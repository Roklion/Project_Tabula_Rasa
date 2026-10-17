"""Native period boundaries, corrections, authorization and close/write races."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageError
from tabula_rasa.infrastructure.postgres.audit import AuditContext, audit_context
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.periods import PostgresPeriodRepository
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.postgres.core_support import seed_core, expense, journal_lines
from tests.postgres.secondary_support import asset, mixed, schedule
from tests.postgres.test_audit import reader
from tests.postgres.test_import_repository import csv, qb


@contextmanager
def operator(database, scope='alpha'):
    with audit_context(database, AuditContext('operator', 'synthetic-operator', 'accounting-control', scope)):
        yield


def close(database, services, month='2026-10-01'):
    with operator(database, services.profile_key):
        PostgresPeriodRepository(database, services.profile_key).configure(enabled=True, reason='Adopt control')
        return services.periods.change(month, closed=True, reason='Close month', expected_version=0)


def test_activation_is_opt_in_repeated_actions_are_audited_once_and_entities_are_isolated(database):
    alpha, beta = seed_core(database)
    assert alpha.periods.list() == {'enabled': False, 'items': []}
    original = alpha.transactions.create(transaction_id='before', **expense())
    period = close(database, alpha)
    assert period['version'] == 1
    with operator(database):
        assert alpha.periods.change('2026-10-01', closed=True, reason='Close month', expected_version=0) == period
        with pytest.raises(StorageConflictError, match='changed'):
            alpha.periods.change('2026-10-01', closed=False, reason='Inspect correction', expected_version=0)
    for mutation in (
        lambda: alpha.transactions.create(transaction_id='backdated', **expense()),
        lambda: alpha.transactions.update(original['id'], expected=original, txn_date='2026-11-01'),
        lambda: alpha.transactions.delete(original['id'], expected=original),
        lambda: alpha.journals.create(entry_id='closed-journal', txn_date='2026-10-10', postings=journal_lines()),
    ):
        with pytest.raises(StorageConflictError) as failed:
            mutation()
        assert failed.value.code == 'period_closed'
    alpha.transactions.create(transaction_id='open', **expense(txn_date='2026-11-01'))
    beta.transactions.create(transaction_id='backdated', **expense())
    assert beta.periods.list() == {'enabled': False, 'items': []}
    assert len(reader(database).query(target_type='accounting_periods')) == 1
    with operator(database):
        unlocked = alpha.periods.change('2026-10-01', closed=False, reason='Inspect correction', expected_version=1)
        assert unlocked['version'] == 2
    alpha.transactions.update(original['id'], expected=original, amount='15')
    with reader(database).operation() as connection:
        actions = list(connection.execute(text('''SELECT control_action,reason FROM accounting_period_actions
            WHERE entity_id='alpha' ORDER BY created_at,id''')).all())
        assert actions == [('enable', 'Adopt control'), ('close', 'Close month'), ('unlock', 'Inspect correction')]
    for statement in ('DELETE FROM accounting_period_actions', "UPDATE accounting_period_actions SET reason='overwrite'",
                      'TRUNCATE accounting_period_actions'):
        from tabula_rasa.infrastructure.postgres.runtime import DatabaseError
        with pytest.raises(DatabaseError), database.transaction() as connection:
            connection.execute(text(statement))
    assert reader(database).verify()['mismatches'] == 0


@pytest.mark.parametrize('path', ['mixed', 'recurring', 'depreciation', 'csv', 'quickbooks'])
def test_all_secondary_financial_mutations_observe_one_period_boundary(database, path):
    alpha, beta = seed_core(database)
    if path == 'depreciation':
        offset = alpha.accounts.create('Depreciation offset', 'Other', classification='Asset')['id']
        alpha.assets.create(asset_id='asset', **asset(offset))
    if path == 'recurring':
        alpha.recurring.create(schedule_id='schedule', **schedule())
    close(database, alpha, '2026-01-01' if path in {'depreciation', 'recurring'} else '2026-10-01')
    if path == 'recurring':
        result = alpha.recurring.reconcile(as_of='2026-02-01')
        assert result['generated'] == [] and result['attention'] == {'schedule': 'storage'}
    else:
        actions = {
            'mixed': lambda: alpha.mixed_use.create(source_id='mixed', linked_transaction_id='projection',
                                                  **mixed(txn_date='2026-10-05')),
            'depreciation': lambda: alpha.assets.post_due('asset', '2026-03-31'),
            'csv': lambda: alpha.imports.import_csv([csv()]),
            'quickbooks': lambda: alpha.imports.import_quickbooks([qb()]),
        }
        with pytest.raises(StorageConflictError) as failed:
            actions[path]()
        assert failed.value.code == 'period_closed'
    assert alpha.transactions.list() == [] and alpha.mixed_use.sources() == []
    assert reader(database).query(target_type='entries') == ()
    assert beta.transactions.list() == []
    with database.transaction(read_only=True) as connection:
        for table in ('postings', 'recurring_occurrences', 'depreciation_events', 'import_batches', 'import_records'):
            assert connection.scalar(text(f"SELECT count(*) FROM {table} WHERE entity_id='alpha'")) == 0


@pytest.mark.parametrize('projection', ['simple', 'journal'])
def test_reversal_preserves_closed_original_links_history_and_replay_has_no_extra_events(database, projection):
    alpha, _ = seed_core(database)
    original = (alpha.transactions.create(transaction_id='original', **expense()) if projection == 'simple' else
                alpha.journals.create(entry_id='original', txn_date='2026-10-05', postings=journal_lines()))
    close(database, alpha)
    request = dict(correction_id='correction', reversal_entry_id='reversal', txn_date='2026-11-01',
                   reason='Explicit correction reason', expected=original)
    with operator(database):
        first = alpha.periods.reverse('original', **request)
        count = len(reader(database).query())
        assert alpha.periods.reverse('original', **request) == first
        assert len(reader(database).query()) == count
        with pytest.raises(StorageConflictError):
            alpha.periods.reverse('original', **{**request, 'txn_date': '2026-11-02'})
    reversal = first['journal']
    assert [p['side'] for p in reversal['postings']] == ['Credit', 'Debit']
    assert reversal['total_debits'] == reversal['total_credits'] == '12.50'
    with operator(database):
        alpha.periods.change('2026-10-01', closed=False, reason='Inspect', expected_version=1)
        PostgresPeriodRepository(database, 'alpha').configure(enabled=False, reason='Rollback adoption')
    with pytest.raises(StorageConflictError):
        alpha.journals.update('reversal', expected=reversal, description='Silent rewrite')
    with pytest.raises(StorageConflictError):
        (alpha.transactions if projection == 'simple' else alpha.journals).delete('original', expected=original)
    correction, = reader(database).query(target_type='entry_corrections')
    assert correction['after_summary']['original_entry_id'] == 'original'
    assert correction['after_summary']['reversal_entry_id'] == 'reversal'
    assert correction['actor_type'] == 'operator' and 'Explicit correction reason' not in str(correction)
    assert reader(database).verify()['mismatches'] == 0


def test_closed_reversal_stale_original_and_audit_failure_roll_back_correction(database, monkeypatch):
    alpha, _ = seed_core(database)
    original = alpha.transactions.create(transaction_id='original', **expense())
    close(database, alpha)
    args = dict(correction_id='correction', reversal_entry_id='reversal', txn_date='2026-10-20',
                reason='Correction', expected=original)
    with operator(database):
        with pytest.raises(StorageConflictError) as failed:
            alpha.periods.reverse('original', **args)
        assert failed.value.code == 'period_closed'
    assert alpha.journals.list() == [] and reader(database).query(target_type='entry_corrections') == ()
    # An audit trigger failure at commit must undo both the new journal and relation.
    with database.engine.begin() as connection:
        connection.exec_driver_sql('''CREATE FUNCTION fail_correction_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.target_type='entry_corrections' THEN RAISE EXCEPTION 'synthetic failure'; END IF; RETURN NEW; END $$''')
        connection.exec_driver_sql('CREATE TRIGGER fail_correction BEFORE INSERT ON audit_events FOR EACH ROW EXECUTE FUNCTION fail_correction_audit()')
    with operator(database), pytest.raises(StorageError):
        alpha.periods.reverse('original', **{**args, 'txn_date': '2026-11-01'})
    assert alpha.journals.list() == [] and reader(database).query(target_type='entry_corrections') == ()


@pytest.mark.parametrize('winner', ['close', 'write'])
def test_close_write_race_serializes_at_the_persisted_boundary(database, winner):
    alpha, _ = seed_core(database)
    with operator(database):
        PostgresPeriodRepository(database, 'alpha').configure(enabled=True, reason='Adopt')
    other = Database(DatabaseSettings(database.engine.url))
    held, release = Event(), Event()

    def first():
        with operator(database), database.transaction():
            if winner == 'close':
                alpha.periods.change('2026-10-01', closed=True, reason='Close month', expected_version=0)
            else:
                alpha.transactions.create(transaction_id='first', **expense())
            held.set()
            assert release.wait(10)

    def second():
        with operator(other):
            services = create_postgres_services(other, 'alpha')
            if winner == 'write':
                return services.periods.change('2026-10-01', closed=True, reason='Close month', expected_version=0)
            with pytest.raises(StorageConflictError) as failed:
                services.transactions.create(transaction_id='late', **expense())
            assert failed.value.code == 'period_closed'

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_run = pool.submit(first)
            assert held.wait(10)
            second_run = pool.submit(second)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline:
                with database.transaction(read_only=True) as connection:
                    blocked = connection.scalar(text('''SELECT EXISTS (SELECT 1 FROM pg_locks
                        WHERE locktype='advisory' AND NOT granted AND database=(
                            SELECT oid FROM pg_database WHERE datname=current_database()))'''))
                if blocked:
                    break
                sleep(0.01)
            assert blocked  # Prove the competing operation is actually waiting.
            release.set()
            first_run.result(timeout=10)
            second_run.result(timeout=10)
        assert len(alpha.transactions.list()) == (1 if winner == 'write' else 0)
        assert alpha.periods.list()['items'][0]['closed']
    finally:
        release.set()
        other.dispose()


def test_membership_and_cross_entity_denial_precede_binding_and_are_rechecked_in_sql(database):
    from tests.postgres.test_authorization_http import named_client
    from tabula_rasa.application.identity import IdentityError

    with named_client(database) as (client, _, repo, ids, factory, _, headers):
        alice, bob, org_a, _ = ids
        with operator(database):
            PostgresPeriodRepository(database, 'alpha').configure(enabled=True, reason='Adopt')
        body = {'period_start': '2026-10-01', 'reason': 'Close month', 'expected_version': 0}
        path = '/api/v1/entities/alpha/accounting-periods'
        assert client.post(path + '/close', json=body, headers=headers).status_code == 200
        assert client.get(path).json()['items'][0]['closed'] is True
        repo.set_membership(org_a, bob.id, 'owner')
        for role in ('admin', 'accountant', 'editor', 'read_only'):
            repo.set_membership(org_a, alice.id, role)
            factory.reset_mock()
            assert client.post(path + '/unlock', json={**body, 'expected_version': 1}, headers=headers).status_code == 403
            factory.assert_not_called()
            if role in {'editor', 'read_only', 'accountant'}:
                assert client.post(path + '/close', json=body, headers=headers).status_code == 403
            with audit_context(database, AuditContext('user', alice.id, 'test', 'alpha')), pytest.raises(IdentityError):
                create_postgres_services(database, 'alpha').periods.change('2026-10-01', closed=False,
                    reason='Forged unlock', expected_version=1)
        factory.reset_mock()
        assert client.post(path.replace('/alpha/', '/beta/') + '/close', json=body, headers=headers).status_code == 403
        factory.assert_not_called()


def test_named_api_correction_and_period_conflicts_are_safe_and_attributed(database):
    from tests.postgres.test_authorization_http import named_client
    from tests.postgres._support import account, category

    with named_client(database) as (client, _, _, ids, _, _, headers):
        with database.transaction() as connection:
            account(connection, 'alpha', 'cash')
            category(connection, 'alpha', 'office', kind='Expense')
        root = '/api/v1/entities/alpha'
        original = client.post(root + '/transactions', headers=headers,
                               json={'transaction_id': 'original', **expense()})
        assert original.status_code == 201, original.text
        saved = original.json()
        with operator(database):
            PostgresPeriodRepository(database, 'alpha').configure(enabled=True, reason='Adopt')
        assert client.post(root + '/accounting-periods/close', headers=headers,
                           json={'period_start': '2026-10-01', 'reason': 'Close', 'expected_version': 0}).status_code == 200
        blocked = client.post(root + '/transactions', headers=headers, json={'transaction_id': 'blocked', **expense()})
        assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'period_closed'
        correction = client.post(root + '/entries/' + saved['id'] + '/reverse', headers=headers, json={
            'correction_id': 'correction', 'reversal_entry_id': 'reversal', 'txn_date': '2026-11-01',
            'reason': 'Private correction explanation', 'baseline': saved['baseline'],
        })
        assert correction.status_code == 200, correction.text
        assert correction.json()['journal']['txn_date'] == '2026-11-01'
        event, = reader(database).query(target_type='entry_corrections')
        assert event['actor_type'] == 'user' and event['actor_id'] == ids[0].id
        assert 'Private correction explanation' not in str(event) + blocked.text


def test_stale_correction_and_source_owned_reversal_are_denied(database):
    alpha, _ = seed_core(database)
    original = alpha.transactions.create(transaction_id='original', **expense())
    alpha.transactions.update('original', expected=original, amount='20')
    source = alpha.mixed_use.create(source_id='mixed', linked_transaction_id='projection', **mixed())
    args = dict(correction_id='correction', reversal_entry_id='reversal', txn_date='2026-11-01', reason='Correct')
    with operator(database):
        with pytest.raises(StorageConflictError) as failed:
            alpha.periods.reverse('original', expected=original, **args)
        assert failed.value.code == 'stale'
        projection = next(row for row in alpha.transactions.list() if row['id'] == source['linked_transaction_id'])
        with pytest.raises(StorageError, match='source workflow'):
            alpha.periods.reverse(projection['id'], expected=projection, **args)
    assert alpha.journals.list() == []


def test_opening_balances_and_source_updates_cannot_change_closed_history(database):
    alpha, beta = seed_core(database)
    source = alpha.mixed_use.create(source_id='mixed', linked_transaction_id='projection', **mixed())
    close(database, alpha, '2026-01-01')
    for change in (
        lambda: alpha.mixed_use.update('mixed', expected_source=source, total_expense='200'),
        lambda: alpha.mixed_use.delete('mixed', expected_source=source),
        lambda: alpha.accounts.create('Backdated opening', 'Bank', opening_balance='10'),
        lambda: alpha.accounts.update('cash', opening_balance='10'),
    ):
        with pytest.raises(StorageConflictError) as failed:
            change()
        assert failed.value.code == 'period_closed'
    beta.accounts.create('Opening', 'Bank', opening_balance='10')
    with operator(database):
        PostgresPeriodRepository(database, 'alpha').configure(enabled=False, reason='Rollback')
        with pytest.raises(StorageConflictError, match='disabled'):
            alpha.periods.change('2026-01-01', closed=True, reason='Close month', expected_version=1)
    alpha.mixed_use.update('mixed', expected_source=source, total_expense='200')


def test_forward_controls_migration_retains_data_without_adopting_policies(empty_database):
    from alembic import command
    from tabula_rasa.infrastructure.postgres.migrations import migration_config, upgrade

    with empty_database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0012_operations')
    alpha, _ = seed_core(empty_database)
    original = alpha.transactions.create(transaction_id='retained', **expense())
    events = reader(empty_database).query(target_type='entries')
    upgrade(empty_database)
    assert alpha.transactions.list() == [original]
    assert alpha.periods.list() == {'enabled': False, 'items': []}
    from tabula_rasa.infrastructure.postgres.recurring_jobs import policy
    assert policy(empty_database, 'alpha')['authority'] == 'explicit'
    assert reader(empty_database).query(target_type='entries') == events
    assert reader(empty_database).verify()['mismatches'] == 0
