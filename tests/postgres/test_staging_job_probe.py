import pytest
from sqlalchemy import text

from tabula_rasa.deployment.staging_job_probe import PROBE_DUE_AT, inspect_queue
from tabula_rasa.infrastructure.postgres.job_cli import operator_registry
from tabula_rasa.infrastructure.postgres.jobs import JobQueue
from tests.postgres.core_support import seed_core


def test_probe_reads_ledger_and_retains_one_durable_success(database):
    seed_core(database)
    queue = JobQueue(database, 'alpha', operator_registry(), service_id='synthetic-probe')
    assert inspect_queue(database, 'alpha', 'probe-1') is None
    job = queue.enqueue('ledger.probe', 'probe-1', max_attempts=1)
    assert inspect_queue(database, 'alpha', 'probe-1')['state'] == 'queued'
    assert queue.execute(*queue.claim()) is True
    assert inspect_queue(database, 'alpha', 'probe-1')['state'] == 'succeeded'
    assert queue.enqueue('ledger.probe', 'probe-1', max_attempts=1) == job
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM entries')) == 0
        assert connection.scalar(text('SELECT count(*) FROM job_attempts')) == 1
        assert connection.scalar(text("SELECT count(*) FROM jobs WHERE entity_id='beta'")) == 0


@pytest.mark.parametrize('other', ['queued', 'running', 'definition'])
def test_existing_work_blocks_probe_without_executing_it(database, other):
    seed_core(database)
    queue = JobQueue(database, 'alpha', operator_registry(), service_id='synthetic-probe')
    if other == 'definition':
        from datetime import datetime, timezone
        queue.define('existing', 'ledger.probe', interval_seconds=3600, first_due=datetime.now(timezone.utc))
    else:
        queue.enqueue('ledger.probe', 'other')
        if other == 'running':
            queue.claim()
    with pytest.raises(ValueError):
        inspect_queue(database, 'alpha', 'probe-1')
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM entries')) == 0
        assert connection.scalar(text("SELECT count(*) FROM jobs WHERE idempotency_key='probe-1'")) == 0


def test_completed_other_tenant_does_not_block_selected_fixture(database):
    seed_core(database)
    other = JobQueue(database, 'beta', operator_registry(), service_id='synthetic-probe')
    other.enqueue('ledger.probe', 'other')
    assert inspect_queue(database, 'alpha', 'probe-1') is None


def test_nonexistent_probe_entity_is_not_reported_as_inspected(database):
    seed_core(database)
    with pytest.raises(ValueError, match='entity does not exist'):
        inspect_queue(database, 'c' * 32, 'probe-1')
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM jobs')) == 0
        assert connection.scalar(text('SELECT count(*) FROM job_attempts')) == 0
    assert inspect_queue(database, 'alpha', 'probe-1') is None
    assert inspect_queue(database, 'beta', 'probe-1') is None


def test_probe_is_immediately_claimable_when_runner_clock_is_ahead(database, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from tabula_rasa.infrastructure.postgres import jobs

    class AheadClock:
        @staticmethod
        def now(tz):
            return datetime.now(timezone.utc) + timedelta(hours=1)

    seed_core(database)
    monkeypatch.setattr(jobs, 'datetime', AheadClock)
    queue = JobQueue(database, 'alpha', operator_registry(), service_id='synthetic-probe')
    job = queue.enqueue('ledger.probe', 'probe-1', max_attempts=1, due_at=PROBE_DUE_AT)
    claim = queue.claim()
    assert str(claim[0]) == job
    assert queue.execute(*claim) is True
    assert inspect_queue(database, 'alpha', 'probe-1')['state'] == 'succeeded'
