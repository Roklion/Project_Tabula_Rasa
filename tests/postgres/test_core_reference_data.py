"""Native reference CRUD, hierarchy, atomic merge/removal and isolation."""

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageNotFoundError, StorageValidationError, StorageError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository, PostgresPayeeRepository, PostgresTagRepository
from tests.postgres.core_support import seed_core, expense, journal_lines, asset_sql


def test_entity_scope_and_blank_only_defaults(database):
    for scope in ('alpha', 'beta'):
        ledger = PostgresLedgerSetupRepository.create_entity(database, scope, scope.title())
        assert ledger.ledger_name == scope.title()
    alpha = create_postgres_services(database, 'alpha')
    beta = create_postgres_services(database, 'beta')
    alpha.accounts.create('Existing', 'Bank')
    assert alpha.ledger.ensure_defaults() == {'accounts': 0, 'categories': 0}
    assert alpha.categories.list() == []
    assert beta.ledger.ensure_defaults() == {'accounts': 2, 'categories': 16}
    assert beta.ledger.ensure_defaults() == {'accounts': 0, 'categories': 0}
    with pytest.raises(StorageNotFoundError):
        create_postgres_services(database, 'missing')
    with pytest.raises(StorageValidationError):
        create_postgres_services(database, '')


def test_account_hierarchy_uniqueness_classification_and_loaded_baselines(database):
    alpha, beta = seed_core(database)
    parent = alpha.accounts.create('Savings', 'Bank', '-5.25')
    child = alpha.accounts.create('Reserve', 'Bank', parent_id=parent['id'])
    assert parent['opening_balance'] == '-5.25'
    with pytest.raises(StorageConflictError):
        alpha.accounts.create(' SAVINGS ', 'Bank')
    with pytest.raises(StorageValidationError):
        alpha.accounts.create('Third level', 'Bank', parent_id=child['id'])
    with pytest.raises(StorageValidationError):
        alpha.accounts.create('Liability child', 'Credit card', parent_id=parent['id'])
    with pytest.raises(StorageValidationError):
        alpha.accounts.update(parent['id'], parent_id=child['id'])
    with pytest.raises(StorageValidationError):
        alpha.accounts.update(parent['id'], classification='Equity')
    with pytest.raises(StorageValidationError):
        beta.accounts.create('Foreign parent', 'Bank', parent_id=parent['id'])
    updated = alpha.accounts.rename(child['id'], 'New name', expected=child)
    assert updated['id'] == child['id'] and updated['baseline'] != child['baseline']
    with pytest.raises(StorageConflictError):
        alpha.accounts.deactivate(child['id'], expected=child)
    alpha.accounts.deactivate(child['id'])  # Documented no-baseline compatibility.
    assert child['id'] not in {row['id'] for row in alpha.accounts.list()}
    assert child['id'] in {row['id'] for row in alpha.accounts.list(active_only=False)}


def test_category_hierarchy_references_and_expected_delete(database):
    alpha, beta = seed_core(database)
    parent = alpha.categories.create('Supplies', 'Expense')
    child = alpha.categories.create('Paper', 'Expense', parent_id=parent['id'])
    alpha.categories.create('Supplies', 'Income')
    with pytest.raises(StorageConflictError):
        alpha.categories.create(' supplies ', 'Expense')
    with pytest.raises(StorageValidationError):
        alpha.categories.update(parent['id'], parent_id=child['id'])
    with pytest.raises(StorageValidationError) as failure:
        alpha.categories.delete(parent['id'])
    assert failure.value.code == 'reference'
    with pytest.raises(StorageNotFoundError):
        beta.categories.delete(child['id'])
    updated = alpha.categories.update(child['id'], name='Stationery', expected=child)
    with pytest.raises(StorageConflictError):
        alpha.categories.delete(child['id'], expected=child)
    alpha.categories.delete(child['id'], expected=updated)
    alpha.categories.delete(parent['id'])
    alpha.transactions.create(transaction_id='expense', **expense())
    with pytest.raises(StorageValidationError):
        alpha.categories.delete('office')
    with pytest.raises(StorageConflictError):
        alpha.categories.update('office', kind='Income')
    alpha.journals.create(entry_id='journal', txn_date='2026-10-05', postings=journal_lines())
    with pytest.raises(StorageConflictError):
        alpha.categories.update('office', kind='Income')


