"""Named membership -> authorization -> native services, with two tenants."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.identity import NamedIdentity
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tests.http.test_authorization import ROUTES, path_for
from tests.postgres.test_identity import setup, verified
from tests.test_application_documents import FakeDocumentStore


@contextmanager
def named_client(database):
    repo, alice, bob, org_a, org_b = setup(database)
    settings = HttpSettings('test', 'http://127.0.0.1', access_mode='named_user')
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    auth = NamedIdentity(settings, sessions, Mock())
    stores = {scope: FakeDocumentStore() for scope in ('alpha', 'beta')}
    factory = Mock(side_effect=lambda context: create_postgres_services(database, context.entity_id,
        document_store=stores[context.entity_id], document_store_kind='fake'))
    runtime = PostgresRuntime(database, auth, service_factory=factory, identity=auth)
    with TestClient(create_app(settings=settings, runtime_factory=lambda _: runtime), base_url=settings.public_origin) as client:
        raw, session = sessions.issue(verified())
        client.cookies.set(auth.session_cookie, raw)
        headers = {'Origin': settings.public_origin, 'X-CSRF-Token': session.csrf_token}
        yield client, auth, repo, (alice, bob, org_a, org_b), factory, stores, headers


def test_native_reads_writes_stale_baselines_and_role_downgrade(database):
    with named_client(database) as (client, auth, repo, identities, factory, stores, headers):
        alice, bob, org_a, _ = identities
        account_path = '/api/v1/entities/alpha/accounts'
        created = client.post(account_path, headers=headers, json={'name': 'Reserve', 'type': 'Bank'})
        assert created.status_code == 201, created.text
        row = created.json()
        for baseline, expected in [(None, 422), (row['baseline'], 200), (row['baseline'], 409)]:
            updated = client.patch(account_path + '/' + row['id'], headers=headers,
                json={'baseline': baseline, 'changes': {'name': 'Updated', 'type': 'Bank',
                    'classification': 'Asset', 'opening_balance': '0', 'active': True, 'parent_id': None}})
            assert updated.status_code == expected, updated.text
        assert updated.json()['error']['code'] == 'stale'
        doc_path = '/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content'
        uploaded = client.put(doc_path, params={'filename': 'receipt.pdf'}, headers=headers, content=b'%PDF alpha')
        assert uploaded.status_code == 200, uploaded.text
        repo.set_membership(org_a, bob.id, 'owner')
        repo.set_membership(org_a, alice.id, 'read_only')
        assert client.get(account_path).status_code == 200
        assert client.get(doc_path).content == b'%PDF alpha'
        assert client.get('/api/v1/entities/alpha/reports/summary').status_code == 200
        assert client.post('/api/v1/entities/alpha/mixed-use/allocation', headers=headers,
                           json={'total_expense': '100', 'business_use_percentage': '50'}).status_code == 200
        factory.reset_mock()
        denied = client.put(doc_path, params={'filename': 'receipt.pdf'}, headers=headers, content=b'%PDF alpha')
        assert denied.status_code == 403
        assert client.post(account_path, headers=headers, json={'name': 'Forbidden', 'type': 'Bank'}).status_code == 403
        factory.assert_not_called()
        assert stores['alpha'].upload_calls == 1 and stores['beta'].upload_calls == 0
        # Editor gets ordinary writes on the same issued session, never bulk/admin rights.
        repo.set_membership(org_a, alice.id, 'editor')
        assert client.post(account_path, headers=headers, json={'name': 'Editor', 'type': 'Bank'}).status_code == 201
        assert 'bookkeeping:export' not in client.get('/api/v1/session').json()['capabilities']
        assert auth.authenticated(Mock(cookies={auth.session_cookie: client.cookies.get(auth.session_cookie)})).selected.role == 'editor'


def test_every_native_route_rejects_foreign_and_revoked_membership_before_binding(database):
    with named_client(database) as (client, auth, repo, identities, factory, _, headers):
        alice, bob, org_a, _ = identities
        for route in ROUTES:
            result = client.request(next(iter(route.methods)), path_for(route, 'beta'), headers=headers, json={})
            assert result.status_code == 403, (route.operation_id, result.text)
        factory.assert_not_called()
        repo.set_membership(org_a, bob.id, 'owner')
        repo.set_membership(org_a, alice.id, 'editor', active=False)
        assert client.get('/api/v1/session').json()['state'] == 'needs_setup'
        assert client.get('/api/v1/entities').json()['items'] == []
        for route in ROUTES:
            result = client.request(next(iter(route.methods)), path_for(route), headers=headers, json={})
            assert result.status_code == 403, (route.operation_id, result.text)
        factory.assert_not_called()


@pytest.mark.parametrize('loss', ['missing', 'expired', 'revoked', 'user_disabled', 'organization_suspended', 'entity_inactive'])
def test_issued_credentials_lose_access_to_data_and_document_bytes(database, loss):
    with named_client(database) as (client, auth, repo, identities, factory, _, headers):
        alice, bob, org_a, _ = identities
        expected = 401
        if loss == 'missing':
            client.cookies.clear()
        elif loss == 'expired':
            auth.sessions.clock = lambda: verified().authenticated_at + timedelta(hours=13)
        elif loss == 'revoked':
            repo.revoke_user_sessions(alice.id)
        elif loss == 'user_disabled':
            repo.set_membership(org_a, bob.id, 'owner')
            repo.set_user_state(alice.id, 'disabled')
        elif loss == 'organization_suspended':
            repo.set_organization_state(org_a, 'suspended')
            expected = 403
        else:
            with database.transaction() as connection:
                connection.execute(text("UPDATE organization_entities SET state='inactive' WHERE entity_id='alpha'"))
            expected = 403
        for path in ('accounts', 'documents/' + 'a' * 32 + '/content', 'reports/summary'):
            result = client.get('/api/v1/entities/alpha/' + path)
            assert result.status_code == expected, result.text
        factory.assert_not_called()


def test_forged_selection_discovery_and_colliding_document_ids_stay_in_two_organizations(database):
    with named_client(database) as (client, auth, repo, identities, factory, stores, headers):
        _, _, org_a, _ = identities
        cookie = client.cookies.get(auth.session_cookie)
        client.cookies.set('tabula_entity', 'beta')
        claimed = {**headers, 'X-Organization-ID': 'foreign', 'X-Role': 'owner', 'X-Entity-ID': 'beta'}
        assert [item['id'] for item in client.get('/api/v1/entities', headers=claimed).json()['items']] == ['alpha']
        assert client.post('/api/v1/session/entity', headers=claimed, json={'entity_id': 'beta'}).status_code == 403
        assert client.post('/api/v1/session/entity', headers=claimed, json={'entity_id': 'missing'}).status_code == 403
        factory.assert_not_called()
        foreign = client.get('/api/v1/entities/beta/accounts').json()['error']
        absent = client.get('/api/v1/entities/does-not-exist/accounts').json()['error']
        assert foreign == absent
        path = '/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content'
        assert client.put(path, headers=claimed, params={'filename': 'receipt.pdf'}, content=b'%PDF alpha').status_code == 200
        other_raw, other_session = auth.sessions.issue(verified('bob'))
        client.cookies.set(auth.session_cookie, other_raw)
        other_headers = {**headers, 'X-CSRF-Token': other_session.csrf_token}
        other_path = path.replace('/alpha/', '/beta/')
        assert client.put(other_path, headers=other_headers, params={'filename': 'receipt.pdf'}, content=b'%PDF beta').status_code == 200
        assert client.get(other_path).content == b'%PDF beta'
        factory.reset_mock()
        assert client.get(path).status_code == 403
        factory.assert_not_called()
        client.cookies.set(auth.session_cookie, cookie)
        assert client.get(path).content == b'%PDF alpha'
        assert client.get(other_path).status_code == 403
        assert stores['alpha'].upload_calls == stores['beta'].upload_calls == 1
        # Stale destination/body claims cannot grant a second owning organization.
        with pytest.raises(IdentityError):
            repo.bind_entity(org_a, 'beta')


def test_unavailable_membership_never_binds_resources(database):
    with named_client(database) as (client, auth, _, _, factory, _, _):
        auth.sessions.validate = Mock(side_effect=IdentityError('unavailable'))
        assert client.get('/api/v1/entities/alpha/accounts').status_code == 503
        assert client.get('/api/v1/entities/alpha/documents/' + 'a' * 32 + '/content').status_code == 503
        factory.assert_not_called()


def test_backup_restore_and_local_admin_remain_unavailable_remotely(database):
    with named_client(database) as (client, _, repo, identities, factory, _, headers):
        alice, bob, org_a, _ = identities
        repo.set_membership(org_a, bob.id, 'owner')
        for role in ('owner', 'admin', 'accountant', 'editor', 'read_only'):
            repo.set_membership(org_a, alice.id, role)
            for path in ('backup', 'backups', 'restore', 'recovery', 'migration', 'cutover', 'reset', 'connections', 'profile-admin'):
                for entity in ('alpha', 'beta'):
                    for method in ('GET', 'POST'):
                        result = client.request(method, '/api/v1/entities/' + entity + '/' + path,
                                                headers=headers, json={'source_entity_id': 'beta', 'target_entity_id': 'alpha'})
                        assert result.status_code in {404, 405}  # SPA GET catch-all may reject unsupported methods.
        factory.assert_not_called()
