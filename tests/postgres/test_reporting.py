"""Native reporting projections with independently calculated accounting totals."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from tabula_rasa.application.reporting_contracts import LedgerFilter, LedgerSnapshot
from tabula_rasa.errors import StorageError, StorageNotFoundError, StorageValidationError
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.reporting import PostgresLedgerQueryRepository
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.postgres._support import account, category, entity
from tests.postgres.core_support import seed_core


@pytest.fixture
def reporting_services(database, monkeypatch):
    monkeypatch.setattr('tabula_rasa.application.transactions.utc_now', lambda: '2026-10-05T12:00:00Z')
    alpha, beta = seed_core(database)
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            account(connection, scope, 'card', classification='Liability')
            account(connection, scope, 'capital', classification='Equity')
            category(connection, scope, 'operations', kind='Expense')
            connection.execute(text("""UPDATE accounts SET opening_balance=CASE id
                WHEN 'cash' THEN 1000 WHEN 'bank' THEN 200 WHEN 'card' THEN -300 ELSE -900 END,
                parent_id=CASE WHEN id='bank' THEN 'cash' END WHERE entity_id=:scope"""), {'scope': scope})
            connection.execute(text("UPDATE categories SET parent_id='operations' WHERE entity_id=:scope AND id='office'"),
                               {'scope': scope})
            connection.execute(text("""INSERT INTO payees(entity_id,id,incarnation_id,name,name_key)
                VALUES (:scope,'vendor','vendor',:name,:name)"""), {'scope': scope, 'name': scope + ' vendor'})
            for identity in ('client', 'internal'):
                connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
                    VALUES (:scope,:id,:id,:name,:name)"""),
                    {'scope': scope, 'id': identity, 'name': scope + ' ' + identity})
    for services in (alpha, beta):
        services.transactions.create(transaction_id='income', txn_date='2026-06-30', kind='Income',
                                     amount='250', account_id='cash', category_id='sales', tag_ids=['client'])
        services.transactions.create(transaction_id='expense', txn_date='2026-07-01', kind='Expense',
                                     amount='40', account_id='cash', category_id='office',
                                     payee_id='vendor', tag_ids=['internal', 'client'],
                                     description='Supplies', reference='reference')
        services.transactions.create(transaction_id='direct', txn_date='2026-07-01', kind='Expense',
                                     amount='10', account_id='bank', category_id='operations')
        services.transactions.create(transaction_id='transfer', txn_date='2026-07-02', kind='Transfer',
                                     amount='100', account_id='cash', to_account_id='bank')
        # Journal posting IDs intentionally overlap the simple posting namespace.
        services.journals.create(entry_id='split', txn_date='2026-07-03', description='Split payment', postings=[
            dict(id='expense:1', target_type='category', target_id='office', side='Debit', amount='15',
                 payee_id='vendor', description='Office portion'),
            dict(id='expense:2', target_type='account', target_id='card', side='Debit', amount='20'),
            dict(id='split:3', target_type='account', target_id='cash', side='Credit', amount='35'),
        ])
        services.journals.create(entry_id='refund', txn_date='2026-07-04', postings=[
            dict(id='refund:1', target_type='account', target_id='cash', side='Debit', amount='7'),
            dict(id='refund:2', target_type='category', target_id='office', side='Credit', amount='7'),
        ])
        services.journals.create(entry_id='contra-income', txn_date='2026-07-05', postings=[
            dict(id='contra:1', target_type='category', target_id='sales', side='Debit', amount='5'),
            dict(id='contra:2', target_type='account', target_id='cash', side='Credit', amount='5'),
        ])
        services.transactions.create(transaction_id='future', txn_date='2026-08-01', kind='Income',
                                     amount='80', account_id='cash', category_id='sales')
    return alpha, beta


def test_native_reports_keep_openings_transfers_contra_activity_and_hierarchies(reporting_services):
    reporting, _ = (services.reporting for services in reporting_services)
    snapshot = reporting.read_ledger()
    assert len(snapshot.transactions) == 5 and len(snapshot.journals) == 3
    # Assets open at 1,200 = liability 300 + capital 900. All activity adds
    # income 325 less expense 58; the transfer changes no total or earnings.
    assert reporting.period_report(snapshot).totals == {'income': 325.0, 'expenses': 58.0, 'net': 267.0}
    period = reporting.period_report(snapshot, start=date(2026, 7, 1), end=date(2026, 7, 31))
    assert period.totals == {'income': -5.0, 'expenses': 58.0, 'net': -63.0}
    assert period.monthly == ({'month': '2026-07', 'income': -5.0, 'expenses': 58.0},)
    assert [(row['category'], row['layer'], row['direct_total'], row['rollup_total'])
            for row in period.expense_categories] == [
        ('operations', 1, 10.0, 58.0), ('office', 2, 48.0, 48.0),
    ]
    assert {row['id']: row['balance'] for row in reporting.account_balances(snapshot)} == {
        'cash': 1157.0, 'bank': 290.0, 'card': -280.0, 'capital': -900.0,
    }
    for as_of, assets, liabilities, equity, earnings in (
        (date(2026, 6, 29), 1200.0, 300.0, 900.0, 0.0),
        (date(2026, 6, 30), 1450.0, 300.0, 1150.0, 250.0),
        (date(2026, 7, 31), 1367.0, 280.0, 1087.0, 187.0),
        (None, 1447.0, 280.0, 1167.0, 267.0),
    ):
        statement = reporting.balance_sheet(snapshot, as_of=as_of)
        assert (statement['total_assets'], statement['total_liabilities'], statement['total_equity'],
                statement['current_earnings'], statement['difference']) == (assets, liabilities, equity, earnings, 0.0)
        parent = next(row for row in statement['assets'] if row['id'] == 'cash')
        assert parent['rollup_balance'] == assets


