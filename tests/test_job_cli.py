"""Operator activation guards and sanitized diagnostics, without a live target."""

from unittest.mock import Mock
import json

import pytest

from tabula_rasa.infrastructure.postgres import job_cli


def test_mutation_and_budget_guards_run_before_opening_any_database(monkeypatch):
    database = Mock()
    monkeypatch.setattr(job_cli, 'Database', database)
    for args in (['tick'], ['retry', '--id', 'job'], ['define-probe', '--id', 'definition']):
        with pytest.raises(SystemExit):
            job_cli.main([*args, '--entity', 'alpha', '--service-id', 'test'])
    with pytest.raises(SystemExit):
        job_cli.main(['tick', '--entity', 'alpha', '--service-id', 'test', '--allow-mutations', '--budget', '0'])
    database.assert_not_called()


def test_cli_provider_failures_are_sanitized_and_close_resources(monkeypatch, capsys):
    database = Mock()
    monkeypatch.setattr(job_cli.DatabaseSettings, 'from_environment', lambda **kwargs: object())
    monkeypatch.setattr(job_cli, 'Database', lambda settings: database)
    queue = Mock()
    queue.diagnostics.side_effect = RuntimeError('private credentials and ledger values')
    monkeypatch.setattr(job_cli, 'JobQueue', lambda *args, **kwargs: queue)
    assert job_cli.main(['inspect', '--entity', 'alpha', '--service-id', 'test']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['error'] == 'job_operation_unconfirmed'
    assert 'private' not in str(result)
    database.dispose.assert_called_once()


def test_tick_composes_and_closes_shared_telemetry(monkeypatch, capsys):
    database, telemetry, queue = Mock(), Mock(), Mock()
    queue.tick.return_value = True
    monkeypatch.setattr(job_cli, 'configure_console', lambda: None)
    monkeypatch.setattr(job_cli.TelemetrySettings, 'from_environment', lambda: object())
    factory = Mock(return_value=telemetry)
    monkeypatch.setattr(job_cli, 'Telemetry', factory)
    monkeypatch.setattr(job_cli.DatabaseSettings, 'from_environment', lambda **kwargs: object())
    monkeypatch.setattr(job_cli, 'Database', lambda settings: database)
    queue_factory = Mock(return_value=queue)
    monkeypatch.setattr(job_cli, 'JobQueue', queue_factory)
    monkeypatch.setenv('TABULA_RASA_ENVIRONMENT', 'staging')
    monkeypatch.setenv('TABULA_RASA_RELEASE_ID', 'release')
    assert job_cli.main(['tick', '--entity', 'alpha', '--service-id', 'worker', '--allow-mutations']) == 0
    assert json.loads(capsys.readouterr().out) == {'executed': 1}
    assert factory.call_args.args[:2] == ('staging', 'release')
    assert queue_factory.call_args.kwargs['telemetry'] is telemetry
    telemetry.close.assert_called_once()
    database.dispose.assert_called_once()
