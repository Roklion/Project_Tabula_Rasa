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
