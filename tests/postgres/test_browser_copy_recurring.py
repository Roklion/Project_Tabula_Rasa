"""Commercial existing-workflow ports through native PostgreSQL and compiled UI."""

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.postgres.browser_quality_support import assert_accessible
from tests.postgres.secondary_support import mixed
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_browser_baselines import document_store as document_store
from tests.postgres.test_browser_baselines import browser_resolver as browser_resolver
from tests.postgres.test_http_baselines import commercial as commercial, snapshot


@pytest.mark.parametrize('width', [1440, 390])
def test_browser_mixed_copy_snapshot_cancellation_failure_and_independent_save(database, commercial, commercial_server, width):
    alpha, beta, _, _ = commercial
    source = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(description='Original memo'))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 760 else 844})
            page.goto(commercial_server + '/mixed-use/source')
            page.get_by_role('link', name='Copy mixed-use expense', exact=True).click()
            expect(page.get_by_label('Description / memo', exact=True)).to_have_value('Original memo. Copy From source')
            expect(page.get_by_label('Total expense', exact=True)).to_have_value('100.00')
            before = snapshot(database)
            page.get_by_role('button', name='Back to records', exact=True).click()
            expect(page.get_by_role('alertdialog', name='Discard draft', exact=True)).to_be_visible()
            page.get_by_role('button', name='Keep editing', exact=True).click()
            assert snapshot(database) == before
            page.get_by_role('button', name='Back to records', exact=True).click()
            page.get_by_role('button', name='Discard draft and close', exact=True).click()
            expect(page.get_by_role('heading', name='Mixed-use expenses', exact=True)).to_be_visible()
            assert snapshot(database) == before
            page.goto(commercial_server + '/mixed-use/source/copy')
            expect(page.get_by_label('Total expense', exact=True)).to_have_value('100.00')
            changed = alpha.mixed_use.update('source', expected_source=source, description='Original changed', total_expense='200')
            page.get_by_label('Total expense', exact=True).fill('19.99')
            page.get_by_label('Business use %', exact=True).fill('50')
            page.get_by_label('Description / memo', exact=True).fill('Independent edited memo')
            requests = []

            def unavailable(route):
                requests.append(route.request.post_data_json)
                route.abort()

            page.route('**/api/v1/entities/alpha/mixed-use', unavailable)
            page.get_by_role('button', name='Save mixed-use copy', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(page.get_by_label('Total expense', exact=True)).to_have_value('19.99')
            assert len(requests) == 1 and len(alpha.mixed_use.list()) == 1
            page.unroute('**/api/v1/entities/alpha/mixed-use', unavailable)
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/mixed-use')) as saved:
                page.get_by_role('button', name='Save mixed-use copy', exact=True).click()
            assert saved.value.status == 201
            copied = saved.value.json()
            expect(page.get_by_role('status').filter(has_text='Mixed-use expense copied.')).to_be_visible()
            assert copied['id'] == requests[0]['source_id'] and copied['linked_transaction_id'] == requests[0]['linked_transaction_id']
            assert copied['allocated_amount'] == '10.00' and copied['description'] == 'Independent edited memo. Copy From source'
            assert alpha.mixed_use.get('source') == changed and not beta.mixed_use.sources()
            assert_accessible(page)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()


def test_browser_conversion_fresh_baseline_stale_draft_confirmed_cancel_and_success(database, commercial, commercial_server):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(commercial_server + '/transactions/expense/recurring')
            expect(page.get_by_label('Amount', exact=True)).to_have_value('12.50')
            expect(page.get_by_label('Repeat every', exact=True)).to_have_value('1')
            expect(page.get_by_label('Repeat unit', exact=True)).to_have_value('month')
            original = next(row for row in alpha.transactions.list() if row['id'] == 'expense')
            changed = alpha.transactions.update('expense', expected=original, amount='30')
            page.get_by_label('Amount', exact=True).fill('25.00')
            page.get_by_label('Schedule name', exact=True).fill('Converted browser expense')
            before = snapshot(database)
            page.get_by_role('button', name='Save changes', exact=True).click()
            page.get_by_role('button', name='Keep editing', exact=True).click()
            assert snapshot(database) == before
            page.get_by_role('button', name='Save changes', exact=True).click()
            page.get_by_role('button', name='Confirm recurring conversion', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(page.get_by_label('Amount', exact=True)).to_have_value('25.00')
            assert alpha.transactions.list()[0] == changed and not alpha.recurring.list()
            page.get_by_role('button', name='Review latest record', exact=True).click()
            page.get_by_role('button', name='Discard draft and reload', exact=True).click()
            expect(page.get_by_label('Amount', exact=True)).to_have_value('30.00')
            page.get_by_label('Amount', exact=True).fill('25.00')
            page.get_by_label('Date', exact=True).fill('2026-01-31')
            page.get_by_role('button', name='Save changes', exact=True).click()
            page.get_by_role('button', name='Confirm recurring conversion', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Expense made recurring.')).to_be_visible()
            assert len(alpha.recurring.list()) == 1 and alpha.transactions.list()[0]['amount'] == '25.00'
            assert alpha.transactions.list()[0]['id'] == 'expense' and not beta.recurring.list()
            page.get_by_role('link', name='View recurring schedule', exact=True).click()
            expect(page.get_by_role('cell', name='initial', exact=True)).to_be_visible()
            assert_accessible(page)
        finally:
            browser.close()


def test_browser_conversion_uncertain_committed_response_preserves_draft_and_stable_schedule(commercial, commercial_server):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(commercial_server + '/transactions/expense/recurring')
            page.get_by_label('Amount', exact=True).fill('25.00')
            page.get_by_label('Schedule name', exact=True).fill('Uncertain converted expense')
            page.get_by_label('Payee', exact=True).select_option('')
            page.get_by_label('New payee name (optional)', exact=True).fill('Inline browser vendor')
            page.get_by_label('New tag name (optional)', exact=True).fill('Inline browser tag')
            requests = []

            def committed_unavailable(route):
                requests.append(route.request.post_data_json)
                response = route.fetch()
                assert response.status == 201
                route.abort()

            page.route('**/api/v1/entities/alpha/recurring/from-transaction/expense', committed_unavailable)
            page.get_by_role('button', name='Save changes', exact=True).click()
            page.get_by_role('button', name='Confirm recurring conversion', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(page.get_by_label('Amount', exact=True)).to_have_value('25.00')
            expect(page.get_by_role('status').filter(has_text='Expense made recurring.')).to_have_count(0)
            assert len(requests) == 1 and len(alpha.recurring.list()) == 1
            page.unroute('**/api/v1/entities/alpha/recurring/from-transaction/expense', committed_unavailable)
            page.get_by_role('button', name='Save changes', exact=True).click()
            page.get_by_role('button', name='Confirm recurring conversion', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Expense made recurring.')).to_be_visible()
            assert alpha.recurring.list()[0]['id'] == requests[0]['schedule_id']
            assert len(alpha.transactions.list()) == len(alpha.recurring.list()) == 1 and not beta.recurring.list()
        finally:
            browser.close()
