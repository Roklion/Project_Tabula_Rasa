"""Real control-plane persistence; byte providers and credentials are synthetic."""
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import text

from tabula_rasa.application.documents import DocumentError, DocumentMetadata, DocumentReference, ReceiptInventory
from tabula_rasa.application.identity import IdentityError, capabilities
from tabula_rasa.http.connections import TenantConnections
from tabula_rasa.http.context import RequestContext
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services, create_postgres_export_service
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tests.postgres.test_identity import setup, verified
from tests.postgres.test_identity_http import client_for


def context(user, org, entity):
    return RequestContext(user.id, org, entity, capabilities('owner'), 'test-cache', 'test-csrf')


def provision(manager, store, ctx):
    payload = dict(environment='test', organization_id=ctx.organization_id, entity_id=ctx.entity_id,
                   provider='google_drive', profile_key=ctx.entity_id, scope_key='folder-' + ctx.entity_id,
                   synthetic_token='fake-refresh-' + ctx.entity_id)
    reference = store.put(payload)
    manager.repository.stage(organization_id=ctx.organization_id, entity_id=ctx.entity_id,
        profile_key=ctx.entity_id, scope_key=payload['scope_key'], secret_ref=reference, expected_revision=0)
    return reference


def fixture(database, tmp_path):
    repo, alice, bob, a, b = setup(database)
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    calls = []
    def factory(row, payload, **kwargs):
        calls.append((row['entity_id'], payload['synthetic_token']))
        return SimpleNamespace(scope_key=row['store_scope_key'], fetch=lambda *args: row['entity_id'].encode())
    manager = TenantConnections(database, 'test', store, store_factory=factory)
    alpha, beta = context(alice, a, 'alpha'), context(bob, b, 'beta')
    refs = [provision(manager, store, ctx) for ctx in (alpha, beta)]
    session = SimpleNamespace(authenticated_at=verified().authenticated_at)
    for ctx in (alpha, beta):
        manager.change(ctx, session, revision=1, connect=True)
    calls.clear()
    return repo, manager, store, calls, alpha, beta, refs, session


def test_migrated_startup_validates_scoped_connected_grants_without_provider_io(database, tmp_path):
    repo, manager, secrets, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    def validate(ctx):
        manager.validate_migrated_binding(organization_id=ctx.organization_id, entity_id=ctx.entity_id,
            profile_key=ctx.entity_id, scope_key='folder-' + ctx.entity_id)
    validate(alpha)
    validate(beta)
    assert calls == [('alpha', 'fake-refresh-alpha'), ('beta', 'fake-refresh-beta')]
    with pytest.raises(IdentityError, match='unavailable'):
        validate(replace(alpha, organization_id=beta.organization_id))
    # Ciphertext from the other profile remains unusable at this boundary.
    (tmp_path / (refs[0] + '.grant')).write_bytes((tmp_path / (refs[1] + '.grant')).read_bytes())
    with pytest.raises(IdentityError, match='unavailable'):
        validate(alpha)
    validate(beta)
    manager.change(beta, session, revision=2, connect=False)
    with pytest.raises(IdentityError, match='unavailable'):
        validate(beta)


@pytest.mark.parametrize('failure', [None, 'disconnected', 'missing_grant'])
def test_migrated_startup_uses_effective_s3_connection_without_drive_fallback(database, tmp_path, failure):
    from tabula_rasa.infrastructure.postgres.managed_documents import install_managed_connection
    repo, manager, secrets, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    reference = secrets.put(dict(environment='test', organization_id=alpha.organization_id, entity_id='alpha',
        provider='s3', profile_key='alpha', scope_key='managed-alpha', synthetic_token='fake-managed-alpha'))
    with database.transaction() as connection:
        install_managed_connection(connection, 'alpha', 'managed-alpha', organization_id=alpha.organization_id,
                                   profile_key='alpha', secret_ref=reference, expected_revision=0)
        if failure == 'disconnected':
            connection.execute(text("UPDATE external_connections SET status='disconnected' WHERE provider='s3'"))
    if failure == 'missing_grant':
        (tmp_path / (reference + '.grant')).unlink()
    def validate(ctx):
        manager.validate_migrated_binding(organization_id=ctx.organization_id, entity_id=ctx.entity_id,
            profile_key=ctx.entity_id, scope_key='folder-' + ctx.entity_id)
    if failure:
        with pytest.raises(IdentityError, match='unavailable'):
            validate(alpha)
        assert calls == []
    else:
        validate(alpha)
        assert calls == [('alpha', 'fake-managed-alpha')]
    assert manager.document_store(alpha).store_kind == 's3'
    validate(beta)
    assert calls[-1] == ('beta', 'fake-refresh-beta')


