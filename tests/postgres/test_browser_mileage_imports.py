"""Compiled browser mileage import against disposable, entity-scoped PostgreSQL."""

from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
import pytest

from tabula_rasa.application.mileage import MileageService
from tabula_rasa.errors import StorageError
from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_browser_baselines import document_store as document_store
from tests.postgres.test_http_baselines import commercial as commercial, snapshot
from tests.postgres.test_http_mileage_imports import CSV
from tests.postgres.browser_quality_support import assert_accessible


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


def upload(page, content=CSV):
    page.get_by_label('QuickBooks mileage CSV', exact=True).set_input_files(
        {'name': 'trips.csv', 'mimeType': 'text/csv', 'buffer': content})
    page.get_by_role('button', name='Preview mileage import', exact=True).click()


@pytest.mark.parametrize('width', [1440, 390])
def test_mileage_import_preview_confirmation_errors_and_scope(commercial, commercial_server, database, width):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/data')
            before = snapshot(database)
            upload(page)
            expect(page.get_by_role('status').filter(has_text='Mileage ready: 1')).to_be_visible()
            assert snapshot(database) == before
            assert_accessible(page)
            page.get_by_role('button', name='Import validated mileage', exact=True).click()
            page.get_by_role('button', name='Keep reviewing', exact=True).click()
            assert snapshot(database) == before
            page.get_by_role('button', name='Import validated mileage', exact=True).click()
            page.get_by_role('button', name='Confirm mileage import', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Imported 1 mileage trips.')).to_be_visible()
            upload(page)
            expect(page.get_by_role('status').filter(has_text='Mileage ready: 0')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated mileage', exact=True)).to_be_disabled()
            page.get_by_label('Select business', exact=True).select_option('beta')
            page.get_by_role('button', name='Discard draft and switch', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Mileage ready:')).to_have_count(0)
            upload(page, CSV + b'bad,Business,Inspection,Van,Office,Site,4\n')
            expect(page.get_by_role('alert').filter(has_text='Fix these mileage')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated mileage', exact=True)).to_be_disabled()
            upload(page)
            expect(page.get_by_role('status').filter(has_text='Mileage ready: 1')).to_be_visible()
            page.get_by_role('button', name='Import validated mileage', exact=True).click()
            page.get_by_role('button', name='Confirm mileage import', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Imported 1 mileage trips.')).to_be_visible()
            assert len(alpha.mileage.list_trips()) == 2 and len(beta.mileage.list_trips()) == 1
        finally:
            browser.close()


def test_mileage_uncertain_create_guidance_requires_fresh_review(commercial, commercial_server):
    alpha, _, _, _ = commercial
    original_import = MileageService.import_quickbooks_mileage

    def lost_response(service, rows):
        original_import(service, rows)
        raise StorageError('Synthetic lost response')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(commercial_server + '/data')
            upload(page)
            expect(page.get_by_role('status').filter(has_text='Mileage ready: 1')).to_be_visible()
            page.get_by_role('button', name='Import validated mileage', exact=True).click()
            with patch.object(MileageService, 'import_quickbooks_mileage', lost_response):
                page.get_by_role('button', name='Confirm mileage import', exact=True).click()
                expect(page.get_by_role('alert').filter(has_text='The import status is not confirmed')).to_be_visible()
            expect(page.get_by_role('button', name='Import validated mileage', exact=True)).to_be_disabled()
            page.get_by_role('button', name='Review mileage import status', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Mileage ready: 0')).to_be_visible()
            assert len(alpha.mileage.list_trips()) == 2
        finally:
            browser.close()
