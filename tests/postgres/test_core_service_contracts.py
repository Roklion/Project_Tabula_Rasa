"""Supported application workflows retain their domain outcomes on PostgreSQL."""

from copy import deepcopy
from decimal import Decimal

import pytest

from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.reference_data import normalize_tag_ids
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository


@pytest.fixture
def services(database):
    PostgresLedgerSetupRepository.create_entity(database, 'synthetic', 'Synthetic')
    return create_postgres_services(database, 'synthetic')


def test_mileage_workflow_preserves_domain_outcome(services):
    trips = services.mileage.create_round_trip(
        trip_date='2026-10-05', miles='12.34', start_location='Office',
        destination='Client', business_purpose='Meeting', new_tag_name='Job',
    )
    assert [(trip.start_location, trip.destination, trip.miles) for trip in trips] == [
        ('Office', 'Client', '12.3'), ('Client', 'Office', '12.3'),
    ]
    assert [item.id for item in services.mileage.list_trips()] == [trips[1].id, trips[0].id]
    updated = services.mileage.edit_trip(trips[0].id, miles='15.25')
    assert updated.miles == '15.2' and updated.created_at == trips[0].created_at
    services.mileage.delete_trip(trips[1].id)
    assert len(services.mileage.list_trips()) == 1
    assert services.transactions.list() == []


def test_import_workflow_preserves_accounting_outcome(services):
    services.accounts.create('Checking', 'Bank', '0')
    services.accounts.create('Savings', 'Bank', '0')
    services.categories.create('Office', 'Expense')
    source = {'Date': '10/05/2026', 'Transaction Type': 'Expense', 'Account': 'Checking',
              'Split': 'Office', 'Amount': '-12.50', 'Name': 'Vendor', 'Num': 'INV-1'}
    rows = [source, source, {**source, 'Transaction Type': 'Transfer', 'Split': 'Savings', 'Amount': '5'}]
    result = services.imports.import_quickbooks(rows)
    assert [(item['kind'], item['amount']) for item in result] == [('Expense', '12.50'), ('Transfer', '5.00')]
    assert services.imports.import_quickbooks(rows) == []
    assert len(services.payees.list()) == 1
    assert len(services.transactions.list()) == 2


def test_reference_contract_success_failure_and_expected_record_transport(services):
    parent = services.accounts.create('Checking', 'Bank', '-12.25')
    child = services.accounts.create('Reserve', 'Bank', parent_id=parent['id'])
    assert Decimal(str(services.accounts.list()[0]['opening_balance'])) == Decimal('-12.25')
    with pytest.raises(StorageConflictError):
        services.accounts.create('checking', 'Bank')
    with pytest.raises(StorageValidationError):
        services.accounts.create('Deep', 'Bank', parent_id=child['id'])
    loaded = next(row for row in services.accounts.list() if row['id'] == child['id'])
    services.accounts.rename(child['id'], 'Renamed', expected=loaded)
    with pytest.raises(StorageConflictError):
        services.accounts.deactivate(child['id'], expected=loaded)
    services.accounts.deactivate(child['id'])
    assert child['id'] not in {row['id'] for row in services.accounts.list()}
    category = services.categories.create('Office', 'Expense')
    services.categories.create('Office', 'Income')
    changed = services.categories.update(category['id'], name='Supplies', expected=category)
    with pytest.raises(StorageConflictError):
        services.categories.delete(category['id'], expected=category)
    services.categories.delete(category['id'], expected=changed)
    for service in (services.payees, services.tags):
        first = service.create('ＡCME  vendor', active=False)
        reused = service.create('acme vendor')
        assert reused['id'] == first['id'] and reused['active'] == 'TRUE'
        target = service.create('Target')
        assert service.merge(target['id'], [first['id']], expected=[reused, target])['count'] == '1'
        assert [row['id'] for row in service.list()] == [target['id']]
        service.remove(target['id'])
        assert service.list() == []


