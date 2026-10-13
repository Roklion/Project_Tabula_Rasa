"""Existing file imports in the compiled browser, with real scoped persistence."""

from unittest.mock import patch

import pytest
from playwright.sync_api import expect, sync_playwright

from tabula_rasa.application.imports import TransactionImportService
from tabula_rasa.errors import StorageError
from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.browser_quality_support import assert_accessible
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_browser_baselines import document_store as document_store
from tests.postgres.test_http_baselines import commercial as commercial, snapshot
from tests.postgres.test_import_repository import csv as transaction_csv, qb
from tests.test_transaction_import_files import csv_bytes, general_ledger_bytes


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


def select_file(page, label, content, name='transactions.csv'):
    page.get_by_label(label, exact=True).set_input_files(
        {'name': name, 'mimeType': 'application/octet-stream', 'buffer': content})


@pytest.mark.parametrize('width', [1440, 390])
def test_transaction_import_staging_diagnostics_duplicates_transfer_and_two_entities(database, commercial, commercial_server, width):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/data')
            before = snapshot(database)
            select_file(page, 'Transaction CSV file', csv_bytes([transaction_csv()]))
            expect(page.get_by_role('table').filter(has_text='Tabula Rasa source rows')).to_be_visible()
            assert snapshot(database) == before
            assert_accessible(page)
            page.get_by_role('button', name='Import rows', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Imported 1 transactions.')).to_be_visible()
            select_file(page, 'QuickBooks export', general_ledger_bytes(broken=True), 'General_ledger.xlsx')
            expect(page.get_by_role('alert').filter(has_text='Some QuickBooks rows could not be converted')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated rows', exact=True)).to_be_disabled()
            assert len(alpha.transactions.list()) == 2
            source = csv_bytes([qb(Num='QB-1'), qb(Num='QB-1'),
                qb(**{'Transaction Type': 'Transfer', 'Split': 'bank', 'Num': 'T-1', 'Name': '', 'Amount': '5'})])
            select_file(page, 'QuickBooks export', source)
            section = page.get_by_role('region', name='Import QuickBooks transactions', exact=True)
            expect(section.get_by_text('Already imported or repeated rows will be skipped: 3.')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated rows', exact=True)).to_be_enabled()
            assert len(alpha.transactions.list()) == 2 and not beta.transactions.list()
            page.get_by_role('button', name='Import validated rows', exact=True).click()
            expect(section.get_by_role('status')).to_contain_text('Imported 2 transactions.')
            assert len(alpha.transactions.list()) == 4
            select_file(page, 'QuickBooks export', source)
            expect(section.get_by_text('Already imported or repeated rows will be skipped: 2, 3, 4.')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated rows', exact=True)).to_be_disabled()
            page.get_by_label('Select business', exact=True).select_option('beta')
            page.get_by_role('button', name='Discard draft and switch', exact=True).click()
            expect(page.get_by_label('QuickBooks export', exact=True)).to_have_value('')
            select_file(page, 'QuickBooks export', source)
            expect(page.get_by_role('button', name='Import validated rows', exact=True)).to_be_enabled()
            page.get_by_role('button', name='Import validated rows', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Imported 2 transactions.')).to_be_visible()
            assert len(alpha.transactions.list()) == 4 and len(beta.transactions.list()) == 2
            assert_accessible(page)
        finally:
            browser.close()


def test_uncertain_csv_import_keeps_file_and_requires_explicit_review_before_replay(commercial, commercial_server):
    alpha, _, _, _ = commercial
    original_import = TransactionImportService.import_csv

    def lost_response(service, rows):
        original_import(service, rows)
        raise StorageError('Synthetic lost response after commit')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(commercial_server + '/data')
            select_file(page, 'Transaction CSV file', csv_bytes([transaction_csv()]))
            expect(page.get_by_role('button', name='Import rows', exact=True)).to_be_enabled()
            with patch.object(TransactionImportService, 'import_csv', lost_response):
                page.get_by_role('button', name='Import rows', exact=True).click()
                expect(page.get_by_role('alert').filter(has_text='Import confirmation is unavailable')).to_be_visible()
            expect(page.get_by_role('button', name='Import rows', exact=True)).to_be_disabled()
            assert len(alpha.transactions.list()) == 2
            page.get_by_role('button', name='Review this file again', exact=True).click()
            expect(page.get_by_role('button', name='Import rows', exact=True)).to_be_enabled()
            page.get_by_role('button', name='Import rows', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='No new transactions were imported')).to_be_visible()
            assert len(alpha.transactions.list()) == 2
        finally:
            browser.close()
