from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import nas_recurring_monitor as monitor


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = {'authority': 'worker', 'time_zone': 'America/New_York'}
DEFINITION = {'job_type': 'recurring.dispatch', 'paused': False, 'interval_seconds': 3600}


@pytest.mark.parametrize('mounted', [False, True])
def test_script_reaches_cli_from_repository_or_root_mount(monkeypatch, capsys, mounted):
    source_path = Path(monitor.__file__)
    script_path = Path(source_path.anchor) / 'monitor.py' if mounted else source_path
    monkeypatch.setattr(sys, 'argv', [str(script_path), '--help'])
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    namespace = {'__file__': str(script_path), '__name__': '__main__'}
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(source_path.read_text(encoding='utf-8'), str(script_path), 'exec'), namespace)
    assert exit_info.value.code == 0
    assert '--notify' in capsys.readouterr().out


def observations(**changes):
    return {'dead': 0, 'running': 0, 'oldest_queued': None, 'oldest_lease': None,
            'last_dispatch': NOW - timedelta(minutes=10), **changes}


def assess(**changes):
    return monitor.assess_entity('alpha', POLICY, DEFINITION, observations(**changes),
                                 expected_zone='America/New_York', now=NOW)


def test_recent_dispatch_is_insufficient_when_a_retained_job_is_dead():
    assert assess()['healthy']
    assert assess(dead=1)['codes'] == ['dead_jobs']


def test_old_pending_work_and_missing_dispatch_require_attention():
    result = assess(oldest_queued=NOW - timedelta(hours=2), last_dispatch=None)
    assert result['codes'] == ['dispatcher_missing_or_stale', 'queued_jobs_overdue']
    assert assess(oldest_queued=NOW - timedelta(minutes=1))['healthy']


def test_expired_execution_requires_attention_but_current_lease_does_not():
    assert assess(running=1, oldest_lease=NOW + timedelta(minutes=1))['healthy']
    assert assess(running=1, oldest_lease=NOW - timedelta(hours=2))['codes'] == ['running_jobs_unconfirmed']


@pytest.mark.parametrize('age,healthy', [(120, True), (150, True), (151, False)])
def test_two_hour_worker_freshness_applies_to_dispatch_queue_and_leases(age, healthy):
    timestamp = NOW - timedelta(minutes=age)
    result = monitor.assess_entity('alpha', POLICY, DEFINITION,
        observations(last_dispatch=timestamp, oldest_queued=timestamp,
                     running=1, oldest_lease=timestamp),
        expected_zone='America/New_York', now=NOW, max_age=timedelta(minutes=150))
    assert result['healthy'] is healthy
    assert result['codes'] == ([] if healthy else [
        'dispatcher_missing_or_stale', 'queued_jobs_overdue', 'running_jobs_unconfirmed'])


def test_unenabled_authority_or_dispatcher_never_reports_healthy():
    result = monitor.assess_entity('alpha', {'authority': 'explicit', 'time_zone': 'UTC'}, None,
        observations(), expected_zone='America/New_York', now=NOW)
    assert not result['healthy']
    assert set(result['codes']) == {'worker_not_enabled', 'business_zone_mismatch', 'dispatcher_not_enabled'}


@pytest.mark.parametrize('max_age', [None, 150])
def test_inspection_is_read_only_scoped_and_does_not_hide_another_entity_failure(monkeypatch, max_age):
    database = MagicMock()
    connection = database.transaction.return_value.__enter__.return_value
    connection.scalar.return_value = 'restricted_worker'
    monkeypatch.setattr(monitor, 'database_identity', lambda db: 'a' * 64)
    monkeypatch.setattr(monitor, 'policy', lambda db, scope: POLICY)
    alpha = observations() if max_age is None else observations(last_dispatch=NOW - timedelta(hours=2))
    beta = observations(dead=1) if max_age is None else observations(last_dispatch=NOW - timedelta(minutes=151))
    rows = [DEFINITION, alpha, DEFINITION, beta]
    def execute(statement, parameters):
        row = rows.pop(0)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row, one=lambda: row))
    connection.execute.side_effect = execute
    config = {'database_sha256': 'a' * 64, 'database_role': 'restricted_worker',
        'entity_ids': ['alpha', 'beta'], 'business_time_zone': 'America/New_York'}
    if max_age is not None:
        config['max_age_minutes'] = max_age
    result = monitor.inspect(database, config, now=NOW)
    assert result['status'] == 'unhealthy'
    assert [row['healthy'] for row in result['entities']] == [True, False]
    assert result['entities'][1]['codes'] == (['dead_jobs'] if max_age is None else ['dispatcher_missing_or_stale'])
    assert [call.args[1]['scope'] for call in connection.execute.call_args_list] == ['alpha', 'alpha', 'beta', 'beta']
    assert all(call.kwargs == {'read_only': True} for call in database.transaction.call_args_list)
    aggregate_sql = str(connection.execute.call_args_list[1].args[0])
    assert 'LIMIT' not in aggregate_sql and 'entity_id=:scope' in aggregate_sql


