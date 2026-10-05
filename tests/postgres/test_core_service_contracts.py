"""The same supported application workflows run on Sheets and PostgreSQL."""

from copy import deepcopy
from decimal import Decimal

import pytest

from tabula_rasa.application.services import assemble_application_services
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.reference_data import normalize_tag_ids
from tabula_rasa.infrastructure.google_sheets import (
    GoogleSheetsAccountRepository, GoogleSheetsCategoryRepository,
    GoogleSheetsLedgerSetupRepository, GoogleSheetsPayeeRepository, GoogleSheetsTagRepository,
    GoogleSheetsTransactionRepository, GoogleSheetsJournalRepository,
)
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


@pytest.fixture(params=['sheets', 'postgres'])
def services(request):
    if request.param == 'postgres':
        database = request.getfixturevalue('database')
        PostgresLedgerSetupRepository.create_entity(database, 'synthetic', 'Synthetic')
        return create_postgres_services(database, 'synthetic')
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    return assemble_application_services(
        'synthetic', ledger_repository=GoogleSheetsLedgerSetupRepository(storage),
        account_repository=GoogleSheetsAccountRepository(storage),
        category_repository=GoogleSheetsCategoryRepository(storage),
        payee_repository=GoogleSheetsPayeeRepository(storage), tag_repository=GoogleSheetsTagRepository(storage),
        transaction_repository=GoogleSheetsTransactionRepository(storage),
        journal_repository=GoogleSheetsJournalRepository(storage),
    )


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
