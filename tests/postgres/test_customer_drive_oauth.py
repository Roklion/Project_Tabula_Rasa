"""Synthetic Google consent over real session, membership and connection persistence."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.google_drive import load_oauth_config
from tabula_rasa.google_drive.errors import GoogleDriveAccessError, GoogleDriveAuthorizationError
from tabula_rasa.http.connections import TenantConnections
from tabula_rasa.http.drive_oauth import CALLBACK_PATH, CustomerDriveOAuth
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant
from tests.postgres.test_identity import setup, verified
from tests.postgres.test_identity_http import client_for
from tests.postgres.test_tenant_connections import context


def fixture(database, tmp_path):
    repo, alice, bob, a, b = setup(database)
    manager = TenantConnections(database, 'test', ConnectionSecrets(tmp_path, Fernet.generate_key().decode()))
    client = Mock()
    # Deterministic remote managed-folder identities, as owned by the existing client.
    client.create_storage_root.side_effect = lambda profile, name: {'id': 'root-' + profile, 'name': name}
    client.provision_storage_children.side_effect = lambda profile, root: {
        'receipts': {'id': 'receipts-' + profile, 'name': 'Receipts'},
        'ledger-backups': {'id': 'backups-' + profile, 'name': 'Ledger Backups'}}
    exchange = Mock(side_effect=lambda config, code, uri, **kwargs: google_grant(code + '@example.test', 'synthetic-' + code))
    config = load_oauth_config({'google_drive_oauth': GOOGLE_OAUTH_CONFIG})
    manager.oauth = CustomerDriveOAuth(manager, config, 'http://127.0.0.1' + CALLBACK_PATH,
                                     exchange=exchange, client_factory=Mock(return_value=client))
    alpha, beta = context(alice, a, 'alpha'), context(bob, b, 'beta')
    sessions = [SimpleNamespace(cache_id='session-' + ctx.entity_id,
        authenticated_at=verified().authenticated_at, selected=SimpleNamespace(
            entity_id=ctx.entity_id, organization_id=ctx.organization_id)) for ctx in (alpha, beta)]
    return repo, manager, client, exchange, alpha, beta, sessions


def begin(manager, ctx, session, revision=0):
    return parse_qs(urlsplit(manager.oauth.begin(ctx, session, revision)).query)['state'][0]


def finish(manager, ctx, session, state, code='alpha', **kwargs):
    return manager.oauth.complete(ctx, session, state, code, reauthenticate=lambda: session, **kwargs)


def test_two_businesses_grants_pkce_and_preserved_binding(database, tmp_path):
    repo, manager, client, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    for ctx, session in zip((alpha, beta), sessions):
        url = manager.oauth.begin(ctx, session, 0)
        params = parse_qs(urlsplit(url).query)
        assert params['scope'] == ['https://www.googleapis.com/auth/drive.file']
        assert params['code_challenge_method'] == ['S256']
        assert 'fake-secret' not in url and 'verifier' not in params
        assert manager.oauth.status(ctx)['authorization_status'] == 'connecting'
        assert finish(manager, ctx, session, params['state'][0], ctx.entity_id)
    a, b = [manager.repository.grant(ctx) for ctx in (alpha, beta)]
    assert a['store_scope_key'] != b['store_scope_key'] and a['secret_ref'] != b['secret_ref']
    assert manager.oauth.status(alpha)['authorized_account'] == 'alpha@example.test'
    assert manager.repository.status(alpha).status == 'connected'
    assert len(exchange.call_args.kwargs['code_verifier']) >= 43
    manager.change(alpha, sessions[0], revision=1, connect=False)
    state = begin(manager, alpha, sessions[0], 2)
    assert not finish(manager, alpha, sessions[0], state, 'different')
    assert manager.repository.status(alpha).status == 'disconnected'
    state = begin(manager, alpha, sessions[0], 2)
    assert finish(manager, alpha, sessions[0], state)
    assert manager.repository.grant(alpha)['store_scope_key'] == a['store_scope_key']
    assert client.create_storage_root.call_count == 2  # no folder creation on reconnect
    assert manager.repository.status(beta).revision == 1
    assert all(b'synthetic-alpha' not in file.read_bytes() for file in tmp_path.iterdir())
    with database.transaction(read_only=True) as connection:
        assert 'synthetic-alpha' not in str(list(connection.execute(text('SELECT * FROM external_connections'))))
        assert 'synthetic-alpha' not in str(list(connection.execute(text('SELECT * FROM drive_oauth_requests'))))


@pytest.mark.parametrize('attack', ['forged', 'expired', 'wrong_session', 'wrong_business', 'replay', 'revoked', 'role_changed', 'stale_revision'])
def test_callback_denial_before_provider_access(database, tmp_path, attack):
    repo, manager, client, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    session = sessions[0]
    state = begin(manager, alpha, session)
    ctx = alpha
    if attack == 'forged':
        state = 'forged'
    elif attack == 'expired':
        with database.transaction() as connection:
            connection.execute(text("UPDATE drive_oauth_requests SET expires_at=CURRENT_TIMESTAMP-interval '1 second'"))
    elif attack == 'wrong_session':
        session = SimpleNamespace(**{**vars(session), 'cache_id': 'other'})
    elif attack == 'wrong_business':
        ctx, session = beta, sessions[1]
    elif attack == 'replay':
        assert not finish(manager, ctx, session, state, denied=True)
    elif attack in {'revoked', 'role_changed'}:
        repo.set_membership(alpha.organization_id, beta.actor_id, 'owner')
        repo.set_membership(alpha.organization_id, alpha.actor_id, 'admin', active=attack != 'revoked')
    elif attack == 'stale_revision':
        manager.repository.stage(organization_id=alpha.organization_id, entity_id=alpha.entity_id,
            profile_key='alpha', scope_key='synthetic-folder-alpha', secret_ref='a' * 32, expected_revision=0)
    with pytest.raises(IdentityError):
        finish(manager, ctx, session, state)
    exchange.assert_not_called()
    assert manager.repository.status(beta).status == 'not_configured'


@pytest.mark.parametrize('failure', ['denied', 'no_code', 'permissions', 'quota', 'outage', 'folder', 'scope', 'session_lost', 'selection_changed', 'membership_lost'])
def test_incomplete_setup_is_consumed_and_retryable_without_connected_status(database, tmp_path, failure):
    repo, manager, client, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    session = sessions[0]
    state = begin(manager, alpha, session)
    if failure in {'permissions', 'quota', 'outage'}:
        exchange.side_effect = GoogleDriveAuthorizationError('synthetic-private-provider-response')
    if failure == 'folder':
        client.validate_storage_configuration.side_effect = GoogleDriveAccessError('private-folder')
    if failure == 'scope':
        exchange.side_effect = lambda *args, **kwargs: {**google_grant(), 'scopes': ['broad-drive']}
    if failure == 'session_lost':
        session.cache_id = 'session-alpha'
        def lost():
            raise IdentityError('unauthorized')
        refresh = lost
    elif failure == 'selection_changed':
        def refresh():
            return sessions[1]
    elif failure == 'membership_lost':
        def removed():
            repo.set_membership(alpha.organization_id, beta.actor_id, 'owner')
            repo.set_membership(alpha.organization_id, alpha.actor_id, 'owner', active=False)
            return session
        refresh = removed
    else:
        def refresh():
            return session
    try:
        assert not manager.oauth.complete(alpha, session, state, '' if failure == 'no_code' else 'alpha',
            denied=failure == 'denied', reauthenticate=refresh)
    except (IdentityError, GoogleDriveAccessError, GoogleDriveAuthorizationError):
        pass
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM external_connections")) == 0
        assert connection.scalar(text("SELECT consumed FROM drive_oauth_requests"))
    with pytest.raises(IdentityError):
        finish(manager, alpha, session, state)
    if failure != 'membership_lost':
        assert manager.oauth.status(alpha)['authorization_status'] == 'failed'


def test_http_start_callback_csrf_logged_out_stale_session_and_clean_redirect(database, tmp_path, caplog):
    repo, manager, google, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    client, auth, _ = client_for(database)
    path = '/api/v1/entities/alpha/connections/google-drive/authorize'
    with client:
        client.app.state.runtime.connections = manager
        assert client.post(path, json={'revision': 0}).status_code == 401
        assert client.get(CALLBACK_PATH).status_code == 401
        token, _ = auth.sessions.issue(verified())
        client.cookies.set(auth.session_cookie, token)
        info = client.get('/api/v1/session').json()
        headers = {'origin': auth.settings.public_origin, 'x-csrf-token': info['csrf_token']}
        assert client.post(path, json={'revision': 0}).status_code == 403
        result = client.post(path, json={'revision': 0}, headers=headers)
        assert result.status_code == 200
        state = parse_qs(urlsplit(result.json()['authorization_url']).query)['state'][0]
        response = client.get(CALLBACK_PATH, params={'state': state, 'code': 'alpha'}, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/data'
        assert response.headers['referrer-policy'] == 'no-referrer'
        replay = client.get(CALLBACK_PATH, params={'state': state, 'code': 'alpha'})
        assert replay.status_code == 403
        assert replay.headers['referrer-policy'] == 'no-referrer'
        with database.transaction() as connection:
            connection.execute(text("UPDATE identity_sessions SET authenticated_at=authenticated_at-interval '6 minutes'"))
        assert client.post(path, json={'revision': 1}, headers=headers).status_code == 403
        auth.sessions.revoke(token)
        assert client.get(CALLBACK_PATH, params={'state': state, 'code': 'alpha'}).status_code == 401
    assert 'synthetic-alpha' not in caplog.text and 'fake-secret' not in caplog.text


def test_multi_business_roles_and_start_freshness(database, tmp_path):
    repo, manager, client, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    repo.set_membership(beta.organization_id, alpha.actor_id, 'admin')
    with pytest.raises(IdentityError):
        begin(manager, replace(beta, actor_id=alpha.actor_id), sessions[0])
    stale = SimpleNamespace(**{**vars(sessions[0]), 'authenticated_at': verified().authenticated_at - timedelta(minutes=6)})
    with pytest.raises(IdentityError):
        begin(manager, alpha, stale)
    exchange.assert_not_called()


def test_superseded_request_and_disconnect_cannot_be_replayed(database, tmp_path):
    _, manager, _, exchange, alpha, _, sessions = fixture(database, tmp_path)
    old = begin(manager, alpha, sessions[0])
    fresh = begin(manager, alpha, sessions[0])
    with pytest.raises(IdentityError):
        finish(manager, alpha, sessions[0], old)
    exchange.assert_not_called()
    assert finish(manager, alpha, sessions[0], fresh)
    pending = begin(manager, alpha, sessions[0], 1)
    manager.change(alpha, sessions[0], revision=1, connect=False)
    exchange.reset_mock()
    with pytest.raises(IdentityError, match='concurrent_write'):
        finish(manager, alpha, sessions[0], pending)
    exchange.assert_not_called()


def test_new_oauth_binding_composes_existing_document_adapter_and_preserves_receipt(database, tmp_path, monkeypatch):
    from hashlib import sha256
    from tabula_rasa.application.documents import DocumentUpload
    from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
    from tests.drive_fixtures import receipt_drive_file
    _, manager, client, _, alpha, beta, sessions = fixture(database, tmp_path)
    assert finish(manager, alpha, sessions[0], begin(manager, alpha, sessions[0]))
    row = manager.repository.grant(alpha)
    content = b'%PDF synthetic receipt'
    drive_file = receipt_drive_file('synthetic-file-alpha', 'receipt.pdf', profile_key=row['profile_key'],
        receipt_id='a' * 32, sha256=sha256(content).hexdigest(), original_name='receipt.pdf', size=len(content))
    client.upload_receipt.return_value = drive_file
    client.list_profile_receipts.return_value = [drive_file]
    client.download_file.return_value = content
    monkeypatch.setattr('tabula_rasa.google_drive.GoogleDriveClient', Mock(return_value=client))
    store = manager.document_store(alpha)
    document = store.upload('alpha', DocumentUpload('a' * 32, 'receipt.pdf', 'application/pdf', sha256(content).hexdigest(), content))
    receipts = PostgresReceiptRepository(database, 'alpha', store_kind='google_drive', store_scope_key=row['store_scope_key'])
    receipts.register_document(document)
    assert store.fetch('alpha', document.storage_key) == content
    before = receipts.retained_documents()
    manager.change(alpha, sessions[0], revision=1, connect=False)
    assert finish(manager, alpha, sessions[0], begin(manager, alpha, sessions[0], 2))
    assert receipts.retained_documents() == before
    assert store.fetch('alpha', document.storage_key) == content
    with pytest.raises(IdentityError):
        store.fetch('beta', document.storage_key)
    client.delete_file.assert_not_called()
