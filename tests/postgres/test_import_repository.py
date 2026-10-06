"""Real PostgreSQL bootstrap/import success, rollback, provenance and isolation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageValidationError, StorageError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository
from tabula_rasa.infrastructure.postgres.imports import PostgresTransactionImportRepository
from tabula_rasa.ledger_defaults import DEFAULT_ACCOUNTS, DEFAULT_CATEGORIES
from tests.postgres.core_support import seed_core


def qb(**changes):
    return {**{'Date': '10/05/2026', 'Transaction Type': 'Expense', 'Account': 'cash',
               'Split': 'office', 'Amount': '-12.50', 'Name': 'Vendor', 'Num': 'INV-1',
               'Memo/Description': 'Supplies'}, **changes}


def csv(**changes):
    return {**{'Date': '2026-10-05', 'Type': 'Expense', 'Account': 'cash',
               'Category': 'office', 'Amount': '12.50', 'Payee': 'Vendor',
               'Description': 'Supplies', 'Reference': 'INV-1'}, **changes}


def test_empty_ledger_bootstrap_is_atomic_idempotent_and_entity_scoped(database):
    services = []
    for scope in ('alpha', 'beta'):
        PostgresLedgerSetupRepository.create_entity(database, scope, scope.title())
        services.append(create_postgres_services(database, scope))
    alpha, beta = services
    expected = {'accounts': len(DEFAULT_ACCOUNTS), 'categories': sum(map(len, DEFAULT_CATEGORIES.values()))}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: alpha.ledger.ensure_defaults(), range(2)))
    assert sorted(results, key=lambda item: item['accounts']) == [{'accounts': 0, 'categories': 0}, expected]
    assert alpha.ledger.get_info().name == 'Alpha'
    assert beta.accounts.list() == beta.categories.list() == []
    assert beta.ledger.ensure_defaults() == expected
    assert alpha.ledger.ensure_defaults() == {'accounts': 0, 'categories': 0}
    assert len(alpha.accounts.list()) == len(DEFAULT_ACCOUNTS)
    assert {item['id'] for item in alpha.accounts.list()}.isdisjoint(item['id'] for item in beta.accounts.list())
    assert all(item['opening_balance'] == '0.00' for item in alpha.accounts.list())
    assert alpha.transactions.list() == []


def test_quickbooks_import_projections_positions_duplicates_and_retry(database):
    alpha, beta = seed_core(database)
    rows = [qb(), qb(), qb(**{'Transaction Type': 'Transfer', 'Split': 'bank', 'Name': '',
                              'Num': 'T-1', 'Amount': '5'})]
    assert alpha.imports.preview_quickbooks(rows)['summary']['duplicates'] == 1
    made = alpha.imports.import_quickbooks(rows)
    assert [item['kind'] for item in made] == ['Expense', 'Transfer']
    assert made[0]['payee'] == 'Vendor'
    assert made[1]['category_id'] == '' and made[1]['to_account_id'] == 'bank'
    assert alpha.imports.import_quickbooks(rows) == []
    alpha.transactions.update(made[0]['id'], expected=made[0], description='Changed')
    # A different submission still recognizes preserved source fingerprints.
    assert alpha.imports.import_quickbooks([qb()]) == []
    assert len(beta.imports.import_quickbooks(rows)) == 2
    with database.transaction(read_only=True) as connection:
        accepted = connection.execute(text(
            "SELECT source_position,entry_id FROM import_records WHERE entity_id='alpha' ORDER BY source_position"
        )).all()
        assert [tuple(row) for row in accepted] == [(2, made[0]['id']), (4, made[1]['id'])]
        assert connection.scalar(text("SELECT count(*) FROM postings WHERE entity_id='alpha'")) == 4
        assert connection.execute(text(
            "SELECT entry_id FROM postings WHERE entity_id='alpha' GROUP BY entry_id "
            "HAVING sum(CASE side WHEN 'Debit' THEN amount ELSE -amount END)<>0"
        )).all() == []
    alpha.transactions.delete(made[1]['id'])
    assert alpha.imports.import_quickbooks(rows) == []  # Completed batch survives target deletion.
    assert len(beta.transactions.list()) == 2


def test_auto_create_and_csv_share_canonical_validation_and_confirmed_replay(database):
    PostgresLedgerSetupRepository.create_entity(database, 'alpha', 'Alpha')
    alpha = create_postgres_services(database, 'alpha')
    rows = [qb(Account='Checking', Split='Office'), qb(Account='Checking', Split='Sales',
            Amount='50.25', **{'Transaction Type': 'Deposit', 'Num': 'I-1'}),
            qb(Account='Checking', Split='Owner investment', Amount='100', Num='E-1')]
    assert alpha.imports.preview_quickbooks(rows, auto_create=True)['errors'] == []
    made = alpha.imports.import_quickbooks(rows, auto_create=True)
    assert [item['kind'] for item in made] == ['Expense', 'Income', 'Transfer']
    assert any(item['classification'] == 'Equity' for item in alpha.accounts.list())
    csv_rows = [csv(Account=' checking ', Category=' OFFICE ', Amount='5.125', Payee='vendor'),
                csv(Account='Checking', Category='Sales', Type='Income', Amount='2', Reference='CSV-2')]
    created = alpha.imports.import_csv(iter(csv_rows))
    assert [item['amount'] for item in created] == ['5.12', '2.00']
    assert len(alpha.payees.list()) == 1
    assert alpha.imports.import_csv(csv_rows) == []
    alpha.transactions.update(created[0]['id'], expected=created[0], amount='6')
    assert alpha.imports.import_csv(csv_rows) == []
    legitimate = csv(Account='Checking', Category='Office', Reference='CSV-DUP')
    assert len(alpha.imports.import_csv([legitimate, legitimate])) == 2
    assert alpha.imports.import_csv([legitimate, legitimate]) == []
    assert len(alpha.transactions.list()) == 7


def test_import_validation_and_deferred_failure_roll_back_all_participants(database, monkeypatch):
    PostgresLedgerSetupRepository.create_entity(database, 'alpha', 'Alpha')
    alpha = create_postgres_services(database, 'alpha')
    with pytest.raises(StorageValidationError, match='invalid rows'):
        alpha.imports.import_quickbooks([qb(Account='Checking', Split='Office', Date='invalid')], auto_create=True)
    assert alpha.accounts.list() == [] and alpha.categories.list() == []
    import tabula_rasa.infrastructure.postgres.imports as adapter
    complete = adapter.complete_import

    def unbalance(connection, scope, identity, source, version, records):
        complete(connection, scope, identity, source, version, records)
        connection.execute(text("UPDATE postings SET amount=amount+1 WHERE entity_id=:scope AND position=1"),
                           {'scope': scope})

    with monkeypatch.context() as patch:
        patch.setattr(adapter, 'complete_import', unbalance)
        with pytest.raises(StorageValidationError) as failure:
            alpha.imports.import_quickbooks([qb(Account='Checking', Split='Office')], auto_create=True)
        assert failure.value.code == 'invariant'
        assert failure.value.__context__ is None
    assert alpha.accounts.list() == alpha.categories.list() == alpha.payees.list() == []
    assert alpha.transactions.list() == []
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM import_batches')) == 0
        assert connection.scalar(text('SELECT count(*) FROM import_records')) == 0
    assert len(alpha.imports.import_quickbooks([qb(Account='Checking', Split='Office')], auto_create=True)) == 1


def test_csv_late_validation_and_bounded_batch_do_not_leave_partial_data(database):
    alpha, beta = seed_core(database)
    with pytest.raises(StorageValidationError):
        alpha.imports.import_csv([csv(Payee='Rolled back'), csv(Date='invalid')])
    assert alpha.payees.list() == [] and alpha.transactions.list() == []
    with pytest.raises(StorageValidationError, match='1,000'):
        alpha.imports.import_csv(csv() for _ in range(1001))
    assert alpha.payees.list() == [] and alpha.transactions.list() == []
    assert beta.transactions.list() == []
    assert len(alpha.imports.import_csv([csv()])) == 1


def test_concurrent_imports_select_duplicates_under_the_database_guard(database):
    alpha, _ = seed_core(database)
    repos = [PostgresTransactionImportRepository(database, 'alpha') for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda repo: repo.import_quickbooks([qb()]), repos))
    assert sorted(map(len, results)) == [0, 1]
    assert len(alpha.transactions.list()) == 1
    assert len(alpha.payees.list()) == 1


@pytest.mark.parametrize('source', ['csv', 'quickbooks'])
def test_replay_after_lost_commit_confirmation_does_not_duplicate(database, monkeypatch, source):
    alpha, _ = seed_core(database)
    repo = PostgresTransactionImportRepository(database, 'alpha')
    operation = repo.operation
    lost = True

    @contextmanager
    def lose_confirmation(**options):
        nonlocal lost
        with operation(**options) as connection:
            yield connection
        if lost:
            lost = False
            raise StorageError('Commit confirmation unavailable; inspect the ledger.', code='unavailable')

    monkeypatch.setattr(repo, 'operation', lose_confirmation)
    command = repo.import_csv if source == 'csv' else repo.import_quickbooks
    rows = [csv() if source == 'csv' else qb()]
    with pytest.raises(StorageError, match='confirmation'):
        command(rows)
    assert command(rows) == []
    assert len(alpha.transactions.list()) == len(alpha.payees.list()) == 1
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM import_batches')) == 1
        assert connection.scalar(text('SELECT count(*) FROM import_records')) == 1
