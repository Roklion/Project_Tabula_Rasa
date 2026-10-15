from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import text

from scripts.manage_identity_bindings import stage_connection
from tabula_rasa.application.identity import IdentityError
from tabula_rasa.http.connections import TenantConnections
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant
from tests.postgres.test_identity import setup
from tests.postgres.test_tenant_connections import context


def test_operator_preflight_stages_exact_pending_grant_and_owner_activates(database, tmp_path, monkeypatch):
    repo, alice, bob, a, b = setup(database)
    secrets = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    grant = google_grant(token='synthetic-private-grant')
    grant.update({key: {'id': name + '-alpha', 'name': name} for key, name in [
        ('storage_root', 'root'), ('receipt_folder', 'folder'), ('backup_folder', 'backup')]})
    payload = dict(environment='test', organization_id=a, entity_id='alpha', provider='google_drive',
        profile_key='alpha', scope_key='folder-alpha', google_drive_oauth=GOOGLE_OAUTH_CONFIG, google_drive=grant)
    client = Mock()
    monkeypatch.setattr('tabula_rasa.google_drive.GoogleDriveClient', Mock(return_value=client))
    preview = stage_connection(database, secrets, payload, environment='test', expected_revision=0)
    assert not preview['applied'] and list(tmp_path.iterdir()) == []
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM external_connections')) == 0
    with pytest.raises(IdentityError):
        stage_connection(database, secrets, payload, environment='production', expected_revision=0)
    with pytest.raises(IdentityError):
        stage_connection(database, secrets, payload, environment='test', expected_revision=0,
                         apply=True, expected_plan='0' * 64)
    assert list(tmp_path.iterdir()) == []
    result = stage_connection(database, secrets, payload, environment='test', expected_revision=0,
                              apply=True, expected_plan=preview['plan_sha256'])
    assert result['status'] == 'pending' and len(list(tmp_path.iterdir())) == 1
    manager = TenantConnections(database, 'test', secrets)
    ctx = context(alice, a, 'alpha')
    assert manager.repository.status(ctx).status == 'pending'
    from tests.postgres.test_identity import verified
    assert manager.change(ctx, SimpleNamespace(authenticated_at=verified().authenticated_at),
                          revision=1, connect=True).status == 'connected'
    client.validate_storage_configuration.assert_called_with('alpha')
    # Replacing an approved grant requires the current revision and same folder.
    with pytest.raises(IdentityError):
        stage_connection(database, secrets, {**payload, 'scope_key': 'folder-beta'},
                         environment='test', expected_revision=2)
    with pytest.raises(IdentityError):
        stage_connection(database, secrets, payload, environment='test', expected_revision=0)
    for profile, scope in [('alpha', 'folder-beta'), ('beta', 'folder-alpha')]:
        with pytest.raises(IdentityError):
            manager.repository.stage(organization_id=b, entity_id='beta', profile_key=profile,
                scope_key=scope, secret_ref='c' * 32, expected_revision=0, dry_run=True)


def test_missing_or_revoked_secret_cannot_activate_and_does_not_enable_bytes(database, tmp_path, monkeypatch):
    from tabula_rasa.google_drive.errors import GoogleDriveAuthorizationError
    from tests.postgres.test_tenant_connections import fixture
    repo, manager, secrets, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    manager.change(alpha, session, revision=2, connect=False)
    manager.store_factory = Mock(side_effect=GoogleDriveAuthorizationError('private token fixture'))
    with pytest.raises(IdentityError) as error:
        manager.change(alpha, session, revision=3, connect=True)
    assert error.value.__context__ is None
    assert manager.repository.status(alpha).status == 'disconnected'
    assert manager.repository.status(alpha).revision == 3
    manager.secrets = None
    with pytest.raises(IdentityError):
        manager.change(alpha, session, revision=3, connect=True)
    with pytest.raises(IdentityError):
        manager.document_store(alpha).fetch('alpha', 'file')
