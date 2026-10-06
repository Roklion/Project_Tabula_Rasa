"""Native accounting CRUD/bulk, projection parity, rollback and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageNotFoundError, StorageValidationError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository, PostgresJournalRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.postgres.core_support import seed_core, expense, journal_lines, asset_sql


def test_simple_crud_postings_transfers_filters_and_disjoint_journal_reads(database):
    alpha, beta = seed_core(database)
    created = alpha.transactions.create(transaction_id='expense', **expense(new_payee_name='Vendor', new_tag_name='Job'))
    assert created['payee'] == 'Vendor' and created['tags'] == ['Job']
    assert created['amount'] == '12.50'
    assert beta.transactions.list() == []
    alpha.transactions.create(transaction_id='income', **expense(kind='Income', category_id='sales', amount='50.25'))
    alpha.transactions.create(transaction_id='transfer', **expense(kind='Transfer', category_id='', to_account_id='bank', amount='5'))
    assert {row['id'] for row in alpha.transactions.list(account_ids=['bank'])} == {'transfer'}
    assert alpha.transactions.list(account_ids=[]) == []
    assert alpha.transactions.list(start='2026-10-06') == []
    assert len(alpha.transactions.list(end='2026-10-05', kind='Expense')) == 1
    assert alpha.journals.list() == []
    with database.transaction(read_only=True) as connection:
        actual = connection.execute(text("SELECT id,side,account_id,category_id,amount FROM postings WHERE entry_id='expense' ORDER BY position")).all()
        assert [(row.id, row.side, row.account_id, row.category_id, str(row.amount)) for row in actual] == [
            ('expense:1', 'Debit', None, 'office', '12.50'), ('expense:2', 'Credit', 'cash', None, '12.50'),
        ]
        assert connection.scalar(text("SELECT count(*) FROM entries WHERE projection_kind='simple'")) == 3
    updated = alpha.transactions.update('expense', expected=created, amount='17.75', description='Changed')
    assert updated['id'] == created['id'] and updated['created_at'] == created['created_at']
    assert updated['baseline'] != created['baseline']
    with pytest.raises(StorageConflictError):
        alpha.transactions.delete('expense', expected=created)
    alpha.transactions.delete('expense', expected=updated)
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM postings WHERE entry_id='expense'")) == 0
    assert alpha.payees.list()[0]['name'] == 'Vendor'


def test_transaction_validation_and_direct_repository_boundary(database):
    alpha, beta = seed_core(database)
    foreign = beta.categories.create('Foreign', 'Expense')
    for data in (expense(category_id=foreign['id']), expense(amount='-1'), expense(category_id='sales'),
                 expense(kind='Transfer', category_id='', to_account_id='cash')):
        with pytest.raises(StorageValidationError):
            alpha.transactions.create(**data)
    account = alpha.accounts.list(active_only=False)[0]
    alpha.accounts.deactivate(account['id'])
    with pytest.raises(StorageValidationError):
        alpha.transactions.create(**expense(account_id=account['id']))
    repository = PostgresTransactionRepository(database, 'alpha')
    with pytest.raises(StorageValidationError):
        repository.create('one', build=lambda refs, current: {**expense(), 'id': 'different'})
    with pytest.raises(StorageValidationError):
        repository.create('one', build=lambda refs, current: {**expense(account_id=account['id']), 'id': 'one'})
    assert alpha.transactions.list() == []


def test_duplicate_identity_checked_before_callback_and_inline_creation(database):
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='same', **expense())
    calls = []
    repository = PostgresTransactionRepository(database, 'alpha')
    with pytest.raises(StorageConflictError):
        repository.create('same', build=lambda refs, current: calls.append('called'))
    assert calls == []
    with pytest.raises(StorageConflictError):
        alpha.transactions.create(transaction_id='same', **expense(new_payee_name='Never created', new_tag_name='Never created'))
    assert alpha.payees.list() == alpha.tags.list() == []


def test_inline_references_roll_back_on_late_validation_and_sql_failure(database, monkeypatch):
    alpha, _ = seed_core(database)
    with pytest.raises(StorageValidationError):
        alpha.transactions.create(transaction_id='failed', **expense(
            new_payee_name='Rolled back', new_tag_name='Rolled back',
            receipt_references=[{'id': 'not-registered', 'name': 'synthetic.pdf'}],
        ))
    assert alpha.transactions.list() == alpha.payees.list() == alpha.tags.list() == []
    write = PostgresTransactionRepository.write_lines

    def unbalance(self, connection, identity, lines):
        write(self, connection, identity, lines)
        connection.execute(text('UPDATE postings SET amount=amount+1 WHERE entity_id=:scope AND entry_id=:id AND position=2'),
                           {'scope': self.entity_id, 'id': identity})

    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', unbalance)
    with pytest.raises(StorageValidationError):
        alpha.transactions.create(transaction_id='failed', **expense(new_payee_name='Rollback at commit', new_tag_name='Rollback at commit'))
    assert alpha.transactions.list() == alpha.payees.list() == alpha.tags.list() == []


@pytest.mark.parametrize('command', ['create', 'update'])
def test_inline_reactivation_refreshes_selected_references_and_rolls_back_on_failure(database, command):
    alpha, beta = seed_core(database)
    inactive = [service.create(name, active=False) for service, name in
                ((alpha.payees, 'Vendor'), (alpha.tags, 'Job'))]
    beta_inactive = [service.create(name, active=False) for service, name in
                     ((beta.payees, 'Vendor'), (beta.tags, 'Job'))]
    original = alpha.transactions.create(transaction_id='one', **expense()) if command == 'update' else None

    def mutate(**changes):
        if command == 'create':
            return alpha.transactions.create(transaction_id='one', **expense(**changes))
        return alpha.transactions.update('one', expected=original, **changes)

    changed = mutate(new_payee_name='vendor', new_tag_name='job')
    assert changed['payee_id'] == inactive[0]['id'] and changed['tag_ids'] == [inactive[1]['id']]
    assert changed['payee'] == 'Vendor' and changed['tags'] == ['Job']
    for service, before in zip((alpha.payees, alpha.tags), inactive):
        current = service.list()[0]
        assert current['active'] == 'TRUE' and current['created_at'] == before['created_at']
        assert current['baseline'] != before['baseline']
        service.update(current['id'], active=False)
    inactive_after = [alpha.payees.list()[0], alpha.tags.list()[0]]
    original = changed
    if command == 'create':
        alpha.transactions.delete('one', expected=changed)
    with pytest.raises(StorageValidationError):
        mutate(payee_id='', tag_ids=[], new_payee_name='Vendor', new_tag_name='Job',
               receipt_references=[{'id': 'not-registered', 'name': 'synthetic.pdf'}])
    assert [alpha.payees.list()[0], alpha.tags.list()[0]] == inactive_after
    assert alpha.transactions.list() == ([] if command == 'create' else [changed])
    assert [beta.payees.list()[0], beta.tags.list()[0]] == beta_inactive
    assert beta.transactions.list() == []


def test_baseline_survives_display_renames_but_rejects_recreated_lifetime(database):
    alpha, _ = seed_core(database)
    original = alpha.transactions.create(transaction_id='stable', **expense(new_payee_name='Vendor', new_tag_name='Job'))
    alpha.payees.rename(original['payee_id'], 'Renamed vendor')
    alpha.tags.rename(original['tag_ids'][0], 'Renamed job')
    assert alpha.transactions.list()[0]['baseline'] == original['baseline']
    alpha.transactions.update('stable', expected=original, description='Allowed')
    alpha.transactions.delete('stable')
    replacement = alpha.transactions.create(transaction_id='stable', **expense())
    assert replacement['baseline'] != original['baseline']
    with pytest.raises(StorageConflictError):
        alpha.transactions.update('stable', expected={'baseline': original['baseline']}, description='Must fail')
    alpha.transactions.update('stable', description='Legacy caller remains supported')


def test_bulk_update_revalidates_selection_and_bulk_delete_rolls_back_at_commit(database):
    alpha, _ = seed_core(database)
    one = alpha.transactions.create(transaction_id='one', **expense())
    two = alpha.transactions.create(transaction_id='two', **expense())
    tag = alpha.tags.create('Batch')
    assert alpha.transactions.bulk_update(['one', 'two'], expected=[one, two], changes={'tag_ids': [tag['id']]}) == {
        'status': 'fully_applied', 'count': '2',
    }
    loaded = alpha.transactions.list()
    assert all(row['tag_ids'] == [tag['id']] for row in loaded)
    assert alpha.transactions.bulk_update(['one', 'two'], expected=loaded, changes={'tag_ids': [tag['id']]})['count'] == '0'
    with pytest.raises(StorageConflictError):
        alpha.transactions.bulk_update(['one', 'two'], expected=[one, two], changes={'payee_id': ''})
    with pytest.raises(StorageConflictError):
        alpha.transactions.bulk_delete(['one', 'two'], expected=[one])
    with database.transaction() as connection:
        connection.execute(text(asset_sql()), {'scope': 'alpha', 'entry': 'two', 'payee': None})
    with pytest.raises(StorageValidationError) as failure:
        alpha.transactions.bulk_delete(['one', 'two'], expected=loaded)
    assert failure.value.code == 'reference'
    assert alpha.transactions.list() == loaded  # One deferred FK failure rolls back the entire batch.
    with database.transaction() as connection:
        connection.execute(text("DELETE FROM fixed_assets WHERE entity_id='alpha'"))
    assert alpha.transactions.bulk_delete(['one', 'two'], expected=loaded)['count'] == '2'
    assert alpha.transactions.list() == []


def test_journal_crud_stable_postings_cross_entity_checks_and_rollback(database):
    alpha, beta = seed_core(database)
    alpha.transactions.create(transaction_id='simple', **expense())
    lines = journal_lines()
    lines[0]['id'], lines[1]['id'] = 'simple:1', 'simple:2'
    original = alpha.journals.create(entry_id='journal', txn_date='2026-10-05', postings=lines)
    assert original['total_debits'] == original['total_credits'] == '12.50'
    assert len(alpha.transactions.list()) == len(alpha.journals.list()) == 1
    assert beta.journals.list() == []
    with pytest.raises(StorageNotFoundError):
        beta.journals.get('journal')
    with pytest.raises(StorageNotFoundError):
        alpha.journals.get('simple')
    foreign = beta.payees.create('Foreign')
    with pytest.raises(StorageValidationError):
        alpha.journals.create(entry_id='foreign', txn_date='2026-10-05', postings=journal_lines(payee_id=foreign['id']))
    bad = deepcopy(lines)
    bad[1]['amount'] = '10'
    with pytest.raises(StorageValidationError):
        alpha.journals.update('journal', expected=original, postings=bad)
    assert alpha.journals.get('journal') == original
    with pytest.raises(StorageConflictError):
        alpha.journals.create(entry_id='duplicate-lines', txn_date='2026-10-05', postings=lines)
    assert len(alpha.journals.list()) == 1
    changed = alpha.journals.update('journal', expected=original, description='Edit')
    assert [line['id'] for line in changed['postings']] == ['simple:1', 'simple:2']
    assert changed['created_at'] == original['created_at'] and changed['baseline'] != original['baseline']
    with pytest.raises(StorageConflictError):
        alpha.journals.delete('journal', expected=original)
    alpha.journals.delete('journal', expected=changed)
    assert alpha.journals.list() == []


@pytest.mark.parametrize('kind', ['transaction', 'journal'])
def test_two_independent_loaded_baselines_reject_later_stale_update_and_delete(database, kind):
    alpha, _ = seed_core(database)
    second_database = Database(DatabaseSettings(database.engine.url))
    try:
        second = create_postgres_services(second_database, 'alpha')
        if kind == 'transaction':
            alpha.transactions.create(transaction_id='one', **expense())
            first_baseline, second_baseline = alpha.transactions.list()[0], second.transactions.list()[0]
            alpha.transactions.update('one', expected=first_baseline, description='Committed first')
            with pytest.raises(StorageConflictError) as failure:
                second.transactions.update('one', expected=second_baseline, description='Stale after commit')
            assert failure.value.code == 'stale'
            with pytest.raises(StorageConflictError):
                second.transactions.delete('one', expected={'baseline': second_baseline['baseline']})
        else:
            alpha.journals.create(entry_id='one', txn_date='2026-10-05', postings=journal_lines())
            first_baseline, second_baseline = alpha.journals.get('one'), second.journals.get('one')
            alpha.journals.update('one', expected=first_baseline, description='Committed first')
            with pytest.raises(StorageConflictError) as failure:
                second.journals.update('one', expected=second_baseline, description='Stale after commit')
            assert failure.value.code == 'stale'
            with pytest.raises(StorageConflictError):
                second.journals.delete('one', expected={'baseline': second_baseline['baseline']})
    finally:
        second_database.dispose()


def test_concurrent_entry_updates_serialize_and_only_one_loaded_baseline_wins(database):
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='one', **expense())
    second_database = Database(DatabaseSettings(database.engine.url))
    barrier = Barrier(2)
    try:
        second = create_postgres_services(second_database, 'alpha')

        def update(service, description):
            loaded = service.transactions.list()[0]
            barrier.wait(timeout=5)
            try:
                service.transactions.update('one', expected=loaded, description=description)
                return 'committed'
            except StorageConflictError:
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(update, service, label) for service, label in [(alpha, 'first'), (second, 'second')]]
            assert sorted(future.result(timeout=10) for future in results) == ['committed', 'conflict']
        assert alpha.transactions.list()[0]['description'] in {'first', 'second'}
    finally:
        second_database.dispose()


def test_receipt_metadata_link_unlink_and_delete_preserve_document(database):
    alpha, beta = seed_core(database)
    with database.transaction() as connection:
        connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
            VALUES ('alpha','document','document','synthetic.pdf','synthetic','opaque-key')"""))
    reference = {'id': 'opaque-key', 'name': 'synthetic.pdf'}
    linked = alpha.transactions.create(transaction_id='linked', **expense(receipt_references=[reference]))
    assert linked['receipt_references'] == [reference]
    with pytest.raises(StorageValidationError):
        beta.transactions.create(transaction_id='foreign', **expense(receipt_references=[reference]))
    alpha.transactions.update('linked', expected=linked, receipt_references=[])
    alpha.transactions.delete('linked')
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM documents WHERE entity_id='alpha'")) == 1
        assert connection.scalar(text('SELECT count(*) FROM document_links')) == 0


