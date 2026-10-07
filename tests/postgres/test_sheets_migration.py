"""Native core loading, source ownership, atomic checkpoints and restart."""

from dataclasses import dataclass, replace
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository, PostgresJournalRepository
from tabula_rasa.infrastructure.postgres.migration import CoreLoader, PostgresMigrationRunner
from tabula_rasa.infrastructure.postgres.runtime import DatabaseError
from tabula_rasa.migration.model import MigrationError
from tests.test_sheets_migration_source import plan_for, values_with_records, values_with_transfer


def counts(database, scope):
    with database.transaction(read_only=True) as connection:
        return {table: connection.scalar(text(f"SELECT count(*) FROM {table} WHERE entity_id=:scope"), {"scope": scope})
                for table in ("accounts", "entries", "postings", "recurring_schedules", "recurring_occurrences", "migration_runs", "migration_units")}


def test_native_dependency_complete_occurrence_restart_and_two_profile_isolation(database):
    plan = plan_for(values_with_records(recurring=True, journal=True))
    runner = PostgresMigrationRunner(database)
    before = counts(database, "alpha")
    dry = runner.execute(plan)
    assert dry["dry_run"] and not dry["load_complete"]
    assert counts(database, "alpha") == before
    first = runner.execute(plan, dry_run=False)
    assert first["loaded_units"] == 4 and first["skipped_units"] == 0
    assert counts(database, "alpha") == dict(accounts=1, entries=2, postings=4, recurring_schedules=1,
                                           recurring_occurrences=1, migration_runs=1, migration_units=4)
    transaction = PostgresTransactionRepository(database, "alpha").list()[0]
    assert transaction["id"] == "entry" and transaction["amount"] == "12.50"
    assert transaction["recurring_schedule_id"] == "schedule"
    assert transaction["recurring_occurrence_type"] == "initial"
    assert transaction["tags"] == ["Synthetic job"]
    journal = PostgresJournalRepository(database, "alpha").list()[0]
    assert journal["id"] == plan.target_id("JournalEntries", "entry")
    assert [line["id"] for line in journal["postings"]] == ["debit", "credit"]
    resumed = runner.execute(plan, dry_run=False)
    assert resumed["loaded_units"] == 0 and resumed["skipped_units"] == 4
    beta = plan_for(values_with_records(recurring=True, journal=True), profile="beta", entity="beta", workbook="workbook-beta")
    runner.execute(beta, dry_run=False)
    assert counts(database, "beta") == counts(database, "alpha")
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT opening_balance FROM accounts WHERE entity_id='alpha'")) == -12.50
        assert connection.scalar(text("SELECT count(*) FROM migration_id_mappings WHERE entity_id='alpha'")) == len(plan.mappings)
        assert connection.scalar(text("SELECT source_updated_at FROM migration_id_mappings WHERE entity_id='alpha' "
                                      "AND source_record_kind='JournalEntries'")).isoformat() == "2026-10-05T00:00:00+00:00"
        assert connection.scalar(text("SELECT count(*) FROM migration_runs WHERE status='validated'")) == 0
    assert not resumed["cutover_authorized"]


def test_unit_failure_rolls_back_entry_and_checkpoint_then_resumes_once(database):
    class FailOnce(CoreLoader):
        failed = False

        def load(self, connection, plan, unit):
            super().load(connection, plan, unit)
            if not self.failed:
                self.failed = True
                raise MigrationError("Synthetic stop after entry writes.")

    plan = plan_for(values_with_records(recurring=True))
    failing = FailOnce()
    runner = PostgresMigrationRunner(database, loaders={"recurring_entry": failing})
    with pytest.raises(MigrationError, match="Synthetic stop"):
        runner.execute(plan, dry_run=False)
    actual = counts(database, "alpha")
    assert actual["entries"] == actual["postings"] == actual["recurring_occurrences"] == 0
    assert actual["recurring_schedules"] == 1
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT status FROM migration_runs")) == "failed"
        assert connection.scalar(text("SELECT status FROM migration_units WHERE unit_kind='recurring_entry'")) == "pending"
    result = runner.execute(plan, dry_run=False)
    assert result["loaded_units"] == 1 and result["skipped_units"] == 2
    assert counts(database, "alpha")["entries"] == 1
    assert runner.execute(plan, dry_run=False)["loaded_units"] == 0


def test_changed_source_binding_or_committed_target_refuses_restart(database):
    runner = PostgresMigrationRunner(database)
    plan = plan_for()
    runner.execute(plan, dry_run=False)
    changed = values_with_records()
    changed["Transactions"][1][changed["Transactions"][0].index("amount")] = "14.00"
    with pytest.raises(MigrationError, match="different run/source"):
        runner.execute(plan_for(changed), dry_run=False)
    with pytest.raises(MigrationError, match="different run/source"):
        runner.execute(plan_for(profile="foreign"), dry_run=False)
    with database.transaction() as connection:
        connection.execute(text("UPDATE entries SET description='Synthetic external edit' WHERE entity_id='alpha'"))
    with pytest.raises(MigrationError, match="committed migration target has changed"):
        runner.execute(plan, dry_run=False)
    assert counts(database, "alpha")["entries"] == 1


