"""Real PostgreSQL migration/reconciliation without live bookkeeping or bytes."""

from copy import deepcopy
import json

import pytest
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
from tabula_rasa.infrastructure.postgres.migration_secondary import SecondaryLoader
from tabula_rasa.infrastructure.postgres.migration_reconciliation import PostgresMigrationReconciler
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tabula_rasa.infrastructure.postgres.assets import PostgresAssetRepository
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.infrastructure.postgres.reporting import PostgresLedgerQueryRepository
from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.migration.model import MigrationError
from tests.migration_support import complete_plan, put
from tests.test_sheets_migration_source import plan_for, values_with_records, values_with_mixed_asset_history


def totals(database, profile):
    with database.transaction(read_only=True) as connection:
        return {table: connection.scalar(text(f"SELECT count(*) FROM {table} WHERE entity_id=:scope"), {"scope": profile})
                for table in ("entries", "postings", "mixed_use_sources", "recurring_schedules", "recurring_occurrences",
                              "fixed_assets", "depreciation_events", "mileage_records", "documents", "document_links")}


def test_all_domains_reconcile_and_restart_in_two_profiles_without_regenerating(database):
    runner = PostgresMigrationRunner(database, secondary=True)
    for profile in ("alpha", "beta"):
        plan, values, docs = complete_plan(profile)
        before = deepcopy(values)
        assert runner.execute(plan)["missing_loaders"] == []
        first = runner.execute(plan, dry_run=False)
        assert first["loaded_units"] == len(plan.units)
        expected = dict(entries=6, postings=14, mixed_use_sources=1, recurring_schedules=2,
                        recurring_occurrences=2, fixed_assets=1, depreciation_events=1,
                        mileage_records=1, documents=3, document_links=2)
        assert totals(database, profile) == expected
        report = PostgresMigrationReconciler(database).reconcile(plan)
        assert report["passed"], report["exceptions"]
        assert report["core_passed"] and report["secondary_passed"]
        assert report["evidence_scope"] == "core_and_secondary"
        assert not report["whole_profile_accepted"] and not report["cutover_authorized"]
        safe = json.dumps(report)
        assert "Synthetic" not in safe and "12.50" not in safe and "file-mixed" not in safe
        assert values == before
        resumed = runner.execute(plan, dry_run=False)
        assert resumed["skipped_units"] == len(plan.units) and resumed["loaded_units"] == 0
        assert totals(database, profile) == expected
        history = PostgresAssetRepository(database, profile)
        with database.transaction(read_only=True) as connection:
            assert len(history.history(connection, "asset")) == 1
            assert connection.scalar(text("SELECT status FROM migration_runs WHERE entity_id=:scope"), {"scope": profile}) == "loading"
        receipts = PostgresReceiptRepository(database, profile, store_kind="google_drive", store_scope_key="folder-" + profile)
        assert receipts.references(profile, "ordinary")[0].storage_key == docs[1].storage_key
        ledger = PostgresLedgerQueryRepository(database, profile).read_ledger()
        service = ReportingService(None)
        assert service.period_report(ledger).totals == {"income": 100.1, "expenses": 55.0, "net": 45.1}
        assert plan.target_id("JournalEntries", "entry") != "entry"
    assert totals(database, "alpha") == totals(database, "beta")


def test_core_only_reconciliation_and_empty_target_failures_are_explicit(database):
    plan = plan_for(values_with_records(recurring=False, journal=True))
    before = PostgresMigrationReconciler(database).reconcile(plan)
    assert not before["passed"] and not before["core_passed"]
    PostgresMigrationRunner(database).execute(plan, dry_run=False)
    report = PostgresMigrationReconciler(database).reconcile(plan)
    assert report["passed"], report["exceptions"]
    assert report["evidence_scope"] == "core_only"
    assert not report["whole_profile_accepted"]


