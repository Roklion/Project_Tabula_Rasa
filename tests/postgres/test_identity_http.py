from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.identity import NamedIdentity
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tests.postgres.test_identity import setup, verified
from tests.postgres._support import entity


def client_for(database):
    settings = HttpSettings('test', 'http://127.0.0.1', access_mode='named_user')
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    provider = Mock()
    auth = NamedIdentity(settings, sessions, provider)
    factory = Mock(side_effect=AssertionError('No private service composition allowed'))
    runtime = PostgresRuntime(database, auth, service_factory=factory, identity=auth)
    app = create_app(settings=settings, runtime_factory=lambda _: runtime)
    return TestClient(app, base_url=settings.public_origin), auth, factory


def test_login_callback_cookie_contract_and_no_entity_setup(database):
    client, auth, factory = client_for(database)
    auth.provider.authorization_url.return_value = 'https://id.example.test/authorize'
    auth.provider.verify.return_value = verified()
    with client:
        assert client.get('/api/v1/session').status_code == 401
        assert client.get('/api/v1/auth/login?return_path=https://foreign.test').status_code == 403
        start = client.get('/api/v1/auth/login', follow_redirects=False)
        assert start.status_code == 303
        transaction = auth.provider.authorization_url.call_args.args[0]
        assert client.get('/api/v1/session').status_code == 401
        assert auth.login_cookie in client.cookies  # Late private denial cannot erase login.
        result = client.get('/api/v1/auth/callback', params={'code': 'synthetic-code', 'state': transaction.state}, follow_redirects=False)
        assert result.status_code == 303 and result.headers['location'] == '/'
        cookies = result.headers.get_list('set-cookie')
        assert all('HttpOnly' in cookie and 'Path=/' in cookie and 'SameSite=lax' in cookie and 'Domain=' not in cookie for cookie in cookies)
        session = client.get('/api/v1/session').json()
        assert session['state'] == 'needs_setup' and session['entity'] is None and not session['capabilities']
        assert client.get('/api/v1/entities/alpha/accounts').status_code == 403
        replay = client.get('/api/v1/auth/callback', params={'code': 'synthetic-code', 'state': transaction.state}, follow_redirects=False)
        assert replay.headers['location'].endswith('login_failed')
        headers = {'origin': auth.settings.public_origin, 'x-csrf-token': session['csrf_token']}
        assert client.post('/api/v1/auth/activity', headers=headers).status_code == 204
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
        assert client.get('/api/v1/session').status_code == 401
        factory.assert_not_called()


@pytest.mark.parametrize('origin', ['https://named.example.test', 'HTTPS://named.example.test'])
def test_hosted_cookie_attributes_and_injected_fixture_rejection(origin):
    from tabula_rasa.http.context import TrustedDevelopmentContext
    from starlette.responses import Response
    settings = HttpSettings('staging', origin, access_mode='named_user')
    auth = NamedIdentity(settings, Mock(), Mock())
    response = Response()
    auth.set_cookie(response, auth.session_cookie, 'synthetic', 43200)
    cookie = response.headers['set-cookie']
    assert cookie.startswith('__Host-tabula_session=') and 'Secure' in cookie and 'HttpOnly' in cookie
    assert 'Path=/' in cookie and 'SameSite=lax' in cookie and 'Domain=' not in cookie
    for values in ({'trusted_entity_id': 'alpha'}, {'alpha_username': 'operator'}, {'alpha_password_hash': 'secret'}):
        with pytest.raises(ValueError):
            HttpSettings('staging', 'https://named.example.test', access_mode='named_user', **values)
    with pytest.raises(ValueError):
        HttpSettings('development', 'http://public.example.test', access_mode='named_user')
    synthetic = TrustedDevelopmentContext('alpha', 'csrf')
    runtime = Mock()
    runtime.identity = None
    runtime.resolve_context = lambda request: synthetic.context
    with TestClient(create_app(settings=settings, runtime_factory=lambda _: runtime), base_url=settings.public_origin) as client:
        assert client.get('/api/v1/session').status_code == 403
        assert client.get('/api/v1/entities/alpha/accounts').status_code == 403
        runtime.services.assert_not_called()


def test_read_only_identity_management_scope_denial_and_outage_logout(database):
    repo, alice, bob, a, _ = setup(database)
    repo.set_membership(a, bob.id, 'owner')
    repo.set_membership(a, alice.id, 'read_only')
    with database.transaction() as connection:
        entity(connection, 'alpha-extra')
    repo.bind_entity(a, 'alpha-extra')
    client, auth, factory = client_for(database)
    raw, session = auth.sessions.issue(verified())
    with client:
        client.cookies.set(auth.session_cookie, raw, domain='127.0.0.1', path='/')
        client.cookies.set(auth.csrf_cookie, session.csrf_token, domain='127.0.0.1', path='/')
        info = client.get('/api/v1/session').json()
        assert info['entity']['id'] == 'alpha' and info['capabilities'] == ['bookkeeping:read']
        headers = {'origin': auth.settings.public_origin, 'x-csrf-token': info['csrf_token']}
        assert client.post('/api/v1/session/entity', json={'entity_id': 'beta'}, headers=headers).status_code == 403
        selected = client.post('/api/v1/session/entity', json={'entity_id': 'alpha-extra'}, headers=headers)
        assert selected.status_code == 200 and selected.json()['entity']['id'] == 'alpha-extra'
        assert selected.json()['capabilities'] == ['bookkeeping:read']
        assert client.post('/api/v1/auth/logout', headers={**headers, 'origin': 'https://evil.test'}).status_code == 403
        auth.sessions.revoke = Mock(side_effect=IdentityError('unavailable'))
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 503
        assert auth.session_cookie not in client.cookies
        assert auth.sessions.validate(raw).user_id == alice.id  # No false server-revocation success.
        factory.assert_not_called()


@pytest.mark.parametrize('code,status', [('unauthorized', 401), ('unavailable', 503)])
def test_middleware_identity_denial_uses_cookie_and_event_handler(code, status, caplog):
    import json
    import logging

    settings = HttpSettings('test', 'http://127.0.0.1', access_mode='named_user')
    auth = NamedIdentity(settings, Mock(), Mock())
    runtime = Mock()
    runtime.identity = auth
    runtime.resolve_context.side_effect = IdentityError(code)
    app = create_app(settings=settings, runtime_factory=lambda _: runtime)
    with TestClient(app, base_url=settings.public_origin) as client:
        client.cookies.set(auth.session_cookie, 'synthetic-session', domain='127.0.0.1', path='/')
        client.cookies.set(auth.csrf_cookie, 'synthetic-csrf', domain='127.0.0.1', path='/')
        client.cookies.set(auth.login_cookie, 'synthetic-login', domain='127.0.0.1', path='/')
        with caplog.at_level(logging.INFO, logger='tabula_rasa.http'):
            response = client.get('/api/docs')
        assert response.status_code == status
        assert (auth.session_cookie in client.cookies) == (code == 'unavailable')
        assert (auth.csrf_cookie in client.cookies) == (code == 'unavailable')
        assert auth.login_cookie in client.cookies
        event = next(json.loads(record.message) for record in caplog.records
                     if record.name == 'tabula_rasa.http')
        assert event['security_event'] == 'identity_denied'
        assert 'synthetic-session' not in caplog.text
        runtime.services.assert_not_called()
