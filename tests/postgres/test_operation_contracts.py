"""Shared boundaries exercised through neutral services and native SQL ports."""

import pytest
from sqlalchemy import text

from tabula_rasa.application.recurring import RecurringService
from tabula_rasa.application.reference_data import PayeeService, TagService
from tabula_rasa.application.transactions import TransactionService
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.infrastructure.postgres.concurrency import AggregateKey
from tabula_rasa.infrastructure.postgres.operations import guarded_mutation, repository_operation
from tests.postgres._service_probe import RecurringProbe, ReferenceProbe, TransactionProbe
from tests.postgres._support import account, expense_references, load_baseline, schedule


def transactions(database, scope="alpha", **options):
    return TransactionService(TransactionProbe(database, scope, **options),
        payees=PayeeService(ReferenceProbe(database, scope, "payees")),
        tags=TagService(ReferenceProbe(database, scope, "tags")))


def test_empty_guard_cannot_yield_an_unguarded_write(database):
    with pytest.raises(StorageValidationError) as caught:
        with guarded_mutation(database, "alpha", [], expected={}):
            pytest.fail("An edit/delete guard requires an affected root")
    assert caught.value.code == "baseline_invalid"


def test_bulk_guard_checks_every_loaded_baseline_before_any_write(database):
    with repository_operation(database) as connection:
        expense_references(connection)
        account(connection, account_id="second")
        expense_references(connection, "beta")
    keys = [AggregateKey("alpha", "account", identity) for identity in ("cash", "second")]
    tokens = {key: load_baseline(database, key) for key in keys}
    with guarded_mutation(database, "alpha", [keys[1]], expected={keys[1]: tokens[keys[1]]}) as (connection, rows):
        connection.execute(text("UPDATE accounts SET opening_balance=10 WHERE entity_id='alpha' AND id='second'"))
    entered = False
    with pytest.raises(StorageConflictError) as caught:
        with guarded_mutation(database, "alpha", reversed(keys), expected=tokens):
            entered = True
    assert caught.value.code == "stale"
    assert not entered
    with repository_operation(database, read_only=True) as connection:
        assert connection.scalar(text("SELECT opening_balance FROM accounts WHERE entity_id='alpha' AND id='cash'")) == 0
        assert connection.scalar(text("SELECT opening_balance FROM accounts WHERE entity_id='beta' AND id='cash'")) == 0
    with pytest.raises(StorageValidationError) as caught:
        with guarded_mutation(database, "alpha", keys, expected={keys[0]: tokens[keys[0]]}):
            pytest.fail("Missing second baseline must fail before callbacks")
    assert caught.value.code == "baseline_required"
    with pytest.raises(StorageValidationError) as caught:
        with guarded_mutation(database, "alpha", [AggregateKey("beta", "account", "cash")], expected={}):
            pytest.fail("Selected entity must govern all roots")
    assert caught.value.code == "baseline_invalid"
    # Explicit internal compatibility still locks fresh rows.
    with guarded_mutation(database, "alpha", keys, expected={}, require_baselines=False) as (connection, rows):
        assert len(rows) == 2
        connection.execute(text("UPDATE accounts SET opening_balance=20 WHERE entity_id='alpha'"))


@pytest.mark.parametrize("fail", [False, True])
def test_real_transaction_service_inline_references_share_atomic_commit(database, fail):
    with repository_operation(database) as connection:
        expense_references(connection)
        expense_references(connection, "beta")
    service = transactions(database, fail_occurrence=(None, "2026-10-05") if fail else None)
    command = dict(transaction_id="created", kind="Expense", txn_date="2026-10-05", amount="10",
        account_id="cash", category_id="expense", new_payee_name="Synthetic payee", new_tag_name="Synthetic tag")
    if fail:
        with pytest.raises(StorageValidationError) as caught:
            service.create(**command)
        assert caught.value.code == "invariant"
    else:
        result = service.create(**command)
        assert result["baseline"] == load_baseline(database, AggregateKey("alpha", "entry", "created"))
    with repository_operation(database, read_only=True) as connection:
        for table in ("entries", "entry_tags", "payees", "tags"):
            assert connection.scalar(text(f"SELECT count(*) FROM {table} WHERE entity_id='alpha'")) == (0 if fail else 1)
            assert connection.scalar(text(f"SELECT count(*) FROM {table} WHERE entity_id='beta'")) == 0


@pytest.mark.parametrize("fail_attention", [False, True])
def test_real_recurring_service_reports_only_durable_occurrences_and_rerun_is_unique(database, fail_attention):
    with repository_operation(database) as connection:
        for scope in ("alpha", "beta"):
            expense_references(connection, scope)
            schedule(connection, scope, "z-failing")
            schedule(connection, scope, "a-healthy")
    repository = RecurringProbe(database, "alpha", fail_attention=fail_attention)
    transaction_service = transactions(database, fail_occurrence=("z-failing", "2026-10-02"))
    service = RecurringService(repository, transactions=transaction_service, mixed_use=None)
    first = service.reconcile(as_of="2026-10-03")
    assert first["attention"] == {"z-failing": "validation"}
    assert len(first["generated"]) == 4  # one failing-schedule commit + three healthy ones
    with repository_operation(database, read_only=True) as connection:
        durable = set(connection.execute(text("SELECT id FROM entries WHERE entity_id='alpha'")).scalars())
        assert durable == {row["id"] for row in first["generated"]}
        assert connection.scalar(text("SELECT count(*) FROM entries WHERE entity_id='beta'")) == 0
        assert connection.scalar(text("SELECT count(*) FROM recurring_occurrences WHERE entity_id='alpha'")) == 4
        assert connection.scalar(text("SELECT attention_code FROM recurring_schedules WHERE entity_id='alpha' AND id='z-failing'")) == (
            "" if fail_attention else "validation")
    transaction_service._repository.fail_occurrence = None
    second = service.reconcile(as_of="2026-10-03")
    assert len(second["generated"]) == 2
    assert not durable.intersection(row["id"] for row in second["generated"])
    assert service.reconcile(as_of="2026-10-03")["generated"] == []
    with repository_operation(database, read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM recurring_occurrences WHERE entity_id='alpha'")) == 6
