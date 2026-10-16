"""Compiled browser + signed fake OIDC + disposable PostgreSQL; no hosted claim."""

from pathlib import Path
import json
import socket
from threading import Thread
from time import monotonic, sleep
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright
import pytest
import uvicorn

from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.identity import NamedIdentity
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tests.postgres.test_identity import setup
from tests.postgres.browser_quality_support import assert_accessible
from tests.test_oidc import oidc as oidc


@pytest.fixture
def named_server(database, oidc):
    dist = Path(__file__).resolve().parents[2] / 'web/dist'
    if not (dist / 'index.html').is_file():
        import os
        if os.environ.get('TABULA_RASA_REQUIRE_BROWSER_TESTS') == '1':
            pytest.fail('Build web before required named-user browser tests.')
        pytest.skip('Build web to run named-user browser tests.')
    repo, alice, bob, a, b = setup(database)
    provider, _, claims, info, _ = oidc
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    settings = HttpSettings('test', origin, access_mode='named_user')
    from dataclasses import replace
    provider.settings = replace(provider.settings, public_origin=origin)
    sessions = PostgresSessionRepository(database, 'test', provider.settings.configuration_hash)
    sessions.configure()
    auth = NamedIdentity(settings, sessions, provider)
    runtime = PostgresRuntime(database, auth, identity=auth,
        service_factory=lambda context: create_postgres_services(database, context.entity_id))
    runtime.close = lambda: None  # Pool owned by disposable fixture.
    app = create_app(settings=settings, runtime_factory=lambda _: runtime,
                     static_dir=dist)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='critical',
                                         timeout_keep_alive=1, timeout_graceful_shutdown=2))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(.01)
        assert server.started
        yield origin, repo, alice, bob, a, b, claims, info
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def configure_login(context, origin, claims):
    """Use signed fake OIDC, adapting only Playwright's external redirect hop."""
    def authorize(route):
        query = parse_qs(urlsplit(route.request.url).query)
        assert query['code_challenge_method'] == ['S256']
        claims['nonce'] = query['nonce'][0]
        route.fulfill(status=302, headers={'location': origin + '/api/v1/auth/callback?' + urlencode(
            {'state': query['state'][0], 'code': 'synthetic-code'})})
    def login_redirect(route):
        # Playwright routing cannot fake the later external hop of a
        # redirect chain. Split only that test hop into a new navigation;
        # assert the real server's 303/cookie response before adapting.
        response = route.fetch(max_redirects=0)
        assert response.status == 303
        target = response.headers['location']
        assert target.startswith('https://id.example.test/authorize?')
        headers = {key: value for key, value in response.headers.items()
                   if key not in {'location', 'content-length', 'content-type'}}
        route.fulfill(status=200, headers=headers, content_type='text/html',
            body='<script>location.replace(' + json.dumps(target) + ')</script>')
    context.route('https://id.example.test/authorize**', authorize)
    context.route('**/api/v1/auth/login**', login_redirect)


@pytest.mark.parametrize('width', [1440, 390])
def test_named_sign_in_revocation_two_users_and_cross_tab_logout(named_server, width):
    origin, repo, alice, bob, a, _, claims, info = named_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            alice_browser = browser.new_context(viewport={'width': width, 'height': 1000})
            bob_browser = browser.new_context(viewport={'width': width, 'height': 1000})
            for context in (alice_browser, bob_browser):
                configure_login(context, origin, claims)
            first, second = alice_browser.new_page(), bob_browser.new_page()
            first.goto(origin)
            expect(first.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            assert_accessible(first)
            with first.expect_response(lambda response: '/api/v1/auth/login' in response.url) as begin:
                first.get_by_role('link', name='Sign in', exact=True).click()
            assert begin.value.status == 200  # Redirect adapter above asserts the native 303.
            expect(first.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            assert alice_browser.request.get(origin + '/api/v1/entities/beta/accounts').status == 403
            claims['sub'] = info['sub'] = 'bob'
            second.goto(origin)
            second.get_by_role('link', name='Sign in', exact=True).click()
            expect(second.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            assert bob_browser.request.get(origin + '/api/v1/session').json()['entity']['id'] == 'beta'
            repo.set_membership(a, bob.id, 'owner')
            repo.set_user_state(alice.id, 'disabled')
            first.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(first.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            assert bob_browser.request.get(origin + '/api/v1/session').status == 200
            peer = bob_browser.new_page()
            peer.goto(origin)
            expect(peer.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            second.get_by_role('button', name='Sign out', exact=True).click()
            expect(second.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            expect(peer.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            peer.reload()
            expect(peer.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
        finally:
            browser.close()