def test_direct_journal_repository_rechecks_balance(database):
    seed_core(database)
    bad = journal_lines()
    bad[1]['amount'] = '5'
    with pytest.raises(StorageValidationError):
        PostgresJournalRepository(database, 'alpha').create(entry_id='one', txn_date='2026-10-05', description='', postings=bad)


def test_receipt_reordering_preserves_links_isolation_and_rolls_back_failed_replacement(database):
    alpha, beta = seed_core(database)
    references = [{'id': f'opaque-key-{identity}', 'name': f'{identity}.pdf'} for identity in ('a', 'b', 'c', 'd')]
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            for identity in ('a', 'b', 'c', 'd'):
                connection.execute(text('''INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
                    VALUES (:scope,:id,:id,:name,'synthetic',:key)'''),
                    {'scope': scope, 'id': identity, 'name': f'{identity}.pdf', 'key': f'opaque-key-{identity}'})
    original = alpha.transactions.create(transaction_id='linked', **expense(receipt_references=references[:2]))
    beta_original = beta.transactions.create(transaction_id='linked', **expense(receipt_references=references[:2]))
    with database.transaction(read_only=True) as connection:
        original_instants = dict(connection.execute(text(
            "SELECT document_id,created_at FROM document_links WHERE entity_id='alpha' AND entry_id='linked'"
        )).all())
    changed = alpha.transactions.update('linked', expected=original, receipt_references=[references[1], references[0]])
    assert changed['receipt_references'] == [references[1], references[0]]
    assert alpha.transactions.list()[0]['baseline'] == changed['baseline'] != original['baseline']
    changed = alpha.transactions.update('linked', expected=changed, receipt_references=[references[2], references[1], references[0]])
    assert changed['receipt_references'] == [references[2], references[1], references[0]]
    with database.transaction(read_only=True) as connection:
        retained = dict(connection.execute(text(
            "SELECT document_id,created_at FROM document_links WHERE entity_id='alpha' AND document_id IN ('a','b')"
        )).all())
        assert retained == original_instants
    with pytest.raises(StorageValidationError):
        alpha.transactions.update('linked', expected=changed, description='Must roll back',
                                  receipt_references=[references[0], references[0]])
    alpha.transactions.create(transaction_id='other', **expense(receipt_references=[references[3]]))
    # The first new link conflicts after retained links move to temporary positions.
    with pytest.raises(StorageConflictError) as failure:
        alpha.transactions.update('linked', expected=changed, description='Must roll back',
                                  receipt_references=[references[3], references[0], references[1]])
    assert failure.value.code == 'duplicate'
    assert next(row for row in alpha.transactions.list() if row['id'] == 'linked') == changed
    assert beta.transactions.list()[0] == beta_original
    with database.transaction(read_only=True) as connection:
        assert connection.execute(text(
            "SELECT document_id,position FROM document_links WHERE entity_id='alpha' AND entry_id='linked' ORDER BY position"
        )).all() == [('c', 1), ('b', 2), ('a', 3)]
        assert connection.scalar(text('SELECT count(*) FROM documents')) == 8


