"""Two native workers, durable crash/replay recovery and atomic service effects."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import event, text

from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.jobs import JobError, JobQueue, JobRegistry
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError
from tests.postgres.core_support import seed_core, expense
from tests.postgres.test_audit import reader


def queue(database, scope='alpha', *, handler=None, service='test-worker', independent=False, telemetry=None):
    registry = JobRegistry()

    def create(database, execution):
        services = create_postgres_services(database, execution.entity_id)
        services.transactions.create(transaction_id='job-' + execution.job_id, **expense())

    registry.register('test.post', handler or create, independent_idempotent=independent)
    return JobQueue(database, scope, registry, service_id=service, telemetry=telemetry)


def expire(database, job_id):
    with database.transaction() as connection:
        connection.execute(text("UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"), {'id': job_id})


def due(database, job_id):
    with database.transaction() as connection:
        connection.execute(text("UPDATE jobs SET due_at=clock_timestamp()-interval '1 second' WHERE id=:id"), {'id': job_id})


def test_two_workers_claim_once_and_two_entities_never_share_effects(database):
    seed_core(database)
    other = Database(DatabaseSettings(database.engine.url))
    first, second = queue(database), queue(other, service='other-worker')
    beta = queue(other, 'beta')
    try:
        identity = first.enqueue('test.post', 'same')
        assert first.enqueue('test.post', 'same') == identity
        beta_id = beta.enqueue('test.post', 'same')
        assert beta_id != identity
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda q: q.claim(), [first, second]))
        assert sum(c is not None for c in claims) == 1
        claim = next(c for c in claims if c)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda q: q.execute(*claim), [first, second])) == [False, True]
        assert len(reader(database).query(target_type='entries', action='create')) == 1
        assert reader(database, 'beta').query(target_type='entries') == ()
        assert beta.execute(*claim) is False
        assert beta.tick() is True
        assert len(reader(database, 'beta').query(target_type='entries', action='create')) == 1
        assert first.diagnostics()[0]['state'] == 'succeeded'
        assert [r['outcome'] for r in first.attempts(identity)] == ['succeeded']
        event, = reader(database).query(target_type='entries', action='create')
        assert event['actor_type'] == 'worker' and event['actor_id'] in {'test-worker','other-worker'}
        assert event['operation_id'] == 'job:' + identity
        assert reader(database).verify()['mismatches'] == 0
    finally:
        other.dispose()


def test_crash_after_claim_restart_reclaims_and_old_lease_is_fenced(database):
    seed_core(database)
    old = queue(database)
    identity = old.enqueue('test.post', 'restart')
    abandoned = old.claim()
    assert abandoned and old.diagnostics()[0]['state'] == 'running'
    expire(database, identity)
    other = Database(DatabaseSettings(database.engine.url))
    try:
        restarted = queue(other, service='restarted-worker')
        replacement = restarted.claim()
        assert replacement and replacement != abandoned
        assert old.execute(*abandoned) is False
        assert restarted.execute(*replacement) is True
        assert restarted.execute(*replacement) is False
        assert [r['outcome'] for r in restarted.attempts(identity)] == ['lease_expired','succeeded']
        assert len(reader(database).query(target_type='entries', action='create')) == 1
    finally:
        other.dispose()


def test_running_transaction_lock_outlives_lease_and_prevents_reclaim(database):
    seed_core(database)
    started, finish = Event(), Event()

    def block(database, execution):
        started.set()
        assert finish.wait(5)
        create_postgres_services(database, execution.entity_id).transactions.create(transaction_id='one', **expense())

    first = queue(database, handler=block)
    identity = first.enqueue('test.post', 'long')
    claim = first.claim(lease_seconds=1)
    other = Database(DatabaseSettings(database.engine.url))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first.execute, *claim)
            assert started.wait(5)
            with other.transaction(read_only=True) as connection:
                connection.execute(text('SELECT pg_sleep(1.1)'))
                assert connection.scalar(text('SELECT lease_until<clock_timestamp() FROM jobs WHERE id=:id'), {'id': identity})
            # Row locking, rather than wall-clock heartbeat timing, is the fence.
            assert queue(other).claim() is None
            finish.set()
            assert future.result(timeout=5) is True
        assert first.diagnostics()[0]['state'] == 'succeeded'
        assert len(first.attempts(identity)) == 1
    finally:
        finish.set()
        other.dispose()


def test_poison_rolls_back_all_effects_and_does_not_block_healthy_jobs(database):
    seed_core(database)

    def poison(database, execution):
        create_postgres_services(database, execution.entity_id).transactions.create(transaction_id='rolled-back', **expense())
        raise RuntimeError('private draft and secret must not be retained')

    failing = queue(database, handler=poison)
    failed_id = failing.enqueue('test.post', 'poison')
    assert failing.tick() is False
    assert failing.diagnostics()[0]['state'] == 'dead'
    assert failing.diagnostics()[0]['failure_code'] == 'poison'
    assert reader(database).query(target_type='entries') == ()
    assert 'private draft' not in str(failing.diagnostics()) + str(failing.attempts(failed_id))
    healthy = queue(database)
    healthy.enqueue('test.post', 'healthy')
    assert healthy.tick() is True
    assert healthy.retry(failed_id) is True
    assert healthy.tick() is True
    assert len(reader(database).query(target_type='entries', action='create')) == 2


@pytest.mark.parametrize('failure_code', ['unavailable', 'concurrent_write', 'database_exhausted'])
def test_transient_failure_backoff_exhaustion_and_cancel_are_durable(database, failure_code):
    seed_core(database)

    def transient(database, execution):
        raise DatabaseError(failure_code)

    worker = queue(database, handler=transient)
    identity = worker.enqueue('test.post', 'transient', max_attempts=2)
    assert worker.tick() is False
    assert worker.claim() is None  # Backoff, no hot retry loop.
    due(database, identity)
    assert worker.tick() is False
    assert worker.diagnostics()[0]['state'] == 'dead'
    assert [a['outcome'] for a in worker.attempts(identity)] == ['transient','transient']
    assert worker.cancel(identity) is True and worker.claim() is None
    identity = worker.enqueue('test.post', 'cancel-claim')
    claim = worker.claim()
    assert worker.cancel(identity) is True
    assert worker.execute(*claim) is False
    assert worker.attempts(identity)[0]['outcome'] == 'cancelled'


def test_expired_final_attempt_enters_dead_state_without_effect(database):
    seed_core(database)
    worker = queue(database)
    identity = worker.enqueue('test.post', 'crash', max_attempts=1)
    worker.claim()
    expire(database, identity)
    assert worker.claim() is None
    assert worker.diagnostics()[0]['state'] == 'dead'
    assert worker.attempts(identity)[0]['outcome'] == 'lease_expired'
    assert reader(database).query(target_type='entries') == ()


def test_commit_response_loss_is_confirmed_once_and_not_reexecuted(database, monkeypatch):
    seed_core(database)
    telemetry = Mock()
    worker = queue(database, telemetry=telemetry)
    identity = worker.enqueue('test.post', 'lost-response')
    claim = worker.claim()
    transaction = database.transaction
    lost = False

    @contextmanager
    def lose_response(**kwargs):
        nonlocal lost
        outer = kwargs.get('require_outer') and not lost
        with transaction(**kwargs) as connection:
            yield connection
        if outer:
            lost = True
            raise DatabaseError('unavailable')

    monkeypatch.setattr(database, 'transaction', lose_response)
    assert worker.execute(*claim) is True
    assert worker.execute(*claim) is False
    assert worker.diagnostics()[0]['state'] == 'succeeded'
    assert len(worker.attempts(identity)) == 1
    assert len(reader(database).query(target_type='entries', action='create')) == 1
    telemetry.record.assert_called_once()
    assert telemetry.record.call_args.kwargs['failure_code'] is None


def test_schedule_catchup_pause_resume_and_concurrent_ticks(database):
    seed_core(database)
    first, second = queue(database), queue(database)
    first.define('hourly', 'test.post', interval_seconds=3600,
                 first_due=datetime.now(timezone.utc)-timedelta(days=7))
    first.pause('hourly')
    assert first.schedule_due() == 0
    first.pause('hourly', paused=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda q: q.schedule_due(), [first,second])) == [0,1]
    assert len(first.diagnostics()) == 1
    first.pause('hourly')
    assert first.claim() is None
    first.pause('hourly', paused=False)
    assert first.tick() is True
    assert first.tick() is False
    assert len(reader(database).query(target_type='entries', action='create')) == 1


def test_registry_unknown_types_and_identity_collisions_fail_closed(database):
    seed_core(database)
    worker = queue(database)
    with pytest.raises(JobError):
        worker.enqueue('unregistered', 'no')
    with pytest.raises(ValueError):
        JobQueue(database, 'alpha', worker.registry, service_id='')
    worker.enqueue('test.post', 'same')
    worker.registry.register('other', lambda db, execution: None)
    with pytest.raises(JobError):
        worker.enqueue('other', 'same')
    with database.transaction() as connection:
        connection.execute(text("UPDATE jobs SET job_type='removed-handler' WHERE entity_id='alpha'"))
    assert worker.tick() is False
    assert worker.diagnostics()[0]['failure_code'] == 'poison'


@pytest.mark.parametrize('independent', [False, True])
def test_worker_scope_cannot_mutate_a_different_entity(database, independent):
    seed_core(database)

    def foreign(database, execution):
        create_postgres_services(database, 'beta').transactions.create(transaction_id='foreign', **expense())

    worker = queue(database, handler=foreign, independent=independent)
    worker.enqueue('test.post', 'foreign')
    assert worker.tick() is False
    assert worker.diagnostics()[0]['state'] == 'dead'
    assert reader(database, 'beta').query(target_type='entries') == ()
    assert create_postgres_services(database, 'beta').transactions.list() == []


def test_connection_death_rolls_back_effects_before_safe_worker_retry(database):
    seed_core(database)

    def crash(database, execution):
        create_postgres_services(database, execution.entity_id).transactions.create(transaction_id='uncommitted', **expense())
        with database.transaction() as connection:
            connection.execute(text('SELECT pg_terminate_backend(pg_backend_pid())'))

    worker = queue(database, handler=crash)
    identity = worker.enqueue('test.post', 'connection-death')
    assert worker.tick() is False
    assert reader(database).query(target_type='entries') == ()
    assert worker.diagnostics()[0]['state'] == 'queued'
    due(database, identity)
    assert queue(database).tick() is True
    assert len(reader(database).query(target_type='entries')) == 1


def test_existing_recurring_service_can_commit_independent_idempotent_effects(database):
    from tests.postgres.secondary_support import schedule
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='monthly', **schedule())

    def reconcile(participant, execution):
        assert participant is not database
        return create_postgres_services(participant, execution.entity_id).recurring.reconcile(as_of='2026-02-01')

    def lose_after_effects(participant, execution):
        assert len(reconcile(participant, execution)['generated']) == 2
        raise DatabaseError('unavailable')

    worker = queue(database, handler=lose_after_effects, independent=True)
    identity = worker.enqueue('test.post', 'recurring-replay')
    assert worker.tick() is False
    assert worker.diagnostics()[0]['state'] == 'queued'
    events = reader(database).query(target_type='entries')
    assert len(events) == 2 and all(e['correlation_id'] == identity for e in events)
    assert all(e['actor_type'] == 'worker' for e in events)
    due(database, identity)
    assert queue(database, handler=reconcile, independent=True).tick() is True
    assert reader(database).query(target_type='entries') == events
    assert len(alpha.transactions.list()) == 2
    assert reader(database, 'beta').query(target_type='entries') == ()
    assert reader(database).verify()['mismatches'] == 0


def test_independent_participant_outlives_orchestration_idle_budget_without_losing_fence(database):
    seed_core(database)

    def participant_work(participant, execution):
        with participant.transaction(read_only=True) as connection:
            connection.execute(text('SELECT pg_sleep(0.25)'))
        create_postgres_services(participant, execution.entity_id).transactions.create(transaction_id='independent', **expense())

    worker = queue(database, handler=participant_work, independent=True)
    identity = worker.enqueue('test.post', 'idle-fence')
    claim = worker.claim()

    def shorten_idle_budget(connection, cursor, statement, parameters, context, many):
        # Reproduce the reported session death in 100 ms instead of 30 seconds.
        if statement == "SET LOCAL idle_in_transaction_session_timeout='30s'":
            statement = "SET LOCAL idle_in_transaction_session_timeout='100ms'"
        return statement, parameters

    event.listen(database.engine, 'before_cursor_execute', shorten_idle_budget, retval=True)
    try:
        assert worker.execute(*claim) is True
    finally:
        event.remove(database.engine, 'before_cursor_execute', shorten_idle_budget)
    assert worker.diagnostics()[0]['state'] == 'succeeded'
    assert worker.attempts(identity)[0]['outcome'] == 'succeeded'
    assert len(reader(database).query(target_type='entries')) == 1


@pytest.mark.parametrize('independent', [False, True])
def test_statement_timeout_rolls_back_and_stable_retry_can_recover(database, independent):
    seed_core(database)

    def blocked(participant, execution):
        with participant.transaction() as connection:
            assert connection.scalar(text('SHOW statement_timeout')) == '30s'
            create_postgres_services(participant, execution.entity_id).transactions.create(
                transaction_id='job-' + execution.job_id, **expense())
            connection.execute(text("SET LOCAL statement_timeout='20ms'"))
            connection.execute(text('SELECT pg_sleep(0.1)'))

    failing = queue(database, handler=blocked, independent=independent)
    identity = failing.enqueue('test.post', 'timeout')
    assert failing.execute(*failing.claim()) is False
    assert failing.diagnostics()[0]['state'] == 'queued'
    assert failing.attempts(identity)[0]['outcome'] == 'transient'
    assert reader(database).query(target_type='entries') == ()
    due(database, identity)
    healthy = queue(database, independent=independent)
    assert healthy.execute(*healthy.claim())
    assert len(reader(database).query(target_type='entries')) == 1