def test_two_org_grants_restart_disconnect_reconnect_and_no_exported_tokens(database, tmp_path):
    repo, manager, secrets, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    cached = manager.document_store(alpha)
    assert cached.fetch('alpha', 'file') == b'alpha'
    assert manager.document_store(beta).fetch('beta', 'file') == b'beta'
    assert calls == [('alpha', 'fake-refresh-alpha'), ('beta', 'fake-refresh-beta')]
    with pytest.raises(IdentityError):
        manager.document_store(replace(alpha, entity_id='beta'))
    with pytest.raises(IdentityError):
        cached.fetch('beta', 'file')
    manager.change(alpha, session, revision=2, connect=False)
    before = len(calls)
    with pytest.raises(IdentityError):
        cached.fetch('alpha', 'file')
    assert len(calls) == before
    assert manager.document_store(beta).fetch('beta', 'file') == b'beta'
    manager.change(alpha, session, revision=3, connect=True)
    # New connection manager and new pool: no ambient grant/session fallback.
    from tabula_rasa.infrastructure.postgres.runtime import Database
    from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
    restarted = Database(DatabaseSettings(database.engine.url))
    try:
        fresh = TenantConnections(restarted, 'test', secrets, store_factory=manager.store_factory)
        assert fresh.document_store(alpha).fetch('alpha', 'file') == b'alpha'
    finally:
        restarted.dispose()
    with database.transaction(read_only=True) as connection:
        metadata = [dict(row) for row in connection.execute(text('SELECT * FROM external_connections')).mappings()]
    assert 'fake-refresh' not in str(metadata)
    assert 'fake-refresh' not in json.dumps(create_postgres_export_service(database, 'alpha').export())
    assert all(b'fake-refresh' not in file.read_bytes() for file in tmp_path.iterdir())
    # Grant loss denies at the byte boundary, including already-composed stores.
    (tmp_path / (refs[0] + '.grant')).unlink()
    with pytest.raises(DocumentError, match='unavailable') as error:
        cached.fetch('alpha', 'file')
    assert error.value.__context__ is None
    assert manager.document_store(beta).fetch('beta', 'file') == b'beta'


def test_revoked_grant_updates_safe_status_and_member_removal_denies_cached_store(database, tmp_path):
    from tabula_rasa.google_drive.errors import GoogleDriveAuthorizationError
    repo, manager, secrets, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    cached = manager.document_store(alpha)
    def revoked(*args, **kwargs):
        raise GoogleDriveAuthorizationError('synthetic provider credential must never escape')
    manager.store_factory = lambda row, payload, **kwargs: SimpleNamespace(scope_key=row['store_scope_key'], fetch=revoked)
    with pytest.raises(DocumentError) as caught:
        cached.fetch('alpha', 'file')
    assert str(caught.value) == 'Document storage is unavailable.' and caught.value.__context__ is None
    assert manager.repository.status(alpha).status == 'reconnect_required'
    # Preserve an owner while removing the caller.
    repo.set_membership(alpha.organization_id, beta.actor_id, 'owner')
    repo.set_membership(alpha.organization_id, alpha.actor_id, 'owner', active=False)
    secrets.get = Mock(side_effect=AssertionError('No secret binding after membership denial'))
    with pytest.raises(IdentityError, match='forbidden'):
        cached.fetch('alpha', 'file')
    secrets.get.assert_not_called()