@pytest.mark.parametrize('attribute', ['payees', 'tags'])
def test_managed_reference_reuse_reactivate_rename_and_stale_removal(database, attribute):
    alpha, beta = seed_core(database)
    service = getattr(alpha, attribute)
    created = service.create('  ＡCME   vendor ', active=False)
    assert service.list(active_only=True) == []
    reused = service.create('acme vendor')
    assert reused['id'] == created['id'] and reused['created_at'] == created['created_at']
    assert reused['active'] == 'TRUE'
    other = service.create('Other')
    with pytest.raises(StorageConflictError):
        service.rename(other['id'], ' ACME vendor ')
    changed = service.rename(created['id'], 'Renamed', expected=reused)
    with pytest.raises(StorageConflictError):
        service.remove(created['id'], expected=reused)
    with pytest.raises(StorageNotFoundError):
        getattr(beta, attribute).remove(created['id'])
    service.remove(created['id'], expected=changed)
    assert [item['name'] for item in service.list()] == ['Other']


def test_merge_repoints_simple_journal_and_secondary_refs_and_advances_baselines(database):
    alpha, beta = seed_core(database)
    source, target = alpha.payees.create('Source'), alpha.payees.create('Target')
    old_tag, new_tag = alpha.tags.create('Old'), alpha.tags.create('New')
    txn = alpha.transactions.create(transaction_id='simple', **expense(payee_id=source['id'], tag_ids=[old_tag['id'], new_tag['id']]))
    journal = alpha.journals.create(entry_id='journal', txn_date='2026-10-05', postings=journal_lines(payee_id=source['id']))
    beta.transactions.create(transaction_id='simple', **expense(new_payee_name='Source', new_tag_name='Old'))
    with database.transaction() as connection:
        connection.execute(text(asset_sql()), {'scope': 'alpha', 'entry': 'simple', 'payee': source['id']})
        for tag in (old_tag, new_tag):
            connection.execute(text("INSERT INTO asset_tags(entity_id,asset_id,tag_id) VALUES ('alpha','asset',:id)"), {'id': tag['id']})
        asset_version = connection.scalar(text("SELECT version FROM fixed_assets WHERE entity_id='alpha'"))
    with pytest.raises(StorageValidationError):
        alpha.payees.remove(source['id'])
    with pytest.raises(StorageValidationError):
        alpha.tags.remove(old_tag['id'])
    assert alpha.payees.merge(target['id'], [source['id']], expected=[source, target]) == {'status': 'fully_applied', 'count': '1'}
    current = alpha.transactions.list()[0]
    assert current['payee_id'] == target['id'] and current['baseline'] != txn['baseline']
    assert alpha.journals.get('journal')['postings'][0]['payee_id'] == target['id']
    assert alpha.journals.get('journal')['baseline'] != journal['baseline']
    alpha.tags.merge(new_tag['id'], [old_tag['id']], expected=[old_tag, new_tag])
    assert alpha.transactions.list()[0]['tag_ids'] == [new_tag['id']]
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT payee_id FROM fixed_assets WHERE entity_id='alpha'")) == target['id']
        assert connection.execute(text("SELECT tag_id FROM asset_tags WHERE entity_id='alpha'")).scalars().all() == [new_tag['id']]
        assert connection.scalar(text("SELECT version FROM fixed_assets WHERE entity_id='alpha'")) > asset_version
    assert beta.transactions.list()[0]['payee'] == 'Source'
    assert beta.transactions.list()[0]['tags'] == ['Old']


@pytest.mark.parametrize('repo_type, attribute, method', [(PostgresPayeeRepository, 'payees', '_merge_payee'), (PostgresTagRepository, 'tags', '_merge_tag')])
def test_failed_merge_rolls_back_references_and_aggregate_baselines(database, monkeypatch, repo_type, attribute, method):
    alpha, _ = seed_core(database)
    service = getattr(alpha, attribute)
    source, target = service.create('Source'), service.create('Target')
    data = {'payee_id': source['id']} if attribute == 'payees' else {'tag_ids': [source['id']]}
    original = alpha.transactions.create(transaction_id='simple', **expense(**data))
    apply = getattr(repo_type, method)

    def fail_after_repoint(self, connection, source_id, target_id):
        apply(self, connection, source_id, target_id)
        connection.execute(text('SELECT 1 / 0'))

    monkeypatch.setattr(repo_type, method, fail_after_repoint)
    with pytest.raises(StorageError):
        service.merge(target['id'], [source['id']])
    assert alpha.transactions.list()[0] == original
    assert {row['id'] for row in service.list()} == {source['id'], target['id']}