def test_missing_loader_and_forged_plan_fail_before_any_target_mutation(database):
    runner = PostgresMigrationRunner(database)
    values = values_with_records()
    fields = values["Mileage"][0]
    row = dict(id="trip", trip_date="2026-10-05", miles="1.2", created_at="2026-10-05T00:00:00Z",
               start_location="Office", destination="Client", business_purpose="Site visit")
    values["Mileage"].append([row.get(field, "") for field in fields])
    plan = plan_for(values)
    assert runner.execute(plan)["missing_loaders"] == ["mileage"]
    with pytest.raises(MigrationError, match="loaders are unavailable"):
        runner.execute(plan, dry_run=False)
    assert counts(database, "alpha")["migration_runs"] == 0
    with pytest.raises(MigrationError, match="plan does not match"):
        runner.execute(replace(plan, units=plan.units[:-1]), dry_run=False)
    assert counts(database, "alpha")["accounts"] == 0


def test_uncertain_commit_keeps_atomic_loaded_checkpoint_and_explicit_resume_does_not_duplicate(database, monkeypatch):
    plan = plan_for()
    original = database.transaction
    calls = 0

    @contextmanager
    def uncertain(**kwargs):
        nonlocal calls
        calls += 1
        call = calls
        with original(**kwargs) as connection:
            yield connection
        # Preparation, foundation, then entry. The actual PostgreSQL commit
        # succeeds, but the caller receives a synthetic unavailable outcome.
        if call == 3:
            raise DatabaseError("unavailable")

    monkeypatch.setattr(database, "transaction", uncertain)
    runner = PostgresMigrationRunner(database)
    with pytest.raises(DatabaseError, match="unavailable"):
        runner.execute(plan, dry_run=False)
    monkeypatch.setattr(database, "transaction", original)
    assert counts(database, "alpha")["entries"] == 1
    resumed = runner.execute(plan, dry_run=False)
    assert resumed["loaded_units"] == 0 and resumed["skipped_units"] == 2
    assert counts(database, "alpha")["postings"] == 2


def test_uninitialized_target_schema_is_rejected_without_initialization(empty_database):
    with pytest.raises(MigrationError, match="initialize it explicitly"):
        PostgresMigrationRunner(empty_database).execute(plan_for(), dry_run=False)
    assert empty_database.health()["revision"] is None


def test_unhashable_extension_preflight_runs_once_and_refuses_foreign_profile_before_writes(database):
    @dataclass
    class ProfileGuard(CoreLoader):
        calls: int = 0

        def preflight(self, plan):
            self.calls += 1
            if plan.snapshot.binding.profile_key != "alpha":
                raise MigrationError("Synthetic profile guard.")

    loader = ProfileGuard()
    runner = PostgresMigrationRunner(database, loaders={"simple_entry": loader, "recurring_entry": loader})
    assert runner.execute(plan_for())["dry_run"]
    assert loader.calls == 1
    with pytest.raises(MigrationError, match="Synthetic profile guard"):
        runner.execute(plan_for(profile="beta", entity="beta", workbook="workbook-beta"), dry_run=False)
    assert counts(database, "beta")["migration_runs"] == 0
    assert counts(database, "beta")["entries"] == 0


def test_normalized_transaction_kind_loads_and_restarts_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    for profile, kind in (("alpha", "expense"), ("beta", " Expense ")):
        values = values_with_records()
        values["Transactions"][1][values["Transactions"][0].index("kind")] = kind
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 2
        assert PostgresTransactionRepository(database, profile).list()[0]["kind"] == "Expense"
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 2
    assert counts(database, "alpha") == counts(database, "beta")


