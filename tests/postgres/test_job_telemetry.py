"""Real durable outcomes, post-commit visibility and tenant-safe diagnostics."""

import json
from unittest.mock import Mock

from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.telemetry import Telemetry, TelemetrySettings
from tests.postgres.core_support import seed_core
from tests.postgres.test_jobs import queue, due, expire


def test_success_is_emitted_after_commit_once_with_scoped_pseudonyms(database):
    seed_core(database)
    observer = Database(DatabaseSettings(database.engine.url))
    sink = Telemetry('test', 'release', TelemetrySettings(scope_key='k' * 32))
    records = []

    def record(*args, **kwargs):
        state = queue(observer, kwargs['context'].entity_id).diagnostics()[0]['state']
        assert state == 'succeeded'
        records.append(sink.record(*args, **kwargs))

    try:
        telemetry = Mock(record=record)
        for scope in ('alpha', 'beta'):
            worker = queue(database, scope, telemetry=telemetry)
            identity = worker.enqueue('test.post', 'same-private-key')
            claim = worker.claim()
            assert worker.execute(*claim) is True
            assert worker.execute(*claim) is False
            assert identity not in json.dumps(records)
        assert len(records) == 2
        assert {r['outcome'] for r in records} == {'success'}
        assert records[0]['entity_ref'] != records[1]['entity_ref']
        assert records[0]['job_ref'] != records[1]['job_ref']
        assert all(r['event'] == 'job_run' and r['operation'] == 'job_execute' for r in records)
        assert 'same-private-key' not in json.dumps(records)
    finally:
        observer.dispose()
        sink.close()


def test_retry_and_obsolete_claim_do_not_emit_terminal_failure(database):
    seed_core(database)
    telemetry = Mock()

    def unavailable(*args):
        raise DatabaseError('unavailable')

    worker = queue(database, handler=unavailable, telemetry=telemetry)
    identity = worker.enqueue('test.post', 'retry', max_attempts=2)
    claim = worker.claim()
    assert worker.execute(*claim) is False
    telemetry.record.assert_not_called()
    assert worker.execute(*claim) is False
    telemetry.record.assert_not_called()
    due(database, identity)
    assert worker.tick() is False
    telemetry.record.assert_called_once()
    assert telemetry.record.call_args.kwargs['failure_code'] == 'job_transient'
    assert worker.diagnostics()[0]['state'] == 'dead'


def test_poison_and_expired_attempt_budget_emit_only_confirmed_terminal_failure(database):
    seed_core(database)
    telemetry = Mock()

    def poison(*args):
        raise ValueError('private token and ledger contents')

    worker = queue(database, handler=poison, telemetry=telemetry)
    worker.enqueue('test.post', 'poison')
    assert worker.tick() is False
    assert telemetry.record.call_args.kwargs['failure_code'] == 'job_poison'
    identity = worker.enqueue('test.post', 'expired', max_attempts=1)
    worker.claim()
    expire(database, identity)
    assert worker.claim() is None
    assert telemetry.record.call_count == 2
    assert telemetry.record.call_args.kwargs['failure_code'] == 'job_lease_expired'
    assert 'private token' not in str(telemetry.record.call_args_list)


def test_broken_telemetry_cannot_repeat_committed_job(database):
    seed_core(database)
    worker = queue(database, telemetry=Mock(record=Mock(side_effect=RuntimeError('sink unavailable'))))
    worker.enqueue('test.post', 'one')
    claim = worker.claim()
    assert worker.execute(*claim) is True
    assert worker.execute(*claim) is False
    assert worker.diagnostics()[0]['state'] == 'succeeded'
