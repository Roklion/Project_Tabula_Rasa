"""Operator-private provenance and fail-closed CLI scope/error output."""

import json
from types import SimpleNamespace

import pytest

from tabula_rasa.deployment import tenancy_reconciliation as cli


def test_prepare_retains_private_plan_and_prints_only_hash(monkeypatch, tmp_path, capsys):
    path = tmp_path / 'private.json'
    database = SimpleNamespace(dispose=lambda: None)
    plan = {'private_original_receipt': 'synthetic-private-identity'}
    monkeypatch.setenv('TABULA_RASA_ENVIRONMENT', 'staging')
    monkeypatch.setattr(cli, 'open_alpha_database', lambda _: database)
    monkeypatch.setattr(cli, 'prepare', lambda *_, **__: plan)
    monkeypatch.setattr('sys.argv', ['maintenance', 'prepare', '--plan', str(path)])
    cli.main()
    output = capsys.readouterr().out
    assert json.loads(path.read_text()) == plan
    assert json.loads(output)['status'] == 'plan_prepared'
    assert 'synthetic-private-identity' not in output
    with pytest.raises(SystemExit, match='maintenance stopped'):
        cli.main()
    assert json.loads(path.read_text()) == plan


@pytest.mark.parametrize('environment', ['production', 'development', 'test', ''])
def test_other_environments_never_open_database(monkeypatch, tmp_path, environment):
    monkeypatch.setenv('TABULA_RASA_ENVIRONMENT', environment)
    def forbidden(_):
        pytest.fail('Database must not be opened for this environment.')
    monkeypatch.setattr(cli, 'open_alpha_database', forbidden)
    monkeypatch.setattr('sys.argv', ['maintenance', 'prepare', '--plan', str(tmp_path / 'plan')])
    with pytest.raises(SystemExit, match='maintenance stopped'):
        cli.main()


@pytest.mark.parametrize('operation', ['apply', 'readback'])
def test_errors_do_not_expose_private_plan_or_provider_details(monkeypatch, tmp_path, capsys, operation):
    disposed = []
    database = SimpleNamespace(dispose=lambda: disposed.append(True))
    path = tmp_path / 'private.json'
    path.write_text('{"original_receipt":"private synthetic reference"}')
    monkeypatch.setenv('TABULA_RASA_ENVIRONMENT', 'staging')
    monkeypatch.setattr(cli, 'open_alpha_database', lambda _: database)
    def fail(*_, **__):
        raise ValueError('private synthetic reference / provider details')
    monkeypatch.setattr(cli, operation, fail)
    monkeypatch.setattr('sys.argv', ['maintenance', operation, '--plan', str(path), '--approval-sha256', 'a' * 64])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert 'private synthetic reference' not in str(caught.value)
    assert capsys.readouterr().out == ''
    assert disposed == [True]