@pytest.mark.parametrize('filters,expected', [
    (LedgerFilter(), ['future', 'journal:contra-income', 'journal:refund', 'journal:split',
                      'transfer', 'expense', 'direct', 'income']),
    (LedgerFilter(kind='Income'), ['future', 'income']),
    (LedgerFilter(kind='Expense'), ['expense', 'direct']),
    (LedgerFilter(kind='Transfer'), ['transfer']),
    (LedgerFilter(kind='Journal'), ['journal:contra-income', 'journal:refund', 'journal:split']),
    (LedgerFilter(kind='All', start=date(2026, 7, 1), end=date(2026, 7, 1)), ['expense', 'direct']),
    (LedgerFilter(account_ids=('bank',)), ['transfer', 'direct']),
    (LedgerFilter(account_ids=('card',)), ['journal:split']),
    (LedgerFilter(category_ids=('office',)), ['journal:refund', 'journal:split', 'expense']),
    (LedgerFilter(account_ids=('bank',), category_ids=('sales',)),
     ['future', 'journal:contra-income', 'transfer', 'direct', 'income']),
    (LedgerFilter(tag_ids=('missing', 'client')), ['expense', 'income']),
    (LedgerFilter(start=date(2026, 7, 1), end=date(2026, 7, 1), account_ids=('cash',),
                  category_ids=('sales',), tag_ids=('client',)), ['expense']),
    (LedgerFilter(start=date(2026, 8, 2), end=date(2026, 7, 1)), []),
    (LedgerFilter(kind='Journal', tag_ids=('client',)), []),
    (LedgerFilter(account_ids=('unknown',)), []),
])
def test_core_filters_retain_complete_journals_and_inclusive_dates(reporting_services, filters, expected):
    reporting = reporting_services[0].reporting
    query = reporting.query_ledger(filters)
    assert [row.id for row in query.entries] == expected
    for entry in query.entries:
        if entry.id == 'journal:split':
            assert entry.amount == Decimal('35.00')
            assert [line.id for line in entry.journal.postings] == ['expense:1', 'expense:2', 'split:3']


