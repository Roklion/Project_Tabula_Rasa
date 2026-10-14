"""Ordinary ledger copy and complete selected mutations in the real browser."""

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.postgres.browser_quality_support import assert_accessible
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_browser_baselines import browser_resolver as browser_resolver
from tests.postgres.test_browser_baselines import document_store as document_store
from tests.postgres.test_http_baselines import commercial as commercial, snapshot


@pytest.mark.parametrize('width', [1440, 390])
def test_ordinary_copy_then_confirmed_bulk_update_delete_and_protected_journal(database, commercial, commercial_server, width):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/transactions')
            page.get_by_role('button', name='Bulk actions', exact=True).click()
            expense = page.get_by_role('checkbox', name='Select 2026-10-05 · Expense · 12.50', exact=True)
            journal = page.get_by_role('checkbox', name='Select 2026-10-05 · Loaded · 12.50', exact=True)
            expense.check()
            journal.check()
            expect(page.get_by_role('button', name='Copy transaction', exact=True)).to_be_disabled()
            expect(page.get_by_role('button', name='Permanently delete selected', exact=True)).to_be_disabled()
            journal.uncheck()
            page.get_by_role('button', name='Copy transaction', exact=True).click()
            expect(page.get_by_label('Description / memo', exact=True)).to_have_value('Copy From expense')
            before = snapshot(database)
            page.get_by_role('button', name='Back to records', exact=True).click()
            expect(page.get_by_role('alertdialog', name='Discard draft', exact=True)).to_be_visible()
            page.get_by_role('button', name='Keep editing', exact=True).click()
            assert snapshot(database) == before
            original = alpha.transactions.list()[0]
            changed = alpha.transactions.update('expense', expected=original, amount='30.00')
            page.get_by_label('Amount', exact=True).fill('19.50')
            page.get_by_label('Description / memo', exact=True).fill('Browser copy')
            page.get_by_role('button', name='Save transaction copy', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Transaction copied.')).to_be_visible()
            expect(page.get_by_role('button', name='Save transaction copy', exact=True)).to_have_count(0)
            copied = next(row for row in alpha.transactions.list() if row['id'] != 'expense')
            assert copied['amount'] == '19.50' and copied['description'] == 'Browser copy. Copy From expense'
            assert copied['receipt_references'] == [] and copied['id'] != original['id']
            assert next(row for row in alpha.transactions.list() if row['id'] == 'expense') == changed
            assert not beta.transactions.list()
            page.get_by_role('button', name='Back to records', exact=True).click()
            page.get_by_role('button', name='Bulk actions', exact=True).click()
            selection = page.get_by_role('checkbox', name='Select 2026-10-05 · Browser copy. Copy From expense · 19.50', exact=True)
            selection.check()
            page.get_by_role('checkbox', name='Apply Payee to all selected', exact=True).check()
            page.get_by_label('Payee / customer', exact=True).select_option('')
            page.get_by_role('button', name='Review selected changes', exact=True).click()
            before = snapshot(database)
            page.get_by_role('button', name='Keep reviewing', exact=True).click()
            assert snapshot(database) == before
            page.get_by_role('button', name='Review selected changes', exact=True).click()
            page.get_by_role('button', name='Confirm selected changes', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='1 transaction(s) updated.')).to_be_visible()
            assert next(row for row in alpha.transactions.list() if row['id'] == copied['id'])['payee_id'] == ''
            page.get_by_role('button', name='Bulk actions', exact=True).click()
            selection.check()
            page.get_by_role('button', name='Permanently delete selected', exact=True).click()
            confirm = page.get_by_role('button', name='Confirm permanent deletion', exact=True)
            expect(confirm).to_be_disabled()
            page.get_by_role('checkbox', name='I understand that this cannot be undone.', exact=True).check()
            confirm.click()
            expect(page.get_by_role('status').filter(has_text='1 transaction(s) permanently deleted.')).to_be_visible()
            assert len(alpha.transactions.list()) == 1 and len(alpha.journals.list()) == 1
            assert_accessible(page)
        finally:
            browser.close()