@pytest.mark.parametrize('role,identity', [('wrong_role', 'a' * 64), ('restricted_worker', 'b' * 64)])
def test_wrong_role_or_target_stops_before_entity_reads(monkeypatch, role, identity):
    database = MagicMock()
    database.transaction.return_value.__enter__.return_value.scalar.return_value = role
    monkeypatch.setattr(monitor, 'database_identity', lambda db: identity)
    read_policy = MagicMock()
    monkeypatch.setattr(monitor, 'policy', read_policy)
    with pytest.raises(ValueError):
        monitor.inspect(database, {'database_sha256': 'a' * 64, 'database_role': 'restricted_worker'})
    read_policy.assert_not_called()


@pytest.mark.parametrize('healthy,suffix', [(True, ''), (False, '/fail')])
def test_signal_uses_only_approved_url_and_no_diagnostic_payload(healthy, suffix):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.status = 200
    url = 'https://incidents.betterstack.com/api/v1/heartbeat/synthetic-token'
    monitor.signal(url, healthy, opener=opener)
    request = opener.open.call_args.args[0]
    assert request.full_url == url + suffix
    assert request.data is None and request.method == 'GET'
    assert opener.open.call_args.kwargs == {'timeout': 10}


@pytest.mark.parametrize('url', ['http://incidents.betterstack.com/api/v1/heartbeat/synthetic-token',
    'https://other.example/api/v1/heartbeat/synthetic-token',
    'https://incidents.betterstack.com/api/v1/heartbeat/synthetic-token?private=data'])
def test_unapproved_notification_destination_is_never_contacted(url):
    opener = MagicMock()
    with pytest.raises(ValueError):
        monitor.signal(url, True, opener=opener)
    opener.open.assert_not_called()


def test_redirects_are_refused():
    with pytest.raises(monitor.URLError):
        monitor.NoRedirects().redirect_request(None, None, 302, '', {}, 'https://other.example')


def test_failed_read_and_worker_exit_cannot_produce_success_signal(monkeypatch, capsys):
    monkeypatch.setattr(monitor, 'load_config', lambda path: {})
    monkeypatch.setattr(monitor, 'Database', MagicMock(side_effect=RuntimeError('private database URL')))
    monkeypatch.setattr(monitor.DatabaseSettings, 'from_environment', lambda **kwargs: None)
    send = MagicMock()
    monkeypatch.setattr(monitor, 'signal', send)
    assert monitor.main(['--config', 'synthetic', '--notify', '--worker-exit-code', '1']) == 1
    assert send.call_args.args[1] is False
    output = capsys.readouterr().out
    assert 'private database URL' not in output
    assert json.loads(output)['codes'] == ['inspection_unconfirmed', 'worker_command_failed']


def test_notify_is_opt_in_and_delivery_failure_is_not_reported_as_success(monkeypatch, capsys):
    monkeypatch.setattr(monitor, 'load_config', lambda path: {})
    monkeypatch.setattr(monitor, 'Database', MagicMock())
    monkeypatch.setattr(monitor.DatabaseSettings, 'from_environment', lambda **kwargs: None)
    monkeypatch.setattr(monitor, 'inspect', lambda *args: {'status': 'healthy'})
    send = MagicMock(side_effect=RuntimeError('private heartbeat URL'))
    monkeypatch.setattr(monitor, 'signal', send)
    assert monitor.main(['--config', 'synthetic']) == 0
    send.assert_not_called()
    assert monitor.main(['--config', 'synthetic', '--notify']) == 1
    output = capsys.readouterr().out
    assert 'private heartbeat URL' not in output
    assert json.loads(output.splitlines()[-1])['signal'] == 'unconfirmed'


def test_runner_failure_overrides_healthy_database_observations(monkeypatch, capsys):
    monkeypatch.setattr(monitor, 'load_config', lambda path: {})
    monkeypatch.setattr(monitor, 'Database', MagicMock())
    monkeypatch.setattr(monitor.DatabaseSettings, 'from_environment', lambda **kwargs: None)
    monkeypatch.setattr(monitor, 'inspect', lambda *args: {'status': 'healthy'})
    send = MagicMock()
    monkeypatch.setattr(monitor, 'signal', send)
    assert monitor.main(['--config', 'synthetic', '--notify', '--worker-exit-code', '1']) == 1
    assert send.call_args.args[1] is False
    assert json.loads(capsys.readouterr().out)['codes'] == ['worker_command_failed']


def test_binding_configuration_requires_distinct_explicit_entities_and_no_credentials(tmp_path):
    config = {'database_sha256': 'a' * 64, 'database_role': 'restricted_worker',
        'entity_ids': ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'],
        'business_time_zone': 'America/New_York'}
    path = tmp_path / 'monitor.json'
    path.write_text(json.dumps(config))
    assert monitor.load_config(path) == config
    path.write_text(json.dumps({**config, 'max_age_minutes': 150}))
    assert monitor.load_config(path)['max_age_minutes'] == 150
    for changed in ({**config, 'entity_ids': [config['entity_ids'][0]] * 2},
                    {**config, 'database_url': 'private-synthetic-value'},
                    {**config, 'entity_ids': []}):
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            monitor.load_config(path)


@pytest.mark.parametrize('max_age', [True, False, '150', 150.0, None, 0, -1, 1441])
def test_invalid_freshness_configuration_is_refused(tmp_path, max_age):
    config = {'database_sha256': 'a' * 64, 'database_role': 'restricted_worker',
        'entity_ids': ['00000000-0000-4000-8000-000000000001'],
        'business_time_zone': 'America/New_York', 'max_age_minutes': max_age}
    path = tmp_path / 'monitor.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        monitor.load_config(path)
