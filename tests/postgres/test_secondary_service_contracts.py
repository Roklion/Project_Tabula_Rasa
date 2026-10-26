"""Independent expected workflows execute through the supported PostgreSQL services."""

from datetime import date
from decimal import Decimal

import pytest

from tabula_rasa.errors import StorageConflictError, StorageError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository


@pytest.fixture
def secondary_services(database):
    PostgresLedgerSetupRepository.create_entity(database, 'synthetic', 'Synthetic')
    return create_postgres_services(database, 'synthetic')


def test_recurring_conversion_repetition_month_end_and_mixed_allocation_parity(secondary_services):
    services = secondary_services
    account = services.accounts.create('Checking', 'Bank')['id']
    category = services.categories.create('Office', 'Expense')['id']
    base = dict(txn_date='2026-01-31', account_id=account, category_id=category)
    original = services.transactions.create(transaction_id='existing', **base, kind='Expense', amount='20')
    request = dict(schedule_id='converted', name='Converted', recurrence_unit='month', amount='20',
                   new_payee_name='Vendor', new_tag_name='Job')
    first = services.recurring.from_transaction('existing', expected_transaction=original, **request)
    repeat = services.recurring.from_transaction('existing', expected_transaction=original, **request)
    assert repeat['transaction']['id'] == first['transaction']['id'] == 'existing'
    assert first['transaction']['created_at'] == original['created_at']
    assert first['transaction']['recurring_occurrence_type'] == 'initial'
    services.recurring.reconcile(as_of='2026-04-30')
    values = services.transactions.list()
    assert sorted((row['txn_date'], Decimal(row['amount'])) for row in values) == [
        ('2026-01-31', Decimal('20')), ('2026-02-28', Decimal('20')),
        ('2026-03-31', Decimal('20')), ('2026-04-30', Decimal('20'))]
    assert services.recurring.get('converted')['next_due_date'] == '2026-05-31'
    assert services.recurring.reconcile(as_of='2026-04-30')['generated'] == []
    source = services.mixed_use.create(source_id='mixed', linked_transaction_id='projection', **base,
                total_expense='100', business_use_percentage='33.33333', allocation_rationale='Measured business use',
                new_payee_name='Vendor', new_tag_name='Job')
    assert Decimal(source['allocated_amount']) == Decimal('33.33')
    changed = services.mixed_use.update('mixed', expected_source=source, total_expense='90')
    assert Decimal(changed['allocated_amount']) == Decimal('30.00')
    converted = services.recurring.from_mixed_use('mixed', expected_source=changed, schedule_id='mixed-schedule', name='Mixed')
    repeated = services.recurring.from_mixed_use('mixed', expected_source=changed, schedule_id='mixed-schedule', name='Mixed')
    assert repeated['source']['id'] == converted['source']['id'] == 'mixed'
    assert repeated['transaction']['id'] == 'projection'
    assert Decimal(repeated['transaction']['amount']) == Decimal('30.00')
    assert len(services.payees.list()) == len(services.tags.list()) == 1
    assert services.journals.list() == []
    with pytest.raises(StorageError):
        services.mixed_use.update('mixed', recurring_schedule_id='other')


def test_asset_schedule_posting_and_saved_history_parity(secondary_services):
    services = secondary_services
    category = services.categories.create('Depreciation', 'Expense')['id']
    offset = services.accounts.create('Accumulated depreciation', 'Other', classification='Asset')['id']
    created = services.assets.create(asset_id='asset', name='Synthetic equipment', asset_type='Computers & office equipment',
                acquisition_date='2026-01-01', depreciation_start_date='2026-01-01', cost_basis='100', salvage_value='0',
                useful_life_quarters=4, depreciation_expense_account_id=category, accumulated_depreciation_account_id=offset)
    saved = services.assets.override('asset', 1, '0', 'Unused quarter', as_of_date=date(2026, 12, 31), expected=created)
    posted = services.assets.post_due('asset', '2026-04-01', expected=saved)
    assert [(row['txn_date'], Decimal(row['amount'])) for row in posted] == [
        ('2026-01-01', Decimal('0')), ('2026-04-01', Decimal('33.33'))]
    assert all(row['source_type'] == 'depreciation' and row['source_id'] == 'asset' for row in posted)
    assert all(row['account_id'] == offset and row['category_id'] == category for row in posted)
    assert services.assets.post_due('asset', '2026-04-01') == []
    assert services.journals.list() == []
    for action in (lambda: services.assets.update('asset', cost_basis='200'),
                   lambda: services.assets.delete('asset'),
                   lambda: services.assets.remove_override('asset', 1)):
        with pytest.raises(StorageConflictError):
            action()


@pytest.mark.parametrize('domain', ['schedule', 'mixed'])
def test_native_independent_loaded_callers_reject_stale_edit_and_delete(database, domain):
    from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
    from tabula_rasa.infrastructure.postgres.runtime import Database
    from tests.postgres.core_support import seed_core
    from tests.postgres.secondary_support import schedule, mixed

    alpha, beta = seed_core(database)
    other = Database(DatabaseSettings(database.engine.url))
    try:
        client = create_postgres_services(other, 'alpha')
        if domain == 'schedule':
            alpha.recurring.create(schedule_id='same', **schedule())
            loaded = client.recurring.get('same')
            alpha.recurring.update('same', amount='19')
            with pytest.raises(StorageConflictError):
                client.recurring.update('same', expected=loaded, name='Stale', new_tag_name='Never created')
            with pytest.raises(StorageConflictError):
                client.recurring.end('same', expected_schedule=loaded)
            assert beta.recurring.list() == []
        else:
            alpha.mixed_use.create(source_id='same', linked_transaction_id='projection', **mixed())
            loaded = client.mixed_use.get('same')
            alpha.mixed_use.update('same', total_expense='200')
            with pytest.raises(StorageConflictError):
                client.mixed_use.update('same', expected=loaded, new_tag_name='Never created')
            with pytest.raises(StorageConflictError):
                client.mixed_use.delete('same', expected_source=loaded)
            assert beta.mixed_use.sources() == []
        assert alpha.tags.list() == []
    finally:
        other.dispose()
