"""Signed provider responses, real one-shot storage and HTTP recovery; no hosted claim."""

import json
from datetime import timedelta
from time import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from tabula_rasa.application.identity import IdentityError
from tests.postgres.test_identity import verified
from tests.postgres.test_identity_http import client_for
from tests.test_oidc import oidc as oidc


@pytest.mark.parametrize('retained', [False, True])
def test_signed_login_and_stale_provider_recovery(database, oidc, retained, caplog, monkeypatch):
    monkeypatch.setenv('TABULA_RASA_TELEMETRY_SCOPE_KEY', 'synthetic-identity-telemetry-key-32-chars')
    caplog.set_level('INFO', logger='tabula_rasa.http')
    client, auth, factory = client_for(database)
    provider, _, claims, _, calls = oidc
    auth.provider = provider
    with client:
        start = client.get('/api/v1/auth/login', follow_redirects=False)
        query = parse_qs(urlsplit(start.headers['location']).query)
        assert query['prompt'] == ['login'] and query['max_age'] == ['0']
        original_state = query['state'][0]
        claims['nonce'] = query['nonce'][0]
        pending_cookie = client.cookies.get(auth.login_cookie)
        claims['auth_time'] = int(time()) - (600 if retained else 0)
        callback = client.get('/api/v1/auth/callback', params={
            'state': original_state, 'code': 'synthetic-private-code'}, follow_redirects=False)
        if retained:
            failure = parse_qs(urlsplit(callback.headers['location']).query)
            assert failure['category'] == ['login_freshness']
            assert failure['reference'] == [callback.headers['x-request-id']]
            assert client.get('/api/v1/session').status_code == 401
            assert auth.session_cookie not in client.cookies
            assert auth.login_cookie not in client.cookies and auth.login_reference_cookie not in client.cookies
            # Even restoring the consumed browser cookie cannot exchange again.
            client.cookies.set(auth.login_cookie, pending_cookie, domain='127.0.0.1', path='/')
            replay = client.get('/api/v1/auth/callback', params={
                'state': original_state, 'code': 'synthetic-private-code'}, follow_redirects=False)
            assert 'category=login_transaction' in replay.headers['location']
            assert sum(method == 'POST' for method, _, _ in calls) == 1
            restart = client.get('/api/v1/auth/login', follow_redirects=False)
            fresh_query = parse_qs(urlsplit(restart.headers['location']).query)
            assert fresh_query['state'] != query['state'] and fresh_query['nonce'] != query['nonce']
            assert fresh_query['code_challenge'] != query['code_challenge']
            assert fresh_query['prompt'] == ['login'] and fresh_query['max_age'] == ['0']
            claims.update(nonce=fresh_query['nonce'][0], auth_time=int(time()))
            callback = client.get('/api/v1/auth/callback', params={
                'state': fresh_query['state'][0], 'code': 'synthetic-fresh-code'}, follow_redirects=False)
        assert callback.headers['location'] == '/'
        assert callback.headers['cache-control'] == 'no-store'
        assert callback.headers['referrer-policy'] == 'no-referrer'
        assert client.get('/api/v1/session').json()['state'] == 'needs_setup'
        assert sum(method == 'POST' for method, _, _ in calls) == (2 if retained else 1)
        events = [json.loads(record.message) for record in caplog.records
                  if record.name == 'tabula_rasa.http' and '"http_request"' in record.message]
        started = next(event for event in events if event['security_event'] == 'login_started')
        completed = next(event for event in events if event['operation'] == 'complete_login')
        assert started['request_id'] == start.headers['x-request-id']
        assert started['login_ref'] and started['login_ref'] == completed['login_ref']
        assert all(event['release'] and event['request_id'] for event in events)
        if retained:
            assert completed['security_reason'] == 'login_freshness' and completed['outcome'] == 'failure'
        assert all(value not in caplog.text for value in (
            pending_cookie, original_state, claims['nonce'], 'synthetic-private-code',
            'synthetic-fresh-code', 'synthetic-access', 'synthetic@example.test',
            client.cookies.get(auth.session_cookie)))
        factory.assert_not_called()