@pytest.mark.parametrize('mounted', [False, True])
def test_http_owner_freshness_csrf_foreign_scope_logout_and_private_bytes(database, tmp_path, caplog, mounted):
    repo, manager, store, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    if mounted:
        from tests.test_connection_secret_mounts import link
        version = tmp_path / '..version'
        version.mkdir()
        for reference in refs:
            path = tmp_path / (reference + '.grant')
            path.rename(version / path.name)
            link(path, version / path.name)
    client, auth, factory = client_for(database)
    doc = DocumentReference('alpha', DocumentMetadata('a' * 32, 'receipt.pdf', 'receipt.pdf',
        'application/pdf', 5, 'a' * 64), 'provider-file', '')
    PostgresReceiptRepository(database, 'alpha', store_kind='google_drive',
        store_scope_key='folder-alpha').register_document(doc)
    manager.store_factory = lambda row, payload, **kwargs: SimpleNamespace(
        scope_key=row['store_scope_key'], metadata=lambda *args: doc,
        inventory=lambda *args, **kwargs: ReceiptInventory((doc,), ()), fetch=lambda *args: b'alpha')
    with client:
        runtime = client.app.state.runtime
        runtime.connections = manager
        runtime.service_factory = lambda ctx: create_postgres_services(database, ctx.entity_id,
            document_store=manager.document_store(ctx), document_store_kind='google_drive')
        token, _ = auth.sessions.issue(verified())
        client.cookies.set(auth.session_cookie, token)
        info = client.get('/api/v1/session').json()
        headers = {'origin': auth.settings.public_origin, 'x-csrf-token': info['csrf_token']}
        client.cookies.set(auth.csrf_cookie, info['csrf_token'])
        path = '/api/v1/entities/alpha/connections/google-drive'
        assert client.get(path).json() == {'provider': 'google_drive', 'status': 'connected', 'revision': 2,
                                                 'self_service_available': False, 'authorization_status': None, 'authorized_account': None}
        assert client.get('/api/v1/entities/beta/connections/google-drive').status_code == 403
        assert client.post(path, json={'revision': 2, 'connect': False}).status_code == 403
        assert client.post(path, headers=headers, json={'revision': 1, 'connect': False}).status_code == 409
        assert client.get('/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content').content == b'alpha'
        assert client.post(path, headers=headers, json={'revision': 2, 'connect': False}).status_code == 200
        assert client.get('/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content').status_code == 503
        assert client.post(path, headers=headers, json={'revision': 3, 'connect': True, 'secret_ref': refs[1]}).status_code == 422
        assert client.post(path, headers=headers, json={'revision': 3, 'connect': True}).status_code == 200
        # A stale provider auth_time is separate from a still-valid app session.
        with database.transaction() as connection:
            connection.execute(text("UPDATE identity_sessions SET authenticated_at=authenticated_at-interval '6 minutes'"))
        assert client.post(path, headers=headers, json={'revision': 4, 'connect': False}).status_code == 403
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
        assert client.get('/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content').status_code == 401
        assert client.get(path).status_code == 401
    assert 'fake-refresh' not in caplog.text


@pytest.mark.parametrize('role', ['admin', 'editor', 'accountant', 'read_only'])
def test_nonowner_cannot_inspect_or_manage_grants(database, tmp_path, role):
    repo, manager, store, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    repo.set_membership(alpha.organization_id, beta.actor_id, 'owner')
    repo.set_membership(alpha.organization_id, alpha.actor_id, role)
    store.get = Mock(side_effect=AssertionError('No credentials for denied management'))
    with pytest.raises(IdentityError, match='forbidden'):
        manager.repository.status(alpha)
    with pytest.raises(IdentityError, match='forbidden'):
        manager.change(alpha, session, revision=2, connect=True)
    if role == 'read_only':
        with pytest.raises(IdentityError, match='forbidden'):
            manager.document_store(alpha).upload('alpha', object())
    store.get.assert_not_called()


