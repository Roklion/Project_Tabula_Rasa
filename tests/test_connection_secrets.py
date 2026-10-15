from cryptography.fernet import Fernet
import pytest

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets


def test_encrypted_store_is_exact_environment_owner_entity_provider_scoped(tmp_path):
    key = Fernet.generate_key().decode()
    store = ConnectionSecrets(tmp_path, key)
    scope = dict(environment='staging', organization_id='org-a', entity_id='entity-a', provider='google_drive')
    reference = store.put({**scope, 'refresh_token': 'synthetic-only-secret'})
    assert store.get(reference, **scope)['refresh_token'] == 'synthetic-only-secret'
    assert b'synthetic-only-secret' not in (tmp_path / (reference + '.grant')).read_bytes()
    for field in scope:
        with pytest.raises(IdentityError) as error:
            store.get(reference, **{**scope, field: 'foreign'})
        assert error.value.__context__ is None
    for reference_value in ('../credentials', 'unknown', 'a' * 32):
        with pytest.raises(IdentityError):
            store.get(reference_value, **scope)
    with pytest.raises(IdentityError):
        ConnectionSecrets(tmp_path, Fernet.generate_key().decode()).get(reference, **scope)
    assert ConnectionSecrets.from_environment({}) is None
    with pytest.raises(IdentityError):
        ConnectionSecrets.from_environment({'TABULA_RASA_CONNECTION_SECRETS_DIR': str(tmp_path)})


def test_store_refuses_tampered_ciphertext(tmp_path):
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    scope = dict(environment='test', organization_id='org', entity_id='entity', provider='google_drive')
    reference = store.put(scope)
    (tmp_path / (reference + '.grant')).write_bytes(b'tampered')
    with pytest.raises(IdentityError):
        store.get(reference, **scope)


def test_operator_cli_errors_do_not_echo_input_or_credentials(tmp_path, capsys, monkeypatch):
    from unittest.mock import Mock
    from scripts.manage_identity_bindings import main
    monkeypatch.setattr('scripts.manage_identity_bindings.DatabaseSettings', Mock())
    monkeypatch.setattr('scripts.manage_identity_bindings.Database', Mock(side_effect=ValueError('synthetic-never-echo')))
    source = tmp_path / 'private.json'
    source.write_text('{"refresh_token":"synthetic-never-echo"}', encoding='utf-8')
    assert main(['claim', '--input', str(source)]) == 1
    assert 'synthetic-never-echo' not in capsys.readouterr().out


@pytest.mark.parametrize('environment', [None, '', 'unknown', 7, ['test']])
@pytest.mark.parametrize('apply', [False, True])
def test_provisioning_rejects_missing_or_unsupported_environment_before_binding(environment, apply, monkeypatch):
    from unittest.mock import Mock
    from scripts.manage_identity_bindings import stage_connection
    database, secrets = Mock(), Mock()
    provider = Mock()
    monkeypatch.setattr('tabula_rasa.http.connections.google_store', provider)
    payload = dict(environment=environment, provider='google_drive', organization_id='org', entity_id='entity',
                   profile_key='profile', scope_key='folder', google_drive_oauth={}, google_drive={})
    with pytest.raises(IdentityError, match='forbidden'):
        stage_connection(database, secrets, payload, environment=environment,
                         expected_revision=0, apply=apply)
    assert not database.mock_calls and not secrets.mock_calls
    provider.assert_not_called()


def test_connection_cli_requires_environment_before_reading_input(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from scripts.manage_identity_bindings import main
    read = Mock()
    monkeypatch.setattr('scripts.manage_identity_bindings.read_private', read)
    with pytest.raises(SystemExit) as error:
        main(['connection', '--input', str(tmp_path / 'not-read.json')])
    assert error.value.code == 2
    read.assert_not_called()
