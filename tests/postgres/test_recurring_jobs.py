"""Real workers reuse recurring semantics, catch up and fence authority changes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier

import pytest
from sqlalchemy import text

from tabula_rasa.application.transactions import TransactionService
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.jobs import JobQueue
from tabula_rasa.infrastructure.postgres.recurring_jobs import (
    business_today, enqueue_reconciliation, policy, recurring_registry, set_authority,
)
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.recurrence import occurrence_id
from tests.postgres.core_support import seed_core
from tests.postgres.secondary_support import schedule, mixed
from tests.postgres.test_audit import reader
from tests.postgres.test_jobs import expire, due
from tests.postgres.test_periods import operator, close


def worker(database, scope='alpha'):
    return JobQueue(database, scope, recurring_registry(), service_id='synthetic-recurring-worker')


def activate(database, scope='alpha'):
    with operator(database, scope):
        set_authority(database, scope, 'worker', 'America/New_York')


def run_one(queue):
    claim = queue.claim()
    assert claim
    return queue.execute(*claim)


@pytest.mark.parametrize('instant,expected', [
    ('2026-03-08T04:59:00+00:00', '2026-03-07'),
    ('2026-03-08T07:01:00+00:00', '2026-03-08'),
    ('2026-11-01T05:30:00+00:00', '2026-11-01'),
    ('2026-11-01T06:30:00+00:00', '2026-11-01'),
])
def test_business_date_is_calendar_based_across_both_dst_transitions(instant, expected):
    assert business_today('America/New_York', instant=datetime.fromisoformat(instant)).isoformat() == expected


def test_two_workers_repeated_explicit_requests_and_entity_scopes_share_one_queue(database):
    alpha, beta = seed_core(database)
    for service in (alpha, beta):
        service.recurring.create(schedule_id='same', **schedule(amount='99' if service is beta else '12.50'))
    activate(database)
    activate(database, 'beta')
    ids = enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    assert len(ids) == 1
    assert enqueue_reconciliation(database, 'alpha', through_date='2026-02-01') == ids
    assert alpha.recurring.reconcile(as_of='2026-02-01')['queued_count'] == 1
    beta_ids = enqueue_reconciliation(database, 'beta', through_date='2026-02-01')
    assert beta_ids != ids
    other = Database(DatabaseSettings(database.engine.url))
    try:
        first, second = worker(database), worker(other)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda q: q.claim(), [first, second]))
        assert sum(c is not None for c in claims) == 1
        claim = next(c for c in claims if c)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda q: q.execute(*claim), [first, second])) == [False, True]
        assert len(alpha.transactions.list()) == 2 and beta.transactions.list() == []
        assert enqueue_reconciliation(database, 'alpha', through_date='2026-02-01') == []
        assert run_one(worker(other, 'beta')) is True
        assert {r['amount'] for r in beta.transactions.list()} == {'99.00'}
        events = reader(database).query(target_type='entries')
        assert all(e['actor_type'] == 'worker' and e['source'] == 'recurring.worker' for e in events)
        assert reader(database).verify()['mismatches'] == 0
    finally:
        other.dispose()


@pytest.mark.parametrize('change', ['edit', 'pause', 'end', 'delete'])
def test_schedule_changes_after_enqueue_are_read_fresh_before_effects(database, change):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='schedule', **schedule())
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    if change == 'delete':
        with database.transaction() as connection:
            connection.execute(text("DELETE FROM recurring_schedules WHERE entity_id='alpha' AND id='schedule'"))
    elif change == 'edit':
        alpha.recurring.update('schedule', amount='25')
    else:
        getattr(alpha.recurring, change)('schedule')
    assert run_one(worker(database)) is True
    assert len(alpha.transactions.list()) == (2 if change == 'edit' else 0)
    if change == 'edit':
        assert {r['amount'] for r in alpha.transactions.list()} == {'25.00'}


def test_sql_failure_isolated_per_schedule_and_operator_retry_preserves_committed_occurrences(database, monkeypatch):
    alpha, _ = seed_core(database)
    for identity in ('broken', 'healthy'):
        alpha.recurring.create(schedule_id=identity, **schedule())
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    original = PostgresTransactionRepository.write_lines
    failed = occurrence_id('broken', date(2026, 2, 1), 'generated')

    def fail(self, connection, identity, lines):
        original(self, connection, identity, lines)
        if identity == failed:
            connection.execute(text('SELECT 1/0'))

    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    queue = worker(database)
    assert sorted([run_one(queue), run_one(queue)]) == [False, True]
    assert len(alpha.transactions.list()) == 3
    retrying, = [r for r in queue.diagnostics() if r['state'] == 'queued']
    for _ in range(2):
        due(database, retrying['id'])
        assert run_one(queue) is False
    dead, = [r for r in queue.diagnostics() if r['state'] == 'dead']
    assert dead['target_id'] == 'broken' and alpha.recurring.get('broken')['attention_code'] == 'storage'
    assert len(reader(database).query(target_type='entries')) == 3
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', original)
    assert queue.retry(str(dead['id']))
    assert run_one(queue)
    assert len(alpha.transactions.list()) == 4 and alpha.recurring.get('broken')['attention_code'] == ''
    assert [r['outcome'] for r in queue.attempts(dead['id'])] == ['transient', 'transient', 'transient', 'succeeded']


def test_restart_missed_runs_and_bounded_catchup_need_no_application_page(database):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='daily', **schedule(recurrence_unit='day'))
    activate(database)
    ids = enqueue_reconciliation(database, 'alpha', through_date='2026-04-15')
    abandoned = worker(database).claim()
    expire(database, ids[0])
    queue = worker(database)
    replacement = queue.claim()
    assert replacement != abandoned and queue.execute(*abandoned) is False
    assert queue.execute(*replacement) is True
    assert len(alpha.transactions.list()) == 100
    continuation = enqueue_reconciliation(database, 'alpha', through_date='2026-04-15')
    assert continuation and continuation != ids
    assert run_one(queue)
    assert len(alpha.transactions.list()) == 105
    assert enqueue_reconciliation(database, 'alpha', through_date='2026-04-15') == []
    assert [r['outcome'] for r in queue.attempts(ids[0])] == ['lease_expired', 'succeeded']


def test_persisted_timer_materializes_and_executes_without_page_open(database):
    alpha, _ = seed_core(database)
    today = business_today('America/New_York').isoformat()
    alpha.recurring.create(schedule_id='monthly', **schedule(txn_date=today))
    activate(database)
    queue = worker(database)
    assert queue.tick()  # Dispatcher creates schedule jobs.
    assert queue.tick()  # Worker runs the schedule through its business date.
    assert len(alpha.transactions.list()) == 1
    assert len(queue.diagnostics()) == 2


def test_rollback_during_generation_fences_worker_and_explicit_mode_can_resume(database, monkeypatch):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='monthly', **schedule())
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    original = TransactionService.create_occurrence
    control = Database(DatabaseSettings(database.engine.url))

    def rollback(self, **values):
        with operator(control):
            set_authority(control, 'alpha', 'explicit', 'America/New_York')
        return original(self, **values)

    monkeypatch.setattr(TransactionService, 'create_occurrence', rollback)
    try:
        assert run_one(worker(database)) is False
    finally:
        control.dispose()
    assert alpha.transactions.list() == [] and policy(database, 'alpha')['authority'] == 'explicit'
    monkeypatch.setattr(TransactionService, 'create_occurrence', original)
    assert len(alpha.recurring.reconcile(as_of='2026-02-01')['generated']) == 2


def test_mixed_use_workers_and_closed_period_attention_preserve_atomic_pairs(database):
    alpha, _ = seed_core(database)
    alpha.recurring.create_mixed_expense(schedule_id='mixed', **{**schedule(), **mixed()})
    close(database, alpha, '2026-02-01')
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    assert run_one(worker(database)) is False
    assert len(alpha.transactions.list()) == len(alpha.mixed_use.sources()) == 1
    assert alpha.recurring.get('mixed')['attention_code'] == 'storage'
    assert reader(database).verify()['mismatches'] == 0


def test_resume_after_queued_noop_and_new_timezone_revision_do_not_lose_due_work(database):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='schedule', **schedule())
    activate(database)
    first = enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    alpha.recurring.pause('schedule')
    assert run_one(worker(database))
    assert alpha.transactions.list() == []
    alpha.recurring.resume('schedule')
    resumed = enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    assert resumed and resumed != first
    with operator(database):
        set_authority(database, 'alpha', 'worker', 'UTC')
    assert run_one(worker(database))  # Obsolete zone/revision job is a no-op.
    assert alpha.transactions.list() == []
    current = enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    assert current and current != resumed
    assert run_one(worker(database))
    assert len(alpha.transactions.list()) == 2


def test_timezone_switch_during_run_fences_the_old_business_cutoff(database, monkeypatch):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='schedule', **schedule())
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    original = TransactionService.create_occurrence
    control = Database(DatabaseSettings(database.engine.url))

    def change_zone(self, **values):
        with operator(control):
            set_authority(control, 'alpha', 'worker', 'UTC')
        return original(self, **values)

    monkeypatch.setattr(TransactionService, 'create_occurrence', change_zone)
    try:
        assert run_one(worker(database)) is False
    finally:
        control.dispose()
    assert alpha.transactions.list() == []


def test_operator_cli_is_explicit_entity_bound_and_reports_counts_only(database, monkeypatch, capsys):
    from tabula_rasa.infrastructure.postgres import job_cli
    alpha, beta = seed_core(database)
    alpha.recurring.create(schedule_id='schedule', **schedule())
    monkeypatch.setattr(job_cli.DatabaseSettings, 'from_environment', lambda **kwargs: DatabaseSettings(database.engine.url))
    common = ['--entity', 'alpha', '--service-id', 'synthetic-operator', '--allow-mutations']
    assert job_cli.main(['recurring-enable', *common, '--time-zone', 'America/New_York']) == 0
    assert job_cli.main(['enqueue-recurring', *common]) == 0
    assert job_cli.main(['period-enable', *common, '--reason', 'Synthetic adoption']) == 0
    assert alpha.periods.list()['enabled'] is True and beta.periods.list()['enabled'] is False
    assert policy(database, 'beta')['authority'] == 'explicit'
    assert job_cli.main(['recurring-disable', *common, '--time-zone', 'America/New_York']) == 0
    output = capsys.readouterr().out
    assert 'queued_count' in output and '12.50' not in output and 'Synthetic adoption' not in output


def test_authorized_http_command_queues_same_jobs_and_page_reads_do_not_dispatch(database):
    from tests.postgres.test_authorization_http import named_client
    from tests.postgres._support import account, category
    from tabula_rasa.infrastructure.postgres.composition import create_postgres_services

    with named_client(database) as (client, _, _, _, _, _, headers):
        with database.transaction() as connection:
            account(connection, 'alpha', 'cash')
            category(connection, 'alpha', 'office', kind='Expense')
        services = create_postgres_services(database, 'alpha')
        services.recurring.create(schedule_id='schedule', **schedule())
        activate(database)
        root = '/api/v1/entities/alpha'
        for path in ('/recurring', '/recurring/schedule', '/transactions'):
            assert client.get(root + path).status_code == 200
        assert worker(database).diagnostics() == ()
        result = client.post(root + '/recurring/reconcile', headers=headers, json={'through_date': '2026-02-01'})
        assert result.status_code == 200 and result.json() == {
            'generated_count': 0, 'attention_count': 0, 'queued_count': 1, 'execution_mode': 'worker',
        }
        assert services.transactions.list() == []
        assert len(enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')) == 1
        assert len(worker(database).diagnostics()) == 1
        assert run_one(worker(database))
        assert len(services.transactions.list()) == 2
        future = client.post(root + '/recurring/reconcile', headers=headers, json={'through_date': '9999-01-01'})
        assert future.status_code == 422 and future.json()['error']['code'] == 'validation'


def test_distinct_overlapping_cutoff_jobs_reuse_occurrence_and_audit_identities(database, monkeypatch):
    from tabula_rasa.infrastructure.postgres.recurring import PostgresRecurringRepository
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='schedule', **schedule())
    activate(database)
    enqueue_reconciliation(database, 'alpha', through_date='2026-02-01')
    enqueue_reconciliation(database, 'alpha', through_date='2026-03-01')
    barrier = Barrier(2)
    snapshot = PostgresRecurringRepository.snapshot

    def simultaneous(self, **options):
        result = snapshot(self, **options)
        if self.database._audit_context.get().actor_type == 'worker':
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(PostgresRecurringRepository, 'snapshot', simultaneous)
    other = Database(DatabaseSettings(database.engine.url))
    try:
        queues = [worker(database), worker(other)]
        claims = [q.claim() for q in queues]
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda pair: pair[0].execute(*pair[1]), zip(queues, claims)))
        assert outcomes == [True, True]
        assert len(alpha.transactions.list()) == 3
        assert len(reader(database).query(target_type='entries', action='create')) == 3
        assert reader(database).verify()['mismatches'] == 0
    finally:
        other.dispose()