def test_owned_and_recurring_provenance_is_read_and_preserved_but_generic_ownership_changes_fail(database):
    alpha, _ = seed_core(database)
    ordinary = alpha.transactions.create(transaction_id='ordinary', **expense())
    with database.transaction() as connection:
        connection.execute(text("""INSERT INTO recurring_schedules(entity_id,id,incarnation_id,name,source_kind,recurrence_unit,
            recurrence_interval,anchor_date,start_date,status,amount,account_id,category_id)
            VALUES ('alpha','schedule','schedule','Synthetic','transaction','month',1,'2026-10-05','2026-10-05','active',12.50,'cash','office')"""))
        connection.execute(text("""INSERT INTO recurring_occurrences(entity_id,schedule_id,scheduled_date,source_kind,occurrence_type,entry_id)
            VALUES ('alpha','schedule','2026-10-05','transaction','initial','ordinary')"""))
        connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,business_use_percentage,
            allocated_amount,account_id,category_id,allocation_rationale,expected_projection_entry_id)
            VALUES ('alpha','mixed','mixed','2026-10-05',25,50,12.50,'cash','office','Synthetic','projection')"""))
        connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,simple_kind,mixed_use_source_id,description)
            VALUES ('alpha','projection','projection','2026-10-05','simple','Expense','mixed','Allocation rationale: Synthetic')"""))
        connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
            VALUES ('alpha','projection:1','projection','simple',1,'Debit',12.50,NULL,'office'),
            ('alpha','projection:2','projection','simple',2,'Credit',12.50,'cash',NULL)"""))
    loaded = {row['id']: row for row in alpha.transactions.list()}
    assert loaded['projection']['source_type'] == 'mixed_use_expense'
    assert loaded['projection']['source_id'] == 'mixed'
    assert loaded['ordinary']['recurring_schedule_id'] == 'schedule'
    assert loaded['ordinary']['recurring_occurrence_type'] == 'initial'
    with pytest.raises(StorageValidationError):
        alpha.transactions.update('ordinary', expected=loaded['ordinary'], recurring_schedule_id='other')
    with pytest.raises(StorageValidationError):
        alpha.transactions.update('projection', expected=loaded['projection'], description='Forbidden')
    with pytest.raises(StorageValidationError):
        alpha.transactions.delete('projection', expected=loaded['projection'])
    with pytest.raises(StorageValidationError):
        alpha.transactions.bulk_delete(['projection'], expected=[loaded['projection']])
    updated = alpha.transactions.update('ordinary', expected=loaded['ordinary'], description='Editable occurrence')
    assert updated['recurring_schedule_id'] == 'schedule'
    alpha.transactions.delete('ordinary', expected=updated)
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM recurring_occurrences')) == 0
    assert ordinary['id'] == 'ordinary'


def test_direct_update_callbacks_cannot_change_identity_or_provenance(database):
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='one', **expense())
    repository = PostgresTransactionRepository(database, 'alpha')
    for changes in ({'id': 'different'}, {'source_type': 'mixed_use_expense', 'source_id': 'new'},
                    {'recurring_schedule_id': 'new', 'recurring_source_kind': 'transaction',
                     'recurring_occurrence_type': 'initial', 'recurring_scheduled_date': '2026-10-05'}):
        with pytest.raises(StorageValidationError):
            repository.update('one', build=lambda refs, current: {**current, **changes})


def test_journal_empty_baseline_is_not_a_legacy_unguarded_mutation(database):
    alpha, _ = seed_core(database)
    alpha.journals.create(entry_id='one', txn_date='2026-10-05', postings=journal_lines())
    for expected in (None, {}, {'description': ''}):
        with pytest.raises((StorageValidationError, StorageConflictError)):
            alpha.journals.update('one', expected=expected, description='Forbidden')
        with pytest.raises((StorageValidationError, StorageConflictError)):
            alpha.journals.delete('one', expected=expected)


def test_journal_token_and_complete_normalized_snapshot_use_current_aggregate_version(database):
    alpha, _ = seed_core(database)
    loaded = alpha.journals.create(entry_id='one', txn_date='2026-10-05', postings=journal_lines())
    assert alpha.journals.get('one')['baseline'] == loaded['baseline']
    snapshot = {key: value for key, value in loaded.items() if key != 'baseline'}
    snapshot['postings'] = list(reversed(snapshot['postings']))
    for line in snapshot['postings']:
        line['amount'] = Decimal(line['amount'])
        line['position'] = str(line['position'])
    updated = alpha.journals.update('one', expected=snapshot, description='Legacy full snapshot')
    assert alpha.journals.get('one')['baseline'] == updated['baseline']
    changed = alpha.journals.update('one', expected={'baseline': updated['baseline']}, description='Token guard')
    with pytest.raises(StorageConflictError) as failure:
        alpha.journals.delete('one', expected={'baseline': loaded['baseline']})
    assert failure.value.code == 'stale'
    alpha.journals.delete('one', expected={'baseline': changed['baseline']})
