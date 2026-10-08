"""Compiled React -> production HTTP handlers -> real synthetic PostgreSQL."""

import os
from pathlib import Path
import socket
from threading import Thread
from time import monotonic, sleep

from playwright.sync_api import expect, sync_playwright
import pytest
import uvicorn

from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres.test_http_baselines import commercial as commercial, loaded, snapshot

DIST = Path(__file__).resolve().parents[2] / 'web' / 'dist'


@pytest.fixture
def commercial_server(database, commercial):
    if not (DIST / 'index.html').is_file():
        if os.environ.get('TABULA_RASA_REQUIRE_BROWSER_TESTS') == '1':
            pytest.fail('Build web before running required native browser tests.')
        pytest.skip('Build web to run native browser baseline tests.')
    context = RequestContext('actor', 'org', 'alpha', frozenset({'bookkeeping:read', 'bookkeeping:write'}), 'browser-scope', 'csrf')
    runtime = PostgresRuntime(database, lambda request: context,
        service_factory=lambda context: create_postgres_services(database, context.entity_id))
    runtime.close = lambda: None  # The synthetic DB fixture owns this pool.
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
    app = create_app(settings=HttpSettings('test', origin), runtime_factory=lambda settings: runtime, static_dir=DIST)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='critical'))
    thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert server.started, 'Synthetic HTTP server did not start.'
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), 'Synthetic HTTP server did not stop.'


def edit_label(resource, row):
    if 'name' in row:
        return 'Edit ' + row['name']
    if resource == 'transactions':
        return f"Edit {row['txn_date']} · {row['description'] or row['kind']} · {row['amount']}"
    if resource == 'journals':
        return f"Edit {row['txn_date']} · {row['description'] or 'Journal'}"
    return f"Edit {row['trip_date']} · {row['destination']} · {row['miles']} miles"