@pytest.mark.parametrize("mutation,domain", [
    ("UPDATE entries SET description='Synthetic unexpected edit' WHERE entity_id='alpha' AND id='ordinary'", "Transactions"),
    ("UPDATE mileage_records SET notes='Synthetic unexpected note' WHERE entity_id='alpha'", "Mileage"),
    ("UPDATE documents SET open_url='https://example.invalid/changed' WHERE entity_id='alpha'", "Documents"),
    ("DELETE FROM document_links WHERE entity_id='alpha' AND entry_id='ordinary'", "Documents"),
    ("UPDATE postings SET amount=amount+1 WHERE entity_id='alpha' AND entry_id='ordinary'", "Transactions"),
    ("UPDATE migration_id_mappings SET source_updated_at='2020-01-01' WHERE entity_id='alpha' AND source_record_kind='Assets'", "Migration"),
])
def test_reconciliation_identifies_current_domain_mismatch_without_exposing_values(database, mutation, domain):
    plan, _, _ = complete_plan()
    PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=False)
    with database.transaction() as connection:
        connection.execute(text(mutation))
    report = PostgresMigrationReconciler(database).reconcile(plan)
    assert not report["passed"]
    assert any(item["domain"] == domain for item in report["exceptions"])
    assert "Synthetic unexpected" not in json.dumps(report)
    if domain != "Migration":
        with pytest.raises(MigrationError, match="committed migration target has changed"):
            PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=False)


def test_secondary_failure_rolls_back_entire_owner_history_and_resumes_once(database):
    class FailOnce(SecondaryLoader):
        failed = False

        def load(self, connection, plan, unit):
            super().load(connection, plan, unit)
            if not self.failed:
                self.failed = True
                raise MigrationError("Synthetic stop in complete asset unit.")

    plan, _, _ = complete_plan()
    loader = FailOnce()
    runner = PostgresMigrationRunner(database, secondary=True, loaders={"asset_history": loader})
    with pytest.raises(MigrationError, match="Synthetic stop"):
        runner.execute(plan, dry_run=False)
    assert totals(database, "alpha")["fixed_assets"] == totals(database, "alpha")["depreciation_events"] == 0
    assert not PostgresMigrationReconciler(database).reconcile(plan)["passed"]
    assert runner.execute(plan, dry_run=False)["loaded_units"] >= 1
    assert PostgresMigrationReconciler(database).reconcile(plan)["passed"]
    assert runner.execute(plan, dry_run=False)["loaded_units"] == 0


def test_missing_acquisition_provenance_fails_before_run_or_ledger_writes(database):
    values = values_with_mixed_asset_history()
    put(values, "Assets", 1, source_transaction_id="missing-historical-entry")
    plan = plan_for(values)
    with pytest.raises(MigrationError, match="acquisition reference"):
        PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=False)
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM migration_runs")) == 0
    assert totals(database, "alpha")["entries"] == 0


def test_existing_empty_entity_must_match_frozen_display_identity_before_preparation(database):
    from tests.postgres._support import entity
    plan, _, _ = complete_plan()
    with database.transaction() as connection:
        entity(connection, "alpha")
    with pytest.raises(MigrationError, match="identity/defaults differ"):
        PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=False)
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM migration_runs")) == 0


def test_added_core_activity_fails_counts_and_financial_reconciliation(database):
    values = values_with_records()
    put(values, "Accounts", 1, active="TRUE")
    plan = plan_for(values)
    PostgresMigrationRunner(database).execute(plan, dry_run=False)
    # Supported runtime create adds balanced activity, so balance checks alone
    # would pass. Exact identity sets and report output must still disagree.
    repo = PostgresTransactionRepository(database, "alpha")
    from tabula_rasa.transaction import prepare_transaction
    repo.create("additional", build=lambda refs, _: prepare_transaction(
        dict(txn_date="2026-10-05", kind="Expense", amount="1.00", account_id="cash", category_id="office"),
        transaction_id="additional", accounts=refs.accounts, categories=refs.categories,
        payees=refs.payees, tags=refs.tags, create_payee=None, create_tag=None,
        original_transaction={"account_id": "cash", "category_id": "office"}))
    report = PostgresMigrationReconciler(database).reconcile(plan)
    assert not report["passed"]
    assert any(item["domain"] == "Reports" for item in report["exceptions"])
