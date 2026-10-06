"""Supported source/history boundaries, including direct SQL bypass attempts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageValidationError
from tabula_rasa.infrastructure.postgres.concurrency import AggregateKey
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.migrations import current_revision, downgrade, upgrade
from tabula_rasa.infrastructure.postgres.operations import repository_operation
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError
from tests.postgres._support import (
    asset, expense_entry, expense_references, load_baseline, mixed_pair, schedule,
)


def rejected(database, sql, *, code="invariant"):
    with pytest.raises(StorageValidationError) as caught:
        with repository_operation(database) as connection:
            connection.execute(text(sql))
    assert caught.value.code == code
    assert caught.value.__context__ is None


@pytest.mark.parametrize("state", ["complete", "missing_projection", "projection_mismatch"])
def test_mixed_inspection_states_must_describe_actual_rows(database, state):
    with repository_operation(database) as connection:
        expense_references(connection)
        mixed_pair(connection, state=state)
    # A declaration cannot make a missing or mismatched projection complete.
    if state == "complete":
        rejected(database, "UPDATE mixed_use_sources SET relationship_state='projection_mismatch'")
        rejected(database, "UPDATE entries SET reference='changed'")
        rejected(database, "DELETE FROM entries")
    else:
        rejected(database, "UPDATE mixed_use_sources SET relationship_state='complete'")
    with repository_operation(database, read_only=True) as connection:
        assert connection.scalar(text("SELECT relationship_state FROM mixed_use_sources")) == state


def test_complete_pair_and_inline_tags_change_atomically_and_rollback_together(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        mixed_pair(connection)
    key = AggregateKey("alpha", "mixed_use", "source")
    before = load_baseline(database, key)
    rejected(database, "UPDATE postings SET amount=60")
    assert load_baseline(database, key) == before
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE mixed_use_sources SET allocated_amount=60,business_use_percentage=60"))
        connection.execute(text("UPDATE postings SET amount=60"))
        connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
            VALUES ('alpha','tag','tag','Synthetic','synthetic')"""))
        connection.execute(text("INSERT INTO mixed_use_tags VALUES ('alpha','source','tag')"))
        connection.execute(text("INSERT INTO entry_tags VALUES ('alpha','projection','tag')"))
    assert load_baseline(database, key) != before
    rejected(database, "DELETE FROM entry_tags")


