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
from tests.test_application_documents import FakeDocumentStore


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
    stores = {scope: FakeDocumentStore() for scope in ('alpha', 'beta')}
    runtime = PostgresRuntime(database, auth, identity=auth,
        service_factory=lambda context: create_postgres_services(database, context.entity_id,
            document_store=stores[context.entity_id], document_store_kind='fake'))
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
            with second.expect_response(lambda response: response.request.method == 'POST'
                                        and response.url.endswith('/auth/logout')) as logged_out:
                second.get_by_role('button', name='Sign out', exact=True).click()
            assert logged_out.value.status == 204
            expect(second.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            expect(peer.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            peer.reload()
            expect(peer.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_named_transaction_receipt_logout_then_other_user_has_no_residual_data(named_server, width):
    origin, repo, alice, _, _, b, claims, info = named_server
    # An overlapping membership lets Alice explicitly select another workspace;
    # Bob still cannot read Alice's original workspace.
    repo.set_membership(b, alice.id, 'read_only')
    from tests.postgres._support import account, category
    with repo.database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            account(connection, scope, 'cash')
            category(connection, scope, 'office', kind='Expense')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            # Installed in every document before app code, including Alice's
            # original receipt document if Back restores it from the BFCache.
            context.add_init_script("""(() => {
                const privateText = text => ['Alice private transaction', 'alice-private.pdf']
                    .some(value => (text || '').includes(value));
                const record = records => {
                    if (sessionStorage.getItem('security_probe_active') !== '1') return;
                    if (privateText(document.body?.textContent) || records.some(change =>
                        [...change.addedNodes, ...change.removedNodes].some(node => privateText(node.textContent))))
                        sessionStorage.setItem('security_probe_exposure', '1');
                };
                addEventListener('pageshow', () => record([]));
                new MutationObserver(record).observe(document, {subtree: true, childList: true, characterData: true});
            })();""")
            configure_login(context, origin, claims)
            page = context.new_page()
            page.goto(origin)
            page.get_by_role('link', name='Sign in', exact=True).click()
            expect(page.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            selector = page.get_by_label('Select business')
            if selector.input_value() != 'alpha':
                selector.select_option('alpha')
                page.get_by_role('button', name='Discard draft and switch').click()
                expect(page.get_by_text('Role: owner', exact=True)).to_be_visible()
            page.get_by_label('Select business').select_option('beta')
            page.get_by_role('button', name='Discard draft and switch').click()
            expect(page.get_by_text('Role: read only', exact=True)).to_be_visible()
            page.get_by_label('Select business').select_option('alpha')
            page.get_by_role('button', name='Discard draft and switch').click()
            expect(page.get_by_text('Role: owner', exact=True)).to_be_visible()
            page.goto(origin + '/transactions/new')
            page.get_by_label('Date', exact=True).fill('2026-10-06')
            page.get_by_label('Amount', exact=True).fill('19.25')
            page.get_by_label('From account', exact=True).select_option('cash')
            page.get_by_label('Category', exact=True).select_option('office')
            page.get_by_label('Description / memo', exact=True).fill('Alice private transaction')
            with page.expect_response(lambda response: response.request.method == 'POST'
                                      and response.url.endswith('/transactions')) as created:
                page.get_by_role('button', name='Save transaction', exact=True).click()
            assert created.value.status == 201
            record = created.value.json()['id']
            page.goto(origin + '/transactions/' + record + '/receipts')
            page.get_by_label('Receipt files').set_input_files({
                'name': 'alice-private.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF synthetic Alice',
            })
            page.get_by_role('button', name='Attach selected receipts').click()
            expect(page.get_by_role('status').filter(has_text='1 receipt attached.')).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role('link', name='Download alice-private.pdf', exact=True).click()
            assert Path(download.value.path()).read_bytes() == b'%PDF synthetic Alice'
            linked = context.request.get(origin + '/api/v1/entities/alpha/transactions/' + record + '/receipts').json()['items']
            document = linked[0]['id']
            receipt_url = page.url
            receipt_history_length = page.evaluate('history.length')
            previous = context.request.get(origin + '/api/v1/session').json()
            with page.expect_response(lambda response: response.request.method == 'POST'
                                      and response.url.endswith('/auth/logout')) as logged_out:
                page.get_by_role('button', name='Sign out', exact=True).click()
            assert logged_out.value.status == 204
            expect(page.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            expect(page.get_by_text('alice-private.pdf', exact=False)).to_have_count(0)
            claims['sub'] = info['sub'] = 'bob'
            page.get_by_role('link', name='Sign in', exact=True).click()
            expect(page.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            current = context.request.get(origin + '/api/v1/session').json()
            assert current['actor_id'] != previous['actor_id']
            assert current['cache_scope'] != previous['cache_scope']
            assert current['entity']['id'] == 'beta'
            page.evaluate("sessionStorage.setItem('security_probe_active', '1')")
            for path in ('transactions', 'transactions/' + record + '/receipts', 'documents/' + document + '/content'):
                assert context.request.get(origin + '/api/v1/entities/alpha/' + path).status == 403
            page.goto(origin + '/transactions')
            expect(page.get_by_role('heading', name='No matching entries', exact=True)).to_be_visible()
            expect(page.get_by_text('Alice private transaction', exact=True)).to_have_count(0)
            # Traverse every entry added by Bob's login and ledger navigation,
            # including the actual receipt entry visited while Alice was signed in.
            history_steps = page.evaluate('history.length') - receipt_history_length
            assert history_steps > 0
            for _ in range(history_steps):
                page.go_back(wait_until='networkidle')
                assert page.evaluate("sessionStorage.getItem('security_probe_exposure')") is None
                expect(page.get_by_text('Alice private transaction', exact=True)).to_have_count(0)
                expect(page.get_by_text('alice-private.pdf', exact=False)).to_have_count(0)
            expect(page).to_have_url(receipt_url)
            for storage in ('localStorage', 'sessionStorage'):
                stored = page.evaluate(f'JSON.stringify(Object.entries({storage}))')
                assert all(value not in stored for value in ('Alice private transaction', 'alice-private.pdf', document))
        finally:
            browser.close()