def test_normalized_transfer_without_payee_loads_and_restarts_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    for profile, kind in (("alpha", "transfer"), ("beta", " transfer ")):
        plan = plan_for(values_with_transfer(kind), profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 2
        row = PostgresTransactionRepository(database, profile).list()[0]
        assert row["kind"] == "Transfer" and row["category_id"] == row["payee_id"] == ""
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 2
    assert counts(database, "alpha") == counts(database, "beta")


def test_padded_journal_date_loads_and_restarts_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    for profile in ("alpha", "beta"):
        values = values_with_records(journal=True)
        values["JournalEntries"][1][values["JournalEntries"][0].index("txn_date")] = " 2026-10-05 "
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 3
        assert PostgresJournalRepository(database, profile).list()[0]["txn_date"] == "2026-10-05"
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 3
    assert counts(database, "alpha") == counts(database, "beta")


def test_canonical_occurrence_and_journal_postings_restart_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    for profile in ("alpha", "beta"):
        values = values_with_records(recurring=True, journal=True)
        fields = values["Transactions"][0]
        values["Transactions"][1][fields.index("recurring_scheduled_date")] = "20261005"
        fields = values["JournalPostings"][0]
        for row in values["JournalPostings"][1:]:
            for field in ("target_type", "side", "amount"):
                row[fields.index(field)] = " " + row[fields.index(field)] + " "
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 4
        transaction = PostgresTransactionRepository(database, profile).list()[0]
        assert transaction["recurring_scheduled_date"] == "2026-10-05"
        journal = PostgresJournalRepository(database, profile).list()[0]
        assert [(row["target_type"], row["side"]) for row in journal["postings"]] == [
            ("category", "Debit"), ("account", "Credit")]
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 4
    assert counts(database, "alpha") == counts(database, "beta")


def test_locale_collated_tags_restart_and_detect_changes_in_two_profiles(database):
    # Only this fixture's disposable database changes; the runtime is untouched.
    with database.transaction() as connection:
        connection.execute(text('ALTER TABLE tags ALTER COLUMN id TYPE text COLLATE "en-x-icu"'))
        connection.execute(text('ALTER TABLE schedule_tags ALTER COLUMN tag_id TYPE text COLLATE "en-x-icu"'))
    runner = PostgresMigrationRunner(database)
    for profile in ("alpha", "beta"):
        values = values_with_records(recurring=True)
        fields = values["Tags"][0]
        tag = dict(zip(fields, values["Tags"][1]))
        values["Tags"] = [fields]
        for identity in ("a", "B"):
            record = {**tag, "id": identity, "name": "Synthetic tag " + identity}
            values["Tags"].append([record[field] for field in fields])
        for title in ("Transactions", "RecurringSchedules"):
            values[title][1][values[title][0].index("tag_ids")] = '["B","a"]'
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 3
        assert PostgresTransactionRepository(database, profile).list()[0]["tag_ids"] == ["a", "B"]
        with database.transaction(read_only=True) as connection:
            assert connection.scalars(text("SELECT tag_id FROM schedule_tags WHERE entity_id=:scope ORDER BY tag_id"),
                                      {"scope": profile}).all() == ["a", "B"]
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 3
    assert counts(database, "alpha") == counts(database, "beta")
    # Ordering is immaterial; actual membership changes must still block restart.
    for table, kind in (("entry_tags", "recurring_entry"), ("schedule_tags", "schedule")):
        with database.transaction() as connection:
            connection.execute(text(f"DELETE FROM {table} WHERE entity_id='alpha' AND tag_id='a'"))
        unit = next(unit for unit in plan_for(values, profile="alpha").units if unit.kind == kind)
        with database.transaction(read_only=True) as connection:
            assert not CoreLoader().verify(connection, plan_for(values, profile="alpha"), unit)
    assert runner.execute(plan, dry_run=False)["skipped_units"] == 3


def test_signed_zero_opening_balances_restart_and_detect_drift_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    plans = []
    for profile, opening in (("alpha", "-0.00"), ("beta", "-0.004")):
        values = values_with_records()
        values["Accounts"][1][values["Accounts"][0].index("opening_balance")] = opening
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        plans.append(plan)
        assert plan.snapshot.tables["Accounts"][0]["opening_balance"] == "-0.00"
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 2
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 2
    with database.transaction() as connection:
        connection.execute(text("UPDATE accounts SET opening_balance=1 WHERE entity_id='alpha'"))
    with pytest.raises(MigrationError, match="committed migration target has changed"):
        runner.execute(plans[0], dry_run=False)
    assert runner.execute(plans[1], dry_run=False)["skipped_units"] == 2


def test_normalized_schedule_source_kind_loads_and_restarts_in_two_profiles(database):
    runner = PostgresMigrationRunner(database)
    for profile, source_kind in (("alpha", "Transaction"), ("beta", " Transaction ")):
        values = values_with_records(recurring=True)
        values["RecurringSchedules"][1][values["RecurringSchedules"][0].index("source_kind")] = source_kind
        plan = plan_for(values, profile=profile, entity=profile, workbook=f"workbook-{profile}")
        assert plan.snapshot.tables["RecurringSchedules"][0]["source_kind"] == "transaction"
        assert runner.execute(plan, dry_run=False)["loaded_units"] == 3
        assert runner.execute(plan, dry_run=False)["skipped_units"] == 3
    assert counts(database, "alpha") == counts(database, "beta")


def test_historical_generated_uuid4_load_restart_and_two_profile_isolation(database):
    from tests.test_sheets_migration_source import values_with_legacy_generated_occurrence, LEGACY_RECURRING_ID
    runner = PostgresMigrationRunner(database)
    for profile in ("alpha", "beta"):
        plan = plan_for(values_with_legacy_generated_occurrence(), profile=profile, entity=profile, workbook=f"workbook-{profile}")
        first = runner.execute(plan, dry_run=False)
        assert first["loaded_units"] == 3
        row = PostgresTransactionRepository(database, profile).list()[0]
        assert row["id"] == LEGACY_RECURRING_ID
        assert row["recurring_occurrence_type"] == "generated"
        before = counts(database, profile)
        resumed = runner.execute(plan, dry_run=False)
        assert resumed["loaded_units"] == 0 and resumed["skipped_units"] == 3
        assert counts(database, profile) == before
    assert counts(database, "alpha") == counts(database, "beta")
