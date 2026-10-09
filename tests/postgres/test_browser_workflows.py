"""Core alpha interactions against the compiled browser and native PostgreSQL."""

import os
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright
import pytest

from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_browser_baselines import document_store as document_store
from tests.postgres.test_http_baselines import commercial as commercial, snapshot


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


def capture(page, name):
    if target := os.environ.get('TABULA_RASA_WORKFLOW_SCREENSHOTS'):
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=directory / (name + '.png'), full_page=True)


@pytest.mark.parametrize('width', [1440, 390])
def test_browser_reference_setup_and_entry_lifecycle(database, commercial, commercial_server, width):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 760 else 844})
            for resource, field, name in [('accounts', 'Account name', 'Browser bank'), ('categories', 'Category name', 'Browser expense'),
                                          ('payees', 'Name', 'Browser vendor'), ('tags', 'Name', 'Browser tag')]:
                page.goto(commercial_server + '/' + resource + '/new')
                page.get_by_label(field, exact=True).fill(name)
                page.get_by_role('button', name='Create ' + ('category' if resource == 'categories' else resource[:-1]), exact=True).click()
                expect(page.get_by_role('status').filter(has_text='Record created.')).to_be_visible()
                page.get_by_role('button', name='Back to records', exact=True).click()
                expect(page.get_by_role('button', name='Edit ' + name, exact=True)).to_be_visible()
            page.goto(commercial_server + '/transactions/new')
            page.get_by_label('Date', exact=True).fill('2026-10-06')
            page.get_by_label('Amount', exact=True).fill('19.25')
            page.get_by_label('From account', exact=True).select_option('cash')
            page.get_by_label('Category', exact=True).select_option('office')
            page.get_by_label('New payee name (optional)', exact=True).fill('Inline browser vendor')
            page.get_by_label('New tag name (optional)', exact=True).fill('Inline browser tag')
            page.get_by_label('Description / memo', exact=True).fill('Browser transaction')
            with page.expect_response(lambda response: response.request.method == 'POST' and '/transactions' in response.url) as created:
                page.get_by_role('button', name='Save transaction', exact=True).click()
            assert created.value.status == 201
            record = created.value.json()
            assert record['payee_id'] and record['tag_ids']
            expect(page.get_by_label('Amount', exact=True)).to_have_value('')
            page.get_by_role('button', name='Back to records', exact=True).click()
            page.get_by_role('button', name='Edit 2026-10-06 · Browser transaction · 19.25', exact=True).click()
            page.get_by_label('Amount', exact=True).fill('20.25')
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Changes saved.')).to_be_visible()
            page.get_by_role('button', name='Delete', exact=True).click()
            page.get_by_role('button', name='Confirm delete', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Record deleted.')).to_be_visible()
            assert not any(row['id'] == record['id'] for row in alpha.transactions.list(fresh=True))
            assert not beta.transactions.list()
            page.get_by_role('button', name='Back to records', exact=True).click()
            page.get_by_label('Type', exact=True).select_option('Journal')
            expect(page.get_by_role('cell', name='Multiple accounts · 2 postings', exact=True)).to_be_visible()
            page.get_by_label('Accounts', exact=True).select_option('category:office')
            expect(page.get_by_role('rowheader', name='↳ Posting', exact=True)).to_have_count(2)
            page.get_by_label('Accounts', exact=True).select_option('category:sales')
            expect(page.get_by_role('heading', name='No matching entries', exact=True)).to_be_visible()
            page.get_by_label('Accounts', exact=True).select_option([])
            page.get_by_label('Search transactions', exact=True).fill('Office')
            expect(page.get_by_role('rowheader', name='↳ Posting', exact=True)).to_have_count(2)
            page.get_by_label('Sort entries by', exact=True).select_option('Amount')
            page.get_by_label('Entry order', exact=True).select_option('Ascending')
            expect(page.get_by_role('rowheader', name='↳ Posting', exact=True)).to_have_count(2)
            expect(page.get_by_role('status').filter(has_text='1 matching entries')).to_be_visible()
            capture(page, 'ledger-' + str(width))
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.goto(commercial_server + '/reports')
            expect(page.get_by_role('heading', name='Profit and loss', exact=True)).to_be_visible()
            expect(page.get_by_role('definition').filter(has_text=re.compile(r'^25\.00$'))).to_be_visible()
            capture(page, 'reports-' + str(width))
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()


def test_browser_journal_balance_and_service_failure_preserve_draft(database, commercial, commercial_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(commercial_server + '/journals/new')
            expect(page.get_by_role('button', name='Save journal', exact=True)).to_be_disabled()
            page.get_by_label('Date', exact=True).fill('2026-10-06')
            page.get_by_label('Description / memo', exact=True).fill('Browser journal')
            page.get_by_label('Target', exact=True).nth(0).select_option('cash')
            page.get_by_label('Account or category', exact=True).nth(0).select_option('category')
            expect(page.get_by_label('Target', exact=True).nth(0)).to_have_value('')
            page.get_by_label('Target', exact=True).nth(0).select_option('office')
            page.get_by_label('Target', exact=True).nth(1).select_option('cash')
            page.get_by_label('Amount', exact=True).nth(0).fill('10.01')
            page.get_by_label('Amount', exact=True).nth(1).fill('10.00')
            expect(page.get_by_role('status').filter(has_text='Difference: 0.01')).to_be_visible()
            expect(page.get_by_role('button', name='Save journal', exact=True)).to_be_disabled()
            page.get_by_label('Amount', exact=True).nth(1).fill('10.01')
            expect(page.get_by_role('button', name='Save journal', exact=True)).to_be_enabled()
            capture(page, 'journal-390')
            commercial[0].accounts.deactivate('cash')
            before = snapshot(database)
            with page.expect_response(lambda response: response.request.method == 'POST') as rejected:
                page.get_by_role('button', name='Save journal', exact=True).click()
            assert rejected.value.status == 422
            assert snapshot(database) == before
            expect(page.get_by_label('Description / memo', exact=True)).to_have_value('Browser journal')
            expect(page.get_by_label('Amount', exact=True).nth(0)).to_have_value('10.01')
            commercial[0].accounts.update('cash', active=True)
            with page.expect_response(lambda response: response.request.method == 'POST') as saved:
                page.get_by_role('button', name='Save journal', exact=True).click()
            assert saved.value.status == 201
            assert saved.value.request.post_data_json['entry_id'] == rejected.value.request.post_data_json['entry_id']
            assert saved.value.request.post_data_json['postings'] == rejected.value.request.post_data_json['postings']
            expect(page.get_by_role('status').filter(has_text='Record created.')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()


def test_browser_entity_switch_discards_draft_and_isolates_clients(commercial, commercial_server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            first = browser.new_context().new_page()
            second = browser.new_context().new_page()
            first.goto(commercial_server + '/transactions/new')
            second.goto(commercial_server + '/transactions')
            first.get_by_label('Description / memo', exact=True).fill('Alpha private draft')
            first.get_by_label('Select business', exact=True).select_option('beta')
            expect(first.get_by_role('alertdialog', name='Switch business')).to_be_visible()
            first.get_by_role('button', name='Keep current business', exact=True).click()
            expect(first.get_by_label('Description / memo', exact=True)).to_have_value('Alpha private draft')
            first.get_by_label('Select business', exact=True).select_option('beta')
            first.get_by_role('button', name='Discard draft and switch', exact=True).click()
            expect(first.get_by_label('Select business', exact=True)).to_have_value('beta')
            expect(first.get_by_label('Description / memo', exact=True)).to_have_value('')
            assert first.request.get(commercial_server + '/api/v1/entities/alpha/transactions').status == 403
            assert first.request.get(commercial_server + '/api/v1/entities/beta/transactions').json()['items'] == []
            expect(second.get_by_label('Select business', exact=True)).to_have_value('alpha')
            expect(second.get_by_role('button', name='Edit 2026-10-05 · Expense · 12.50', exact=True)).to_be_visible()
        finally:
            browser.close()
