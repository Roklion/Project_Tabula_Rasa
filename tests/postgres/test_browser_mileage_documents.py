"""Native browser vertical slices with PostgreSQL and a synthetic byte adapter."""

from pathlib import Path
from threading import Event
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import pytest

from tabula_rasa.application.documents import DocumentError
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_http_mileage_documents import commercial as commercial, document_store as document_store


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


@pytest.mark.parametrize('width', [1440, 390])
def test_mileage_capture_round_trip_filter_export_detail_and_delete(commercial, commercial_server, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/mileage')
            page.get_by_role('link', name='Add trip', exact=True).click()
            page.get_by_label('Trip date', exact=True).fill('2026-10-08')
            page.get_by_label('Business miles', exact=True).fill('12.4')
            page.get_by_label('Round trip', exact=True).check()
            expect(page.get_by_label('Return business miles')).to_have_value('12.4')
            page.get_by_label('Return business miles').fill('14.2')
            page.get_by_label('Starting location').fill('Office')
            page.get_by_label('Destination', exact=True).fill('Site')
            page.get_by_label('Business purpose').fill('Inspection')
            page.get_by_label('New tag name (optional)').fill('Inspection')
            page.get_by_role('button', name='Save mileage trip').click()
            expect(page.get_by_role('status').filter(has_text='Mileage saved: 2 trips.')).to_be_visible()
            page.get_by_role('link', name='View mileage log').click()
            page.get_by_label('From', exact=True).fill('2026-10-08')
            page.get_by_label('To', exact=True).fill('2026-10-08')
            page.get_by_label('Filter by tags').select_option(label='Inspection')
            expect(page.get_by_role('status').filter(has_text='Trips: 2 · Business miles: 26.6')).to_be_visible()
            with page.expect_download() as download:
                page.get_by_role('button', name='Download filtered mileage CSV').click()
            csv = Path(download.value.path()).read_text(encoding='utf-8')
            assert 'Inspection' in csv and '14.2' in csv and '12.4' in csv
            page.get_by_role('button', name='Edit 2026-10-08 · Site · 12.4 miles', exact=True).click()
            page.get_by_label('Notes', exact=True).fill('Reviewed')
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Changes saved.')).to_be_visible()
            page.get_by_role('button', name='Delete', exact=True).click()
            page.get_by_role('button', name='Confirm delete', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Record deleted.')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_receipt_upload_partial_link_retry_download_remove_and_recover(commercial, commercial_server, document_store, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/transactions')
            page.get_by_role('link', name='Receipts for 2026-10-05 · Expense · 12.50', exact=True).click()
            expect(page.get_by_role('heading', name='No receipts attached')).to_be_visible()
            page.get_by_label('Receipt files').set_input_files({'name': 'receipt.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF synthetic receipt'})
            with patch.object(PostgresReceiptRepository, 'link', side_effect=DocumentError('Synthetic link failure')):
                page.get_by_role('button', name='Attach selected receipts').click()
                expect(page.get_by_role('alert').filter(has_text='1 unresolved.')).to_be_visible()
            assert document_store.upload_calls == 1
            page.get_by_role('button', name='Retry unresolved receipts').click()
            expect(page.get_by_role('status').filter(has_text='1 receipt attached.')).to_be_visible()
            assert document_store.upload_calls == 1
            with page.expect_download() as download:
                page.get_by_role('link', name='Download receipt.pdf', exact=True).click()
            assert Path(download.value.path()).read_bytes() == b'%PDF synthetic receipt'
            page.get_by_role('button', name='Remove receipt.pdf', exact=True).click()
            expect(page.get_by_role('alertdialog', name='Remove receipt')).to_contain_text('stored file remains')
            page.get_by_role('button', name='Confirm remove', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Receipt reference removed. File retained.')).to_be_visible()
            page.get_by_role('button', name='Link receipt.pdf', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Receipt linked.')).to_be_visible()
            assert document_store.delete_calls == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_role('link', name='Back to transactions').click()
            expect(page.get_by_role('table', name='Business ledger')).to_contain_text('1 receipt(s)')
        finally:
            browser.close()


def test_receipt_upload_progress_uncertain_retry_and_invalid_batch(commercial, commercial_server, document_store):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        release = Event()
        original = document_store.upload

        def blocked_upload(*args):
            assert release.wait(10), 'Synthetic upload was not released.'
            return original(*args)

        try:
            page = browser.new_page(viewport={'width': 320, 'height': 844})
            page.goto(commercial_server + '/transactions/expense/receipts')
            expect(page.get_by_role('heading', name='No receipts attached')).to_be_visible()
            page.get_by_label('Receipt files').set_input_files([
                {'name': 'good.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF synthetic'},
                {'name': 'invalid.txt', 'mimeType': 'text/plain', 'buffer': b'unsupported'},
            ])
            expect(page.get_by_role('alert')).to_contain_text('Check the highlighted fields')
            assert document_store.upload_calls == 0
            page.get_by_label('Receipt files').set_input_files({'name': 'uncertain.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF synthetic'})
            document_store.fail_after_create = True
            with patch.object(document_store, 'upload', side_effect=blocked_upload):
                page.get_by_role('button', name='Attach selected receipts').click()
                expect(page.get_by_role('progressbar', name='Receipt upload progress')).to_be_visible()
                expect(page.get_by_label('Select business')).to_be_disabled()
                expect(page.get_by_label('Receipt files')).to_be_disabled()
                release.set()
                expect(page.get_by_role('alert').filter(has_text='1 unresolved.')).to_be_visible()
            assert document_store.upload_calls == 1 and len(document_store.files) == 1
            page.get_by_role('button', name='Retry unresolved receipts').click()
            expect(page.get_by_role('status').filter(has_text='1 receipt attached.')).to_be_visible()
            assert document_store.upload_calls == 2 and len(document_store.files) == 1
            with patch.object(document_store, 'fetch', side_effect=DocumentError('Synthetic download failure')):
                page.get_by_role('link', name='Download uncertain.pdf').click()
                expect(page.get_by_role('alert')).to_contain_text('request could not be completed')
            expect(page.get_by_role('heading', name='Receipts', exact=True)).to_be_visible()
            page.get_by_role('button', name='Remove uncertain.pdf', exact=True).click()
            page.get_by_role('button', name='Keep receipt', exact=True).click()
            expect(page.get_by_role('link', name='Download uncertain.pdf')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            release.set()
            browser.close()