@pytest.mark.parametrize('resource,field', [
    ('accounts', 'Account name'), ('categories', 'Category name'), ('payees', 'Name'), ('tags', 'Name'),
    ('transactions', 'Description / memo'), ('journals', 'Description / memo'), ('mileage', 'Notes'),
])
def test_two_real_forms_keep_original_baseline_and_explicitly_review_conflicts(database, commercial, commercial_server, resource, field):
    _, _, clients, ids = commercial
    row = loaded(clients[0], resource, ids[resource])
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            if os.environ.get('TABULA_RASA_REQUIRE_BROWSER_TESTS') == '1':
                pytest.fail('Install Chromium for required native browser tests.')
            pytest.skip('Install Playwright Chromium for native browser tests.')
        browser = playwright.chromium.launch()
        try:
            a = browser.new_context(viewport={'width': 1440, 'height': 1000})
            b = browser.new_context(viewport={'width': 390, 'height': 844})
            first, second = a.new_page(), b.new_page()
            for page in (first, second):
                page.goto(commercial_server + '/' + resource)
                page.get_by_role('button', name=edit_label(resource, row), exact=True).click()
                expect(page.get_by_label(field, exact=True)).to_be_visible()
            # Drafts are independently loaded before either writer commits.
            second.get_by_label(field, exact=True).fill('Client B draft')
            first.get_by_label(field, exact=True).fill('Client A commit')
            with first.expect_response(lambda response: response.request.method == 'PATCH') as saved:
                first.get_by_role('button', name='Save changes', exact=True).click()
            assert saved.value.status == 200
            before = snapshot(database)
            with second.expect_response(lambda response: response.request.method == 'PATCH') as stale:
                second.get_by_role('button', name='Save changes', exact=True).click()
            assert stale.value.status == 409 and stale.value.json()['error']['code'] == 'stale'
            expect(second.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(second.get_by_label(field, exact=True)).to_have_value('Client B draft')
            original_token = stale.value.request.post_data_json['baseline']
            assert original_token == row['baseline']
            remove_label = 'Deactivate' if resource == 'accounts' else 'Delete'
            second.get_by_role('button', name=remove_label, exact=True).click()
            with second.expect_response(lambda response: response.request.method == ('POST' if resource == 'accounts' else 'DELETE')) as deleted:
                second.get_by_role('button', name='Confirm ' + remove_label.lower(), exact=True).click()
            assert deleted.value.status == 409 and deleted.value.json()['error']['code'] == 'stale'
            assert deleted.value.request.post_data_json['baseline'] == original_token
            body = dict(stale.value.request.post_data_json)
            del body['baseline']
            missing = b.request.patch(commercial_server + '/api/v1/entities/alpha/' + resource + '/' + ids[resource],
                headers={'Origin': commercial_server, 'X-CSRF-Token': 'csrf'}, data=body)
            assert missing.status == 422 and missing.json()['error']['code'] == 'baseline_required'
            assert snapshot(database) == before
            second.get_by_role('button', name='Review latest record', exact=True).click()
            expect(second.get_by_role('alertdialog', name='Reload record')).to_be_visible()
            expect(second.get_by_label(field, exact=True)).to_have_value('Client B draft')
            second.get_by_role('button', name='Discard draft and reload', exact=True).click()
            expect(second.get_by_label(field, exact=True)).to_have_value('Client A commit')
            expect(second.get_by_role('alert')).to_have_count(0)
            second.get_by_label(field, exact=True).fill('Client B reviewed')
            with second.expect_response(lambda response: response.request.method == 'PATCH') as reviewed:
                second.get_by_role('button', name='Save changes', exact=True).click()
            assert reviewed.value.status == 200
            assert reviewed.value.request.post_data_json['baseline'] != original_token
            expect(second.get_by_role('status').filter(has_text='Changes saved.')).to_be_visible()
            assert second.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            if resource == 'transactions':
                second.get_by_label(field, exact=True).fill('Unsaved navigation draft')
                second.get_by_role('link', name='Journals', exact=True).click()
                expect(second.get_by_role('alertdialog', name='Unsaved changes')).to_be_visible()
                second.get_by_role('button', name='Keep editing', exact=True).click()
                expect(second.get_by_label(field, exact=True)).to_have_value('Unsaved navigation draft')
                second.get_by_role('link', name='Journals', exact=True).click()
                second.get_by_role('button', name='Discard draft and leave', exact=True).click()
                second.get_by_role('button', name='Edit 2026-10-05 · Loaded', exact=True).click()
                expect(second.get_by_label(field, exact=True)).to_have_value('Loaded')
        finally:
            browser.close()


@pytest.mark.parametrize('resource', ['payees', 'tags'])
def test_real_merge_form_keeps_target_and_source_baselines(database, commercial, commercial_server, resource):
    alpha, _, clients, ids = commercial
    service = getattr(alpha, resource)
    service.create('Merge target')
    service.create('Second source')
    original = loaded(clients[0], resource, ids[resource])
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.fail('Install Chromium for native merge form validation.')
        browser = playwright.chromium.launch()
        try:
            first, second = browser.new_context().new_page(), browser.new_context().new_page()
            first.goto(commercial_server + '/' + resource)
            first.get_by_role('button', name='Edit ' + original['name'], exact=True).click()
            second.goto(commercial_server + '/' + resource + '/merge')
            second.get_by_role('button', name='Merge ' + resource, exact=True).click()
            second.get_by_label('Keep this record').select_option(label='Merge target')
            second.get_by_label(original['name'], exact=True).check()
            second.get_by_label('Second source', exact=True).check()
            first.get_by_label('Name', exact=True).fill('Other committed source')
            first.get_by_role('button', name='Save changes', exact=True).click()
            expect(first.get_by_role('status').filter(has_text='Changes saved.')).to_be_visible()
            before = snapshot(database)
            with second.expect_response(lambda response: response.request.method == 'POST') as stale:
                second.get_by_role('button', name='Confirm merge', exact=True).click()
            assert stale.value.status == 409 and stale.value.json()['error']['code'] == 'stale'
            assert stale.value.request.post_data_json['baselines'][original['id']] == original['baseline']
            expect(second.get_by_label(original['name'], exact=True)).to_be_checked()
            assert snapshot(database) == before
            second.get_by_role('button', name='Review latest record', exact=True).click()
            second.get_by_role('button', name='Discard draft and reload', exact=True).click()
            expect(second.get_by_label('Other committed source', exact=True)).not_to_be_checked()
            second.get_by_label('Keep this record').select_option(label='Merge target')
            second.get_by_label('Other committed source', exact=True).check()
            second.get_by_label('Second source', exact=True).check()
            with second.expect_response(lambda response: response.request.method == 'POST') as merged:
                second.get_by_role('button', name='Confirm merge', exact=True).click()
            assert merged.value.status == 200 and merged.value.json()['count'] == '2'
            assert merged.value.request.post_data_json['baselines'][original['id']] != original['baseline']
            expect(second.get_by_role('status').filter(has_text='Records merged.')).to_be_visible()
            assert len(service.list()) == 1
        finally:
            browser.close()


@pytest.mark.parametrize('kind,category', [('Expense', 'office'), ('Income', 'sales'), ('Transfer', '')])
def test_real_transaction_editor_switches_kind_without_hidden_references(commercial, commercial_server, kind, category):
    from tests.postgres.core_support import expense

    alpha, _, clients, _ = commercial
    initial_kind = 'Expense' if kind == 'Transfer' else 'Transfer'
    row = alpha.transactions.create(transaction_id='switch-kind', **expense(kind=initial_kind,
        category_id='office' if initial_kind == 'Expense' else '', description='Kind switch',
        to_account_id='bank' if initial_kind == 'Transfer' else ''))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(commercial_server + '/transactions')
            page.get_by_role('button', name=edit_label('transactions', row), exact=True).click()
            page.get_by_label('Type', exact=True).select_option(kind)
            if category:
                page.get_by_label('Category', exact=True).select_option(category)
            else:
                page.get_by_label('To account', exact=True).select_option('bank')
            with page.expect_response(lambda response: response.request.method == 'PATCH') as saved:
                page.get_by_role('button', name='Save changes', exact=True).click()
            assert saved.value.status == 200
            body = saved.value.request.post_data_json
            assert body['baseline'] == row['baseline']
            assert body['changes']['category_id'] == category
            assert body['changes']['to_account_id'] == ('bank' if kind == 'Transfer' else '')
            actual = loaded(clients[0], 'transactions', row['id'])
            assert actual['kind'] == kind and actual['category_id'] == category
            assert actual['to_account_id'] == ('bank' if kind == 'Transfer' else '')
        finally:
            browser.close()
