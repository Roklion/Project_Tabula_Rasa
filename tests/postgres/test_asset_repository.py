"""Native asset lifecycle, immutable history, posting rollback and competing writers."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import Barrier

import pytest
from sqlalchemy import text

from tabula_rasa.depreciation_posting import depreciation_entry_id
from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.postgres.core_support import seed_core, expense, journal_lines
from tests.postgres.secondary_support import asset


def offsets(alpha, beta):
    return [service.accounts.create('Accumulated depreciation', 'Other', classification='Asset')['id'] for service in (alpha, beta)]


def test_asset_crud_terms_overrides_retirement_and_entity_isolation(database):
    alpha, beta = seed_core(database)
    first_offset, second_offset = offsets(alpha, beta)
    payee = alpha.payees.create('Vendor')
    tag = alpha.tags.create('Equipment')
    acquisition = alpha.transactions.create(transaction_id='acquisition', **expense())
    created = alpha.assets.create(asset_id='asset', **asset(first_offset, payee_id=payee['id'], tag_ids=[tag['id']],
                                                          source_transaction_id=acquisition['id']))
    beta_created = beta.assets.create(asset_id='asset', **asset(second_offset))
    assert created['tags'] == ['Equipment'] and created['payee'] == 'Vendor'
    assert created['source_transaction_id'] == 'acquisition'
    changed = alpha.assets.update('asset', expected=created, notes='Synthetic note')
    assert changed['created_at'] == created['created_at'] and changed['baseline'] != created['baseline']
    with pytest.raises(StorageConflictError):
        alpha.assets.delete('asset', expected=created)
    saved = alpha.assets.override('asset', 1, '10', 'Historical correction', as_of_date=date(2026, 12, 31), expected=changed)
    assert alpha.assets.schedule(saved)[0].depreciation_amount == 10
    with pytest.raises(StorageConflictError):
        alpha.assets.update('asset', expected=saved, cost_basis='200')
    removed = alpha.assets.remove_override('asset', 1, expected=saved)
    assert removed['schedule_overrides'] == '{}'
    retired = alpha.assets.retire('asset', '2026-12-31', expected=removed)
    assert retired['status'] == 'retired'
    alpha.assets.delete('asset', expected=retired)
    assert alpha.assets.list() == [] and beta.assets.list() == [beta_created]


def test_straight_line_posting_canonical_history_repetition_and_zero_period(database):
    alpha, beta = seed_core(database)
    first_offset, second_offset = offsets(alpha, beta)
    first = alpha.assets.create(asset_id='asset', **asset(first_offset))
    beta.assets.create(asset_id='asset', **asset(second_offset))
    posted = alpha.assets.post_due('asset', '2026-06-30', expected=first)
    assert [(row['id'], row['txn_date'], row['amount']) for row in posted] == [
        (depreciation_entry_id('asset', 1), '2026-01-01', '25.00'),
        (depreciation_entry_id('asset', 2), '2026-04-01', '25.00')]
    assert alpha.assets.post_due('asset', '2026-06-30') == []
    assert alpha.journals.list() == [] and len(alpha.transactions.list()) == 2
    assert beta.transactions.list() == []
    with database.transaction(read_only=True) as connection:
        events = connection.execute(text("SELECT sequence,entry_id,amount FROM depreciation_events WHERE entity_id='alpha' ORDER BY sequence")).all()
        assert [(row.sequence, row.entry_id, str(row.amount)) for row in events] == [(1, posted[0]['id'], '25.00'), (2, posted[1]['id'], '25.00')]
        lines = connection.execute(text("SELECT position,side,amount,category_id,account_id FROM postings WHERE entity_id='alpha' AND entry_id=:id ORDER BY position"), {'id': posted[0]['id']}).all()
        assert [(row.position, row.side, str(row.amount), row.category_id, row.account_id) for row in lines] == [
            (1, 'Debit', '25.00', 'office', None), (2, 'Credit', '25.00', None, first_offset)]
    with pytest.raises(StorageConflictError):
        alpha.assets.update('asset', expected=first, notes='Stale')
    for action in (lambda: alpha.assets.update('asset', cost_basis='200'),
                   lambda: alpha.assets.override('asset', 3, '0', 'No', as_of_date=date(2027, 1, 1)),
                   lambda: alpha.assets.retire('asset', '2026-03-31'),
                   lambda: alpha.assets.delete('asset'),
                   lambda: alpha.transactions.delete(posted[0]['id'])):
        with pytest.raises(StorageError):
            action()
    alpha.assets.update('asset', notes='Description may change')
    alpha.assets.create(asset_id='zero', **asset(first_offset))
    alpha.assets.override('zero', 1, '0', 'No use this quarter', as_of_date=date(2026, 12, 31))
    zero = alpha.assets.post_due('zero', '2026-03-31')
    assert len(zero) == 1 and zero[0]['amount'] == '0.00'
    assert alpha.assets.post_due('zero', '2026-03-31') == []
    assert len(beta.assets.post_due('asset', '2026-03-31')) == 1


def test_late_sql_failure_rolls_back_all_events_postings_and_asset_baseline(database, monkeypatch):
    alpha, beta = seed_core(database)
    first_offset, _ = offsets(alpha, beta)
    created = alpha.assets.create(asset_id='asset', **asset(first_offset))
    original = PostgresTransactionRepository.write_lines

    def fail(self, connection, identity, lines):
        original(self, connection, identity, lines)
        if identity == depreciation_entry_id('asset', 2):
            connection.execute(text('UPDATE postings SET amount=amount+1 WHERE entity_id=:scope AND entry_id=:id AND position=2'),
                               {'scope': self.entity_id, 'id': identity})
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    with pytest.raises(StorageValidationError):
        alpha.assets.post_due('asset', '2026-06-30', expected=created)
    assert alpha.transactions.list() == [] and alpha.assets.list() == [created]
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM depreciation_events')) == 0
        assert connection.scalar(text('SELECT count(*) FROM postings')) == 0
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', original)
    assert len(alpha.assets.post_due('asset', '2026-06-30', expected=created)) == 2


def test_reference_types_cross_entity_references_and_readonly_history(database):
    alpha, beta = seed_core(database)
    offset, foreign_offset = offsets(alpha, beta)
    wrong_offset = alpha.accounts.create('Wrong offset', 'Bank')['id']
    for fields in ({'accumulated_depreciation_account_id': foreign_offset},
                   {'accumulated_depreciation_account_id': wrong_offset}, {'depreciation_expense_account_id': 'sales'},
                   {'source_transaction_id': 'foreign'}):
        with pytest.raises(StorageError):
            alpha.assets.create(asset_id='asset', **{**asset(offset), **fields})
    alpha.journals.create(entry_id='journal', txn_date='2026-01-01', postings=journal_lines())
    with pytest.raises(StorageError):
        alpha.assets.create(asset_id='asset', **asset(offset, source_transaction_id='journal'))
    created = alpha.assets.create(asset_id='asset', **asset(offset))
    alpha.accounts.deactivate(offset)
    with pytest.raises(StorageValidationError):
        alpha.assets.post_due('asset', '2026-03-31')
    assert alpha.assets.list() == [created] and alpha.transactions.list() == []


@pytest.mark.parametrize('action', ['edit', 'post'])
def test_independent_loaded_callers_and_overlapping_writers(database, action):
    alpha, beta = seed_core(database)
    offset, _ = offsets(alpha, beta)
    alpha.assets.create(asset_id='asset', **asset(offset))
    others = [Database(DatabaseSettings(database.engine.url)) for _ in range(2)]
    try:
        clients = [create_postgres_services(db, 'alpha') for db in others]
        loaded = [deepcopy(client.assets.list()[0]) for client in clients]
        barrier = Barrier(2)

        def write(index):
            barrier.wait(timeout=10)
            try:
                if action == 'edit':
                    clients[index].assets.update('asset', expected=loaded[index], notes=f'Synthetic {index}')
                else:
                    clients[index].assets.post_due('asset', '2026-03-31', expected=loaded[index])
                return 'committed'
            except StorageConflictError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [0, 1]))
        assert sorted(results) == ['committed', 'stale']
        assert len(alpha.transactions.list()) == (1 if action == 'post' else 0)
        with pytest.raises(StorageConflictError):
            clients[1 if results[0] == 'committed' else 0].assets.delete('asset', expected=loaded[0])
    finally:
        for db in others:
            db.dispose()


def test_asset_mutation_and_posting_share_outer_commit_and_rollback(database, monkeypatch):
    from tabula_rasa.infrastructure.postgres.operations import repository_operation

    alpha, beta = seed_core(database)
    offset, _ = offsets(alpha, beta)
    original_asset = alpha.assets.create(asset_id='asset', **asset(offset))
    write = PostgresTransactionRepository.write_lines

    def fail(self, connection, identity, lines):
        write(self, connection, identity, lines)
        connection.execute(text('SELECT 1/0'))
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    with pytest.raises(StorageError):
        with repository_operation(database):
            changed = alpha.assets.update('asset', expected=original_asset, notes='Rolled back')
            alpha.assets.post_due('asset', '2026-01-01', expected=changed)
    assert alpha.assets.list() == [original_asset] and alpha.transactions.list() == []
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', write)
    with repository_operation(database):
        changed = alpha.assets.update('asset', expected=original_asset, notes='Committed')
        posted = alpha.assets.post_due('asset', '2026-01-01', expected=changed)
    assert len(posted) == 1 and alpha.assets.list()[0]['notes'] == 'Committed'
    assert beta.assets.list() == []


def test_asset_post_reads_only_its_history_and_preserves_period_collision_checks(database, monkeypatch):
    alpha, beta = seed_core(database)
    first_offset, _ = offsets(alpha, beta)
    alpha.assets.create(asset_id='asset', **asset(first_offset))
    for index in range(12):
        alpha.transactions.create(transaction_id=f'unrelated-{index}', **expense())
    project = PostgresTransactionRepository.project

    def assert_relevant(self, connection, row):
        assert not row['id'].startswith('unrelated-')
        return project(self, connection, row)
    monkeypatch.setattr(PostgresTransactionRepository, 'project', assert_relevant)
    assert len(alpha.assets.post_due('asset', '2026-01-01')) == 1
    assert alpha.assets.post_due('asset', '2026-01-01') == []
    monkeypatch.setattr(PostgresTransactionRepository, 'project', project)
    alpha.transactions.create(transaction_id=depreciation_entry_id('asset', 2), **expense())
    with pytest.raises(StorageConflictError, match='already in use'):
        alpha.assets.post_due('asset', '2026-04-01')
    assert len([row for row in alpha.transactions.list() if row['source_type'] == 'depreciation']) == 1