def test_transaction_and_journal_contracts_keep_identity_domain_rules_and_projection_separation(services):
    account = services.accounts.create('Checking', 'Bank')
    category = services.categories.create('Office', 'Expense')
    data = dict(txn_date='2026-10-05', kind='Expense', amount='12.50', account_id=account['id'], category_id=category['id'])
    first = services.transactions.create(transaction_id='one', **data, new_payee_name='Vendor', new_tag_name='Job')
    assert first['payee'] == 'Vendor' and len(normalize_tag_ids(first['tag_ids'])) == 1
    with pytest.raises(StorageConflictError):
        services.transactions.create(transaction_id='one', **data)
    changed = services.transactions.update('one', expected=first, description='Changed')
    assert changed['id'] == first['id'] and changed['created_at'] == first['created_at']
    with pytest.raises(StorageConflictError):
        services.transactions.update('one', expected=first, amount='15')
    two = services.transactions.create(transaction_id='two', **data)
    loaded = services.transactions.list()
    assert services.transactions.bulk_update(['one', 'two'], expected=loaded, changes={'payee_id': first['payee_id']})['count'] == '1'
    lines = [dict(id='debit', target_type='category', target_id=category['id'], side='Debit', amount='12.50'),
             dict(id='credit', target_type='account', target_id=account['id'], side='Credit', amount='12.50')]
    journal = services.journals.create(entry_id='journal', txn_date='2026-10-05', postings=lines)
    assert len(services.transactions.list()) == 2 and len(services.journals.list()) == 1
    assert journal['total_debits'] == journal['total_credits'] == '12.50'
    bad = deepcopy(lines)
    bad[0]['amount'] = '5'
    with pytest.raises(StorageValidationError):
        services.journals.update('journal', expected=journal, postings=bad)
    assert services.journals.get('journal') == journal
    updated = services.journals.update('journal', expected=journal, description='Updated')
    assert [row['id'] for row in updated['postings']] == ['debit', 'credit']
    services.journals.delete('journal', expected=updated)
    assert services.journals.list() == []
    assert services.transactions.bulk_delete(['one', two['id']], expected=services.transactions.list())['count'] == '2'
    assert services.transactions.list() == []


def test_reporting_contract_has_independent_totals_on_both_backends(services):
    checking = services.accounts.create('Checking', 'Bank', '100')
    savings = services.accounts.create('Savings', 'Bank')
    capital = services.accounts.create('Capital', 'Equity', '-100', classification='Equity')
    sales = services.categories.create('Sales', 'Income')
    operations = services.categories.create('Operations', 'Expense')
    office = services.categories.create('Office', 'Expense', parent_id=operations['id'])
    services.transactions.create(transaction_id='income', txn_date='2026-06-30', kind='Income', amount='50',
                                 account_id=checking['id'], category_id=sales['id'])
    services.transactions.create(transaction_id='expense', txn_date='2026-07-01', kind='Expense', amount='20',
                                 account_id=checking['id'], category_id=office['id'])
    services.transactions.create(transaction_id='transfer', txn_date='2026-07-02', kind='Transfer', amount='30',
                                 account_id=checking['id'], to_account_id=savings['id'])
    services.journals.create(entry_id='split', txn_date='2026-07-03', postings=[
        dict(id='debit', target_type='category', target_id=office['id'], side='Debit', amount='15'),
        dict(id='credit', target_type='account', target_id=checking['id'], side='Credit', amount='15'),
    ])
    services.accounts.deactivate(savings['id'])
    snapshot = services.reporting.read_ledger()
    assert [entry.id for entry in services.reporting.query_ledger(snapshot=snapshot).entries] == [
        'journal:split', 'transfer', 'expense', 'income',
    ]
    assert services.reporting.period_report(snapshot).totals == {'income': 50.0, 'expenses': 35.0, 'net': 15.0}
    assert {row['id']: row['balance'] for row in services.reporting.account_balances(snapshot)} == {
        checking['id']: 85.0, savings['id']: 30.0, capital['id']: -100.0,
    }
    statement = services.reporting.balance_sheet(snapshot)
    assert statement['current_earnings'] == 15.0 and statement['difference'] == 0.0