@pytest.mark.parametrize('failure', ['provider', 'state', 'cookie', 'expired', 'session'])
def test_failed_callback_classification_and_deliberate_restart(database, failure, caplog):
    caplog.set_level('INFO', logger='tabula_rasa.http')
    client, auth, _ = client_for(database)
    auth.provider.authorization_url.return_value = 'https://id.example.test/authorize'
    auth.provider.verify.return_value = verified()
    original_issue, original_clock = auth.sessions.issue, auth.sessions.clock
    with client:
        client.get('/api/v1/auth/login', follow_redirects=False)
        transaction = auth.provider.authorization_url.call_args.args[0]
        params = {'state': transaction.state, 'code': 'private-code'}
        expected = 'login_transaction'
        if failure == 'provider':
            params.update(error='private-provider-error', error_description='private-provider-description')
            expected = 'provider_authorization'
        elif failure == 'state':
            params['state'] = 'private-wrong-state'
        elif failure == 'cookie':
            client.cookies.clear()
        elif failure == 'expired':
            now = original_clock()
            auth.sessions.clock = lambda: now + timedelta(minutes=6)
        else:
            auth.sessions.issue = Mock(side_effect=IdentityError('unavailable'))
            expected = 'session_issue'
        result = client.get('/api/v1/auth/callback', params=params, follow_redirects=False)
        assert 'category=' + expected in result.headers['location']
        assert auth.login_cookie not in client.cookies
        assert auth.session_cookie not in client.cookies
        assert all(value not in result.headers['location'] + caplog.text for value in (
            'private-code', 'private-provider-error', 'private-provider-description', 'private-wrong-state'))
        if failure != 'session':
            auth.provider.verify.assert_not_called()
        assert result.headers['cache-control'] == 'no-store'
        assert result.headers['referrer-policy'] == 'no-referrer'
        # No redirect straight to the provider or automatic second exchange.
        assert result.headers['location'].startswith('/signed-out?')
        auth.sessions.issue, auth.sessions.clock = original_issue, original_clock
        client.get('/api/v1/auth/login', follow_redirects=False)
        fresh_transaction = auth.provider.authorization_url.call_args.args[0]
        assert fresh_transaction.state != transaction.state
        recovered = client.get('/api/v1/auth/callback', params={
            'state': fresh_transaction.state, 'code': 'synthetic-recovery-code'}, follow_redirects=False)
        assert recovered.headers['location'] == '/'
        assert client.get('/api/v1/session').status_code == 200


@pytest.mark.parametrize('boundary', ['transaction', 'discovery'])
def test_login_start_outage_has_clean_recovery_page(database, boundary, caplog):
    caplog.set_level('INFO', logger='tabula_rasa.http')
    client, auth, _ = client_for(database)
    if boundary == 'transaction':
        auth.sessions.begin_login = Mock(side_effect=IdentityError('unavailable'))
    else:
        auth.provider.authorization_url.side_effect = IdentityError('unavailable')
    with client:
        result = client.get('/api/v1/auth/login', follow_redirects=False)
        query = parse_qs(urlsplit(result.headers['location']).query)
        assert query == dict(reason=['unavailable'], category=['login_start'],
                             reference=[result.headers['x-request-id']])
        assert result.headers['cache-control'] == 'no-store'
        assert result.headers['referrer-policy'] == 'no-referrer'
        assert auth.login_cookie not in client.cookies and auth.login_reference_cookie not in client.cookies
        assert auth.session_cookie not in client.cookies
        auth.provider.verify.assert_not_called()
        events = [json.loads(record.message) for record in caplog.records
                  if record.name == 'tabula_rasa.http' and '"http_request"' in record.message]
        assert events[-1]['security_reason'] == 'login_start'
        assert events[-1]['outcome'] == 'failure'
