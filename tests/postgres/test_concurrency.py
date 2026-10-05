"""Native concurrency primitives; domain adapters remain the later slices' work."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageError, StorageNotFoundError, StorageValidationError
from tabula_rasa.infrastructure.postgres.concurrency import AggregateKey, baseline_for, check_baseline, lock_aggregates
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.operations import repository_operation
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.postgres._support import account, entity, ledger, simple_entry, load_baseline

KEY = AggregateKey("alpha", "account", "cash")


def load(database, key=KEY):
    return load_baseline(database, key)


def mutate(database, token, *, delete=False, key=KEY):
    with repository_operation(database) as connection:
        row = lock_aggregates(connection, [key])[key]
        check_baseline(key, row, token, required=True)
        if delete:
            connection.execute(text("DELETE FROM accounts WHERE entity_id=:scope AND id=:id"),
                               {"scope": key.entity_id, "id": key.record_id})
        else:
            connection.execute(text("UPDATE accounts SET opening_balance=12.34 WHERE entity_id=:scope AND id=:id"),
                               {"scope": key.entity_id, "id": key.record_id})


@pytest.mark.parametrize("delete", [False, True])
def test_later_submission_rejects_an_independently_loaded_stale_baseline(database, delete):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
    other = Database(DatabaseSettings(database.engine.url))
    try:
        first, second = load(database), load(other)
        assert first == second
        mutate(database, first)
        with pytest.raises(StorageConflictError) as caught:
            mutate(other, second, delete=delete)
        assert caught.value.code == "stale"
        assert load(other) != second
        # The compatibility path still locks current data but makes no stale claim.
        with repository_operation(other) as connection:
            row = lock_aggregates(connection, [KEY])[KEY]
            check_baseline(KEY, row, None)
            connection.execute(text("UPDATE accounts SET opening_balance=15 WHERE entity_id='alpha'"))
    finally:
        other.dispose()


def test_overlapping_writer_checks_the_version_after_the_lock_wait(database):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
    other = Database(DatabaseSettings(database.engine.url))
    token = load(other)
    started = Event()

    def contender():
        with repository_operation(other) as connection:
            started.set()
            row = lock_aggregates(connection, [KEY])[KEY]
            check_baseline(KEY, row, token, required=True)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with repository_operation(database) as connection:
                lock_aggregates(connection, [KEY])
                connection.execute(text("UPDATE accounts SET opening_balance=20 WHERE entity_id='alpha'"))
                future = executor.submit(contender)
                assert started.wait(5)
                assert not future.done()
            with pytest.raises(StorageConflictError):
                future.result(timeout=5)
    finally:
        other.dispose()


def test_baseline_scope_incarnation_and_required_policy(database):
    with repository_operation(database) as connection:
        for scope in ("alpha", "beta"):
            entity(connection, scope)
            account(connection, scope)
    original = load(database)
    with repository_operation(database) as connection:
        beta = AggregateKey("beta", "account", "cash")
        row = lock_aggregates(connection, [beta])[beta]
        with pytest.raises(StorageConflictError):
            check_baseline(beta, row, original)
        with pytest.raises(StorageValidationError, match="required"):
            check_baseline(beta, row, None, required=True)
        with pytest.raises(StorageValidationError, match="metadata"):
            baseline_for(KEY, row)
    # Recreate with a new persisted lifetime; the old version-1 token must fail.
    with repository_operation(database) as connection:
        connection.execute(text("DELETE FROM accounts WHERE entity_id='alpha'"))
        connection.execute(text("""INSERT INTO accounts(entity_id,id,name,name_key,type,classification,incarnation_id)
            VALUES ('alpha','cash','cash','cash','Other','Asset','new-lifetime')"""))
    with pytest.raises(StorageConflictError):
        mutate(database, original)
    with pytest.raises(StorageNotFoundError):
        with repository_operation(database) as connection:
            lock_aggregates(connection, [AggregateKey("alpha", "account", "beta-only")])


def test_lock_order_is_independent_of_selection_order(database):
    with repository_operation(database) as connection:
        entity(connection)
        for identity in ("z", "a"):
            account(connection, account_id=identity)
    keys = [AggregateKey("alpha", "account", identity) for identity in ("z", "a")]
    with repository_operation(database) as connection:
        assert [key.record_id for key in lock_aggregates(connection, keys)] == ["a", "z"]


@pytest.mark.parametrize("fail", [False, True])
def test_inline_references_and_complete_accounting_share_the_commit_unit(database, fail):
    with repository_operation(database) as connection:
        ledger(connection)

    def operation():
        with repository_operation(database) as connection:
            with repository_operation(database) as participant:
                assert participant is connection
                participant.execute(text("""INSERT INTO payees(entity_id,id,name,name_key,incarnation_id)
                    VALUES ('alpha','inline','Synthetic payee','synthetic payee','inline')"""))
                participant.execute(text("""INSERT INTO tags(entity_id,id,name,name_key,incarnation_id)
                    VALUES ('alpha','inline','Synthetic tag','synthetic tag','inline')"""))
            simple_entry(connection)
            connection.execute(text("INSERT INTO entry_tags VALUES ('alpha','income','inline')"))
            connection.execute(text("UPDATE entries SET payee_id='inline'"))
            if fail:
                connection.execute(text("UPDATE postings SET amount=9 WHERE position=2"))

    if fail:
        with pytest.raises(StorageValidationError) as caught:
            operation()
        assert caught.value.code == "invariant"
        assert caught.value.__context__ is None
    else:
        operation()
    with repository_operation(database, read_only=True) as connection:
        for table in ("payees", "tags", "entries", "entry_tags"):
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == (0 if fail else 1)


def test_occurrence_units_preserve_committed_results_after_sql_failure(database):
    with repository_operation(database) as connection:
        ledger(connection)

    def occurrence(identity, amount):
        with repository_operation(database, require_outer=True) as connection:
            simple_entry(connection, entry_id=identity, amount=amount)
        return identity

    generated = [occurrence("first", "10")]
    with pytest.raises(StorageValidationError):
        generated.append(occurrence("failed", "0"))
    generated.append(occurrence("unrelated", "20"))
    with repository_operation(database, read_only=True) as connection:
        assert connection.execute(text("SELECT id FROM entries ORDER BY id")).scalars().all() == generated
    with pytest.raises(StorageError) as caught:
        with repository_operation(database):
            occurrence("uncommitted", "10")
    assert caught.value.code == "boundary_mismatch"


def test_nested_provider_error_is_safe_and_aborts_the_whole_operation(database):
    with pytest.raises(StorageError) as outer_error:
        with repository_operation(database) as connection:
            entity(connection)
            with pytest.raises(StorageConflictError) as inner_error:
                with repository_operation(database) as nested:
                    entity(nested)
            assert inner_error.value.code == "duplicate"
            assert inner_error.value.__context__ is None
    assert outer_error.value.code == "operation_aborted"
    with repository_operation(database, read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 0