def test_historical_labels_native_values_and_two_entity_isolation(database, reporting_services):
    alpha, beta = reporting_services
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
                VALUES (:scope,'receipt','receipt','synthetic.pdf','synthetic','opaque')"""), {'scope': scope})
            connection.execute(text("""INSERT INTO document_links(entity_id,document_id,entry_id,position)
                VALUES (:scope,'receipt','expense',1)"""), {'scope': scope})
        connection.execute(text("UPDATE accounts SET active=false WHERE entity_id='alpha' AND id='bank'"))
        for table in ('payees', 'tags'):
            connection.execute(text(f"UPDATE {table} SET active=false WHERE entity_id='alpha'"))
    first = alpha.reporting.read_ledger()
    expense = next(row for row in first.transactions if row.id == 'expense')
    assert type(expense.date) is date and type(expense.amount) is Decimal
    assert expense.amount == Decimal('40.00') and expense.receipt_count == 1
    assert expense.description == 'Supplies' and expense.reference == 'reference'
    assert expense.payee_id == 'vendor' and expense.payee == 'alpha vendor'
    assert expense.tag_ids == ('client', 'internal') and expense.tags == ('alpha client', 'alpha internal')
    assert expense.created_at.endswith('Z') and expense.recurring_scheduled_date is None
    bank = next(row for row in first.accounts if row.id == 'bank')
    assert bank.active is False and bank.parent_id == 'cash' and bank.opening_balance == Decimal('200.00')
    assert first.journals[-1].postings[0].payee == 'alpha vendor'
    assert 'baseline' not in asdict(expense) and 'entity_id' not in asdict(expense)

    # Both entities deliberately reuse every local entry/reference/document ID.
    other = beta.reporting.read_ledger()
    other_expense = next(row for row in other.transactions if row.id == 'expense')
    assert other_expense.payee == 'beta vendor' and other_expense.tags == ('beta client', 'beta internal')
    assert other.journals[-1].postings[0].payee == 'beta vendor'
    assert all(row.active for row in other.accounts)
    alpha.payees.rename('vendor', 'Renamed vendor')
    alpha.tags.rename('client', 'Renamed tag')
    for fresh in (False, True):
        refreshed = alpha.reporting.read_ledger(force_refresh=fresh)
        changed = next(row for row in refreshed.transactions if row.id == 'expense')
        assert changed.payee == 'Renamed vendor' and changed.tags == ('Renamed tag', 'alpha internal')
    assert beta.reporting.read_ledger() == other
    assert expense.payee == 'alpha vendor'


def test_empty_entity_and_unknown_scope_have_distinct_results(database):
    with database.transaction() as connection:
        entity(connection)
    repository = PostgresLedgerQueryRepository(database, 'alpha')
    assert repository.read_ledger() == LedgerSnapshot()
    with pytest.raises(StorageNotFoundError, match='business entity'):
        PostgresLedgerQueryRepository(database, 'missing').read_ledger()
    with pytest.raises(StorageValidationError):
        # The entity boundary's existing domain validation rejects no selection.
        PostgresLedgerQueryRepository(database, '')


def test_read_failure_is_safe_propagates_once_and_does_not_cache_a_partial_snapshot(database, reporting_services):
    reporting = reporting_services[0].reporting
    attempts = []

    def fail(connection, cursor, statement, parameters, context, executemany):
        if 'FROM categories WHERE' in statement:
            attempts.append('failed')
            with connection.connection.driver_connection.cursor() as raw:
                raw.execute("SELECT 'synthetic private reporting content'::integer")

    event.listen(database.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(StorageError) as caught:
            reporting.read_ledger()
        assert caught.value.code == 'unavailable' and caught.value.__context__ is None
        assert 'synthetic private' not in str(caught.value)
        assert attempts == ['failed']
    finally:
        event.remove(database.engine, 'before_cursor_execute', fail)
    assert len(reporting.read_ledger().transactions) == 5


@pytest.mark.parametrize('read_only', [False, True])
def test_reporting_requires_its_own_committed_snapshot_boundary(database, reporting_services, read_only):
    with pytest.raises(StorageError) as caught:
        with database.transaction(read_only=read_only):
            reporting_services[0].reporting.read_ledger()
    assert caught.value.code == 'boundary_mismatch'


def test_snapshot_remains_coherent_across_a_committed_reference_and_accounting_write(database, reporting_services):
    reporting = reporting_services[0].reporting
    writer = Database(DatabaseSettings(database.engine.url))
    committed = []

    def write():
        with writer.transaction() as connection:
            account(connection, 'alpha', 'new-cash')
            category(connection, 'alpha', 'new-office', kind='Expense')
            connection.execute(text("""UPDATE accounts SET opening_balance=CASE id
                WHEN 'cash' THEN 900 ELSE 100 END WHERE entity_id='alpha' AND id IN ('cash','new-cash')"""))
            connection.execute(text("""UPDATE postings SET category_id='new-office'
                WHERE entity_id='alpha' AND entry_id IN ('expense','split') AND category_id='office'"""))
            connection.execute(text("""UPDATE postings SET account_id='new-cash'
                WHERE entity_id='alpha' AND entry_id='expense' AND account_id='cash'"""))
            connection.execute(text("UPDATE payees SET name='New vendor',name_key='new vendor' WHERE entity_id='alpha'"))
        committed.append(True)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def interleave(connection, cursor, statement, parameters, context, executemany):
                if 'FROM accounts WHERE' in statement:
                    assert connection.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
                    assert connection.scalar(text('SHOW transaction_read_only')) == 'on'
                    pool.submit(write).result(timeout=10)

            event.listen(database.engine, 'after_cursor_execute', interleave)
            try:
                old = reporting.read_ledger()
            finally:
                event.remove(database.engine, 'after_cursor_execute', interleave)
        assert committed == [True]
        assert {row.id for row in old.accounts} == {'cash', 'bank', 'card', 'capital'}
        assert 'new-office' not in {row.id for row in old.categories}
        old_expense = next(row for row in old.transactions if row.id == 'expense')
        assert (old_expense.account_id, old_expense.category_id, old_expense.payee) == ('cash', 'office', 'alpha vendor')
        assert old.journals[-1].postings[0].target_id == 'office'
        assert reporting.balance_sheet(old)['difference'] == 0.0
        new = reporting.read_ledger(force_refresh=True)
        assert 'new-cash' in {row.id for row in new.accounts} and 'new-office' in {row.id for row in new.categories}
        new_expense = next(row for row in new.transactions if row.id == 'expense')
        assert (new_expense.account_id, new_expense.category_id, new_expense.payee) == ('new-cash', 'new-office', 'New vendor')
        assert new.journals[-1].postings[0].target_id == 'new-office'
        assert reporting.balance_sheet(new)['difference'] == 0.0
    finally:
        writer.dispose()