def test_recurring_targets_and_provenance_cannot_be_reassigned(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        schedule(connection)
        expense_entry(connection)
    key = AggregateKey("alpha", "entry", "expense")
    before = load_baseline(database, key)
    with repository_operation(database) as connection:
        connection.execute(text("""INSERT INTO recurring_occurrences(entity_id,schedule_id,scheduled_date,
            source_kind,occurrence_type,entry_id)
            VALUES ('alpha','schedule','2026-10-05','transaction','initial','expense')"""))
    assert load_baseline(database, key) != before
    rejected(database, "UPDATE recurring_occurrences SET scheduled_date='2026-10-06'")
    rejected(database, """UPDATE recurring_schedules SET source_kind='mixed_use',total_expense=100,
        business_use_percentage=10,allocation_rationale='Synthetic'""")
    rejected(database, "UPDATE entries SET simple_kind='Income'")
    with repository_operation(database) as connection:
        # Templates can change without rewriting committed occurrence amounts.
        connection.execute(text("UPDATE recurring_schedules SET amount=20"))
        connection.execute(text("DELETE FROM recurring_occurrences"))
    assert load_baseline(database, key) != before


def test_mixed_occurrence_requires_a_complete_pair_and_matching_schedule(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        mixed_pair(connection, state="missing_projection")
        schedule(connection, source_kind="mixed_use")
    rejected(database, """INSERT INTO recurring_occurrences(entity_id,schedule_id,scheduled_date,
        source_kind,occurrence_type,mixed_use_source_id)
        VALUES ('alpha','schedule','2026-10-05','mixed_use','initial','source')""")
    rejected(database, "UPDATE categories SET kind='Income'")


@pytest.mark.parametrize("sql", [
    "UPDATE fixed_assets SET cost_basis=120",
    "UPDATE fixed_assets SET expense_category_id=NULL",
    "UPDATE fixed_assets SET status='retired',retired_date='2026-03-30'",
    "DELETE FROM fixed_assets",
    "UPDATE depreciation_events SET amount=30",
    "DELETE FROM depreciation_events",
    "UPDATE entries SET description='changed'",
    "UPDATE postings SET amount=30",
    "DELETE FROM postings",
    "INSERT INTO asset_period_overrides(entity_id,asset_id,sequence,amount,reason) VALUES ('alpha','asset',2,10,'Synthetic')",
])
def test_posted_depreciation_is_immutable(database, sql):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection, posted=True)
    rejected(database, sql)
    with repository_operation(database) as connection:
        # Ordinary metadata edits and retirement after the event stay supported.
        connection.execute(text("""UPDATE fixed_assets SET name='Renamed',reference='new',
            status='retired',retired_date='2026-04-01'"""))


def test_saved_override_locks_terms_but_not_unposted_reference_metadata(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection, override=True)
    rejected(database, "UPDATE fixed_assets SET useful_life_quarters=8")
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE fixed_assets SET expense_category_id=NULL,reference='new'"))
        connection.execute(text("UPDATE asset_period_overrides SET amount=15,reason='Revised'"))
        connection.execute(text("""INSERT INTO asset_period_overrides(entity_id,asset_id,sequence,amount,reason)
            VALUES ('alpha','asset',2,20,'Later')"""))
    rejected(database, "DELETE FROM asset_period_overrides WHERE sequence=1")


def test_depreciation_event_cannot_index_an_ordinary_expense(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection)
        expense_entry(connection)
    rejected(database, """INSERT INTO depreciation_events(entity_id,asset_id,sequence,entry_id,scheduled_date,amount)
        VALUES ('alpha','asset',1,'expense','2026-10-05',10)""")


def test_waiting_override_writer_rechecks_newly_committed_history(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection, override=True)
    other = Database(DatabaseSettings(database.engine.url))
    started = Event()

    def edit_override():
        with repository_operation(other) as connection:
            started.set()
            connection.execute(text("UPDATE asset_period_overrides SET amount=20"))

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with repository_operation(database) as connection:
                connection.execute(text("SELECT id FROM fixed_assets FOR UPDATE"))
                expense_entry(connection, identity="posted", amount="10", date="2026-03-31", owner="asset")
                connection.execute(text("""INSERT INTO depreciation_events(entity_id,asset_id,sequence,entry_id,scheduled_date,amount)
                    VALUES ('alpha','asset',1,'posted','2026-03-31',10)"""))
                pending = executor.submit(edit_override)
                assert started.wait(5)
                assert not pending.done()
            with pytest.raises(StorageValidationError) as caught:
                pending.result(timeout=5)
            assert caught.value.code == "invariant"
        with repository_operation(database, read_only=True) as connection:
            assert connection.scalar(text("SELECT amount FROM asset_period_overrides")) == 10
    finally:
        other.dispose()


def test_document_link_must_use_logical_mixed_owner(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        mixed_pair(connection)
        connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
            VALUES ('alpha','receipt','receipt','synthetic.pdf','synthetic','synthetic')"""))
    rejected(database, """INSERT INTO document_links(entity_id,document_id,entry_id,position)
        VALUES ('alpha','receipt','projection',1)""")
    with repository_operation(database) as connection:
        connection.execute(text("""INSERT INTO document_links(entity_id,document_id,mixed_use_source_id,position)
            VALUES ('alpha','receipt','source',1)"""))


def test_asset_and_import_targets_exclude_advanced_journals(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection)
        connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind)
            VALUES ('alpha','journal','journal','2026-10-05','journal')"""))
        connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id)
            VALUES ('alpha','first','journal','journal',1,'Debit',10,'cash'),
                   ('alpha','second','journal','journal',2,'Credit',10,'cash')"""))
        connection.execute(text("""INSERT INTO import_batches(entity_id,id,incarnation_id,source_kind,format_version,status)
            VALUES ('alpha','batch','batch','csv','synthetic','complete')"""))
    rejected(database, "UPDATE fixed_assets SET source_entry_id='journal'")
    rejected(database, """INSERT INTO import_records(entity_id,batch_id,source_position,record_kind,entry_id,fingerprint)
        VALUES ('alpha','batch',1,'entry','journal','synthetic')""")


def test_zero_periods_commit_and_history_details_stay_protected(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        asset(connection)
        expense_entry(connection, identity="zero", amount="0", date="2026-03-31", owner="asset")
        connection.execute(text("""INSERT INTO depreciation_events(entity_id,asset_id,sequence,entry_id,scheduled_date,amount)
            VALUES ('alpha','asset',1,'zero','2026-03-31',0)"""))
        connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
            VALUES ('alpha','tag','tag','Synthetic','synthetic')"""))
    rejected(database, "INSERT INTO entry_tags VALUES ('alpha','zero','tag')")