@pytest.mark.parametrize('failure', ['missing_grant', 'provider_unavailable'])
def test_document_dependency_telemetry_and_recovery_preserve_other_business(database, tmp_path, caplog, failure):
    repo, manager, store, calls, alpha, beta, refs, session = fixture(database, tmp_path)
    content = {'alpha': b'alpha', 'beta': b'beta'}
    documents = {}
    selected = []
    unavailable = False
    for ctx in (alpha, beta):
        data = content[ctx.entity_id]
        doc = DocumentReference(ctx.entity_id, DocumentMetadata('a' * 32, 'receipt.pdf', 'receipt.pdf',
            'application/pdf', len(data), sha256(data).hexdigest()), 'provider-file', '')
        PostgresReceiptRepository(database, ctx.entity_id, store_kind='google_drive',
            store_scope_key='folder-' + ctx.entity_id).register_document(doc)
        documents[ctx.entity_id] = doc

    def provider(row, payload, **kwargs):
        entity = row['entity_id']
        selected.append(entity)
        def fetch(*args):
            if unavailable and entity == 'alpha':
                raise RuntimeError('synthetic-private-provider-detail')
            return content[entity]
        return SimpleNamespace(scope_key=row['store_scope_key'], fetch=fetch,
            inventory=lambda *args, **kwargs: ReceiptInventory((documents[entity],), ()))

    manager.store_factory = provider
    client, auth, factory = client_for(database)
    caplog.set_level('INFO', logger='tabula_rasa.http')

    def event(response):
        logged = [json.loads(record.message) for record in caplog.records if record.name == 'tabula_rasa.http']
        return next(item for item in reversed(logged) if item.get('request_id') == response.headers['x-request-id'])

    with client:
        runtime = client.app.state.runtime
        runtime.service_factory = lambda ctx: create_postgres_services(database, ctx.entity_id,
            document_store=manager.document_store(ctx), document_store_kind='google_drive')
        tokens = {entity: auth.sessions.issue(verified(subject))[0]
                  for entity, subject in (('alpha', 'alice'), ('beta', 'bob'))}

        def read(entity):
            client.cookies.clear()
            client.cookies.set(auth.session_cookie, tokens[entity])
            return client.get('/api/v1/entities/' + entity + '/documents/' + 'a' * 32 + '/content')

        for entity in content:
            assert read(entity).content == content[entity]
        encrypted = (tmp_path / (refs[0] + '.grant')).read_bytes()
        if failure == 'missing_grant':
            (tmp_path / (refs[0] + '.grant')).rename(tmp_path / 'offline.grant')
        else:
            unavailable = True
        response = read('alpha')
        assert response.status_code == 503 and response.json()['error']['code'] == 'unavailable'
        signal = event(response)
        assert signal['provider'] == 'documents' and signal['provider_status'] == 'unavailable'
        assert signal['operation'] == 'download_document' and signal['outcome'] == 'failure'
        assert signal.get('security_event') is None
        unaffected = read('beta')
        assert unaffected.status_code == 200 and unaffected.content == content['beta']
        assert event(unaffected)['outcome'] == 'success'
        assert manager.repository.status(alpha).status == manager.repository.status(beta).status == 'connected'
        if failure == 'missing_grant':
            (tmp_path / 'offline.grant').rename(tmp_path / (refs[0] + '.grant'))
        unavailable = False
        recovered = read('alpha')
        assert recovered.status_code == 200 and recovered.content == content['alpha']
        assert event(recovered)['outcome'] == 'success'
        assert (tmp_path / (refs[0] + '.grant')).read_bytes() == encrypted
        for ctx in (alpha, beta):
            retained = PostgresReceiptRepository(database, ctx.entity_id, store_kind='google_drive',
                store_scope_key='folder-' + ctx.entity_id).retained_documents()
            assert retained == (documents[ctx.entity_id],)
        before = len(selected)
        denied = client.get('/api/v1/entities/beta/documents/' + 'a' * 32 + '/content')
        assert denied.status_code == 403
        assert event(denied)['security_event'] == 'authorization_denied'
        assert len(selected) == before
    assert 'synthetic-private-provider-detail' not in response.text + caplog.text
    assert 'fake-refresh' not in response.text + caplog.text
    assert str(tmp_path) not in response.text + caplog.text
