"""Sanitized read-only tenancy preflight command outcomes."""

import json

import pytest

from scripts import inspect_business_tenancy as cli


@pytest.mark.parametrize('ready,exit_code', [(True, 0), (False, 2)])
def test_preflight_reports_inventory_without_mutation(monkeypatch, capsys, ready, exit_code):
    class Database:
        disposed = False

        def __init__(self, settings):
            pass

        def dispose(self):
            self.disposed = True

    database = Database(None)
    monkeypatch.setattr(cli.DatabaseSettings, 'from_environment', lambda **_: None)
    monkeypatch.setattr(cli, 'Database', lambda _: database)
    result = {'ready_for_constraint': ready}
    monkeypatch.setattr(cli, 'tenancy_inventory', lambda db: result if db is database else None)
    assert cli.main() == exit_code
    assert json.loads(capsys.readouterr().out) == result
    assert database.disposed


def test_preflight_does_not_print_configuration_errors(monkeypatch, capsys):
    def fail(**_):
        raise ValueError('private configuration')
    monkeypatch.setattr(cli.DatabaseSettings, 'from_environment', fail)
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out) == {'error': 'tenancy_preflight_unavailable'}
