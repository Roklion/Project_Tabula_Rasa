from types import SimpleNamespace

import pytest

from scripts import rotate_identity_configuration as cli


@pytest.mark.parametrize('failure', [None, 'rotation', 'dispose'])
def test_operator_rotation_uses_process_database_and_safe_output(monkeypatch, capsys, failure):
    calls = []
    settings = SimpleNamespace(access_mode='named_user', environment='synthetic')
    monkeypatch.setattr(cli.HttpSettings, 'from_environment', lambda: settings)
    monkeypatch.setattr(cli.OidcSettings, 'from_environment',
                        lambda actual, env: SimpleNamespace(configuration_hash='a' * 64))
    def database_settings(env, *, required):
        assert env is cli.os.environ and required
        return 'process-only'
    monkeypatch.setattr(cli.DatabaseSettings, 'from_environment', database_settings)
    class Database:
        def __init__(self, configuration):
            assert configuration == 'process-only'
        def dispose(self):
            calls.append('disposed')
            if failure == 'dispose':
                raise RuntimeError('private-connection-secret')
    class Repository:
        def __init__(self, database, environment, configuration_hash):
            assert environment == 'synthetic' and configuration_hash == 'a' * 64
        def rotate_configuration(self, epoch):
            calls.append(epoch)
            if failure == 'rotation':
                raise RuntimeError('private-connection-secret')
    monkeypatch.setattr(cli, 'Database', Database)
    monkeypatch.setattr(cli, 'PostgresSessionRepository', Repository)
    assert cli.main(['--expected-epoch', '7']) == (1 if failure else 0)
    assert calls == [7, 'disposed']
    output = capsys.readouterr()
    assert 'private-connection-secret' not in output.out + output.err
    assert ('failed' if failure else 'rotated') in output.out