@pytest.mark.parametrize("destination_scope", ["alpha", "beta"])
def test_tag_repointing_checks_both_history_owners_and_entity_scopes(database, destination_scope):
    with repository_operation(database) as connection:
        for scope in ("alpha", "beta"):
            expense_references(connection, scope)
            asset(connection, scope, posted=True)
            expense_entry(connection, scope, "ordinary")
            connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
                VALUES (:scope,'tag','tag','Synthetic','synthetic')"""), {"scope": scope})
        connection.execute(text("INSERT INTO entry_tags VALUES ('alpha','ordinary','tag')"))
    rejected(database, f"""UPDATE entry_tags SET entity_id='{destination_scope}',entry_id='depreciation'
        WHERE entity_id='alpha' AND entry_id='ordinary'""")
    with repository_operation(database, read_only=True) as connection:
        assert connection.execute(text("SELECT entity_id,entry_id FROM entry_tags")).all() == [("alpha", "ordinary")]


@pytest.mark.parametrize("sql", [
    "UPDATE mixed_use_sources SET payee_id='beta-only' WHERE entity_id='alpha'",
    "INSERT INTO mixed_use_tags VALUES ('alpha','source','beta-only')",
    "INSERT INTO schedule_tags VALUES ('alpha','schedule','beta-only')",
    "INSERT INTO asset_tags VALUES ('alpha','asset','beta-only')",
    "INSERT INTO document_links(entity_id,document_id,mixed_use_source_id,position) VALUES ('alpha','beta-only','source',1)",
])
def test_secondary_references_reject_foreign_entity_only_identifiers(database, sql):
    with repository_operation(database) as connection:
        for scope in ("alpha", "beta"):
            expense_references(connection, scope)
            mixed_pair(connection, scope)
            schedule(connection, scope)
            asset(connection, scope)
        for table in ("tags", "payees"):
            connection.execute(text(f"""INSERT INTO {table}(entity_id,id,incarnation_id,name,name_key)
                VALUES ('beta','beta-only','beta-only','Synthetic','synthetic')"""))
        connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
            VALUES ('beta','beta-only','beta-only','synthetic.pdf','synthetic','synthetic')"""))
    before = load_baseline(database, AggregateKey("beta", "mixed_use", "source"))
    rejected(database, sql, code="reference")
    assert load_baseline(database, AggregateKey("beta", "mixed_use", "source")) == before


def test_new_revision_refuses_invalid_existing_data_without_partial_install(database):
    downgrade(database, "0002_aggregate_versions", allow_destructive=True)
    with repository_operation(database) as connection:
        expense_references(connection)
        mixed_pair(connection)
        connection.execute(text("UPDATE entries SET reference='mismatch'"))
    with pytest.raises(DatabaseError) as caught:
        upgrade(database)
    assert caught.value.code == "invariant"
    with database.transaction(read_only=True) as connection:
        assert current_revision(connection) == "0002_aggregate_versions"
        assert connection.scalar(text("SELECT reference FROM entries")) == "mismatch"
        assert connection.scalar(text("SELECT count(*) FROM pg_proc WHERE proname='check_mixed_relationship'")) == 0
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE mixed_use_sources SET relationship_state='projection_mismatch'"))
    upgrade(database)
    assert database.health()["revision"] == "0003_domain_integrity"
