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