def test_merges_cover_every_canonical_owner_and_keep_overlapping_entity_ids_isolated(database):
    alpha, beta = seed_core(database)
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            for table in ('payees', 'tags'):
                for identity in ('source', 'target'):
                    connection.execute(text(f'INSERT INTO {table}(entity_id,id,incarnation_id,name,name_key) VALUES (:scope,:id,:id,:id,:id)'),
                                       {'scope': scope, 'id': identity})
            connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,
                business_use_percentage,allocated_amount,account_id,category_id,payee_id,allocation_rationale,expected_projection_entry_id,relationship_state)
                VALUES (:scope,'mixed','mixed','2026-10-05',25,50,12.50,'cash','office','source','Synthetic allocation','projection','missing_projection')"""), {'scope': scope})
            connection.execute(text("""INSERT INTO recurring_schedules(entity_id,id,incarnation_id,name,source_kind,
                recurrence_unit,recurrence_interval,anchor_date,start_date,status,amount,account_id,category_id,payee_id)
                VALUES (:scope,'schedule','schedule','Synthetic','transaction','month',1,'2026-10-05','2026-10-05','paused',12.50,'cash','office','source')"""), {'scope': scope})
            connection.execute(text(asset_sql()), {'scope': scope, 'entry': None, 'payee': 'source'})
            connection.execute(text("""INSERT INTO mileage_records(entity_id,id,incarnation_id,trip_date,miles,start_location,destination,business_purpose)
                VALUES (:scope,'trip','trip','2026-10-05',1.2,'Start','End','Synthetic')"""), {'scope': scope})
            for table, column, identity in [('mixed_use_tags', 'source_id', 'mixed'), ('schedule_tags', 'schedule_id', 'schedule'),
                                            ('asset_tags', 'asset_id', 'asset'), ('mileage_tags', 'mileage_id', 'trip')]:
                for tag_id in ('source', 'target'):
                    connection.execute(text(f'INSERT INTO {table}(entity_id,{column},tag_id) VALUES (:scope,:id,:tag)'),
                                       {'scope': scope, 'id': identity, 'tag': tag_id})
    with database.transaction(read_only=True) as connection:
        initial_versions = {owner: connection.scalar(text(f"SELECT version FROM {owner} WHERE entity_id='alpha'"))
                            for owner in ('mixed_use_sources', 'recurring_schedules', 'fixed_assets', 'mileage_records')}
    beta_loaded = next(row for row in beta.payees.list() if row['id'] == 'source')
    with pytest.raises(StorageConflictError):
        alpha.payees.rename('source', 'Rejected cross-scope token', expected=beta_loaded)
    alpha.payees.merge('target', ['source'])
    alpha.tags.merge('target', ['source'])
    with database.transaction(read_only=True) as connection:
        for owner in ('mixed_use_sources', 'recurring_schedules', 'fixed_assets'):
            assert connection.scalar(text(f"SELECT payee_id FROM {owner} WHERE entity_id='alpha'")) == 'target'
            assert connection.scalar(text(f"SELECT payee_id FROM {owner} WHERE entity_id='beta'")) == 'source'
            assert connection.scalar(text(f"SELECT version FROM {owner} WHERE entity_id='alpha'")) > initial_versions[owner]
        for table in ('mixed_use_tags', 'schedule_tags', 'asset_tags', 'mileage_tags'):
            assert connection.execute(text(f"SELECT tag_id FROM {table} WHERE entity_id='alpha'")).scalars().all() == ['target']
            assert set(connection.execute(text(f"SELECT tag_id FROM {table} WHERE entity_id='beta'")).scalars()) == {'source', 'target'}
        assert connection.scalar(text("SELECT version FROM mileage_records WHERE entity_id='alpha'")) > initial_versions['mileage_records']


def test_multiple_source_merge_deduplicates_tags_and_repoints_journal_lines(database):
    alpha, _ = seed_core(database)
    payees = [alpha.payees.create(name) for name in ('One', 'Two', 'Target')]
    tags = [alpha.tags.create(name) for name in ('One', 'Two', 'Target')]
    original = alpha.transactions.create(transaction_id='simple', **expense(tag_ids=[tag['id'] for tag in tags]))
    postings = journal_lines(payee_id=payees[0]['id'])
    postings[1]['payee_id'] = payees[1]['id']
    journal = alpha.journals.create(entry_id='journal', txn_date='2026-10-05', postings=postings)
    assert alpha.payees.merge(payees[2]['id'], [item['id'] for item in payees[:2]], expected=payees)['count'] == '2'
    assert alpha.tags.merge(tags[2]['id'], [item['id'] for item in tags[:2]], expected=tags)['count'] == '2'
    merged = alpha.transactions.list()[0]
    assert merged['tag_ids'] == [tags[2]['id']] and merged['baseline'] != original['baseline']
    changed = alpha.journals.get('journal')
    assert {line['payee_id'] for line in changed['postings']} == {payees[2]['id']}
    assert changed['baseline'] != journal['baseline']
