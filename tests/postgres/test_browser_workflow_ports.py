"""Compiled browser existing-workflow ports against disposable PostgreSQL."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from playwright.sync_api import expect, sync_playwright
import pytest

from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.context import TrustedDevelopmentContext
from tabula_rasa.http.maps import MileageMapsAdapter
from tabula_rasa.maps_routing import GoogleRoutesQuotaError
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_http_baselines import commercial as commercial
from tests.postgres.secondary_support import mixed
from tests.test_application_documents import FakeDocumentStore
from tests.test_financial_csv import csv_rows


@pytest.fixture
def document_store():
    return FakeDocumentStore()


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


@pytest.fixture
def maps_runtime(monkeypatch):
    original = PostgresRuntime.__init__
    routes = Mock()
    routes.compute_route.side_effect = lambda origin, destination: SimpleNamespace(
        suggested_miles=Decimal('12.4' if origin == 'Office' else '14.6'))
    def initialize(self, *args, **kwargs):
        kwargs['maps'] = MileageMapsAdapter('synthetic-browser', routes)
        original(self, *args, **kwargs)
    monkeypatch.setattr(PostgresRuntime, '__init__', initialize)
    return routes


PLACES_STUB = """class TestPlaceWidget extends HTMLElement {
  connectedCallback() {
    const input = document.createElement('input');
    input.setAttribute('aria-label', this.getAttribute('aria-label'));
    input.oninput = () => { this.value = input.value; this.dispatchEvent(new Event('input')); };
    const choose = document.createElement('button'); choose.type = 'button';
    choose.textContent = 'Choose ' + this.getAttribute('aria-label');
    choose.onclick = () => {
      this.value = input.value;
      const event = new Event('gmp-select');
      event.placePrediction = {toPlace: () => ({id: input.value, fetchFields: async () => {}})};
      this.dispatchEvent(event);
    };
    this.append(input, choose);
  }
}
customElements.define('test-place-widget', TestPlaceWidget);
window.google = {maps: {importLibrary: async () => ({PlaceAutocompleteElement: TestPlaceWidget})}};"""


@pytest.mark.parametrize('width', [1440, 390])
def test_complete_selected_journal_and_full_financial_downloads(commercial, commercial_server, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(commercial_server + '/transactions')
            expect(page.get_by_role('checkbox')).to_have_count(2)
            page.get_by_role('checkbox', name='Select 2026-10-05 · Loaded · 12.50', exact=True).check()
            with page.expect_download() as download:
                page.get_by_role('button', name='Export selected', exact=True).click()
            rows = csv_rows(Path(download.value.path()).read_bytes())[1]
            assert [row['Type'] for row in rows] == ['Journal', '↳ Posting', '↳ Posting']
            assert rows[1]['Debit'] == rows[2]['Credit'] == '12.5'
            page.get_by_label('Search transactions').fill('not present')
            expect(page.get_by_role('checkbox')).to_have_count(0)
            page.goto(commercial_server + '/data')
            expect(page.get_by_role('heading', name='Data & backup', exact=True)).to_be_visible()
            for label, column in [('Download transactions CSV', 'ID'), ('Download journal postings CSV', 'Entry ID')]:
                with page.expect_download() as download:
                    page.get_by_role('button', name=label, exact=True).click()
                assert len(csv_rows(Path(download.value.path()).read_bytes())[1]) >= 1
                assert column in csv_rows(Path(download.value.path()).read_bytes())[0]
        finally:
            browser.close()


def test_mixed_source_stale_link_reload_retry_download_and_reference_only_remove(commercial, commercial_server, document_store):
    alpha, _, _, _ = commercial
    created = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(commercial_server + '/mixed-use/source/receipts')
            expect(page.get_by_role('heading', name='Mixed-use receipts', exact=True)).to_be_visible()
            files = page.get_by_label('Receipt files')
            expect(files).to_be_enabled()
            alpha.mixed_use.update('source', expected_source=created, description='Other client edit')
            files.set_input_files({'name': 'source.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF source receipt'})
            page.get_by_role('button', name='Attach selected receipts', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='The source changed or is unavailable')).to_be_visible()
            expect(page.get_by_role('button', name='Retry unresolved receipts')).to_be_disabled()
            assert document_store.upload_calls == 1
            page.get_by_role('button', name='Review latest source', exact=True).click()
            page.get_by_role('button', name='Reload source', exact=True).click()
            page.get_by_role('button', name='Retry unresolved receipts').click()
            expect(page.get_by_role('status').filter(has_text='1 receipt attached.')).to_be_visible()
            assert document_store.upload_calls == 1
            with page.expect_download() as download:
                page.get_by_role('link', name='Download source.pdf', exact=True).click()
            assert Path(download.value.path()).read_bytes() == b'%PDF source receipt'
            page.get_by_role('button', name='Remove source.pdf', exact=True).click()
            page.get_by_role('button', name='Confirm remove', exact=True).click()
            expect(page.get_by_role('button', name='Link source.pdf', exact=True)).to_be_visible()
            assert document_store.delete_calls == 0
            page.get_by_role('button', name='Link source.pdf', exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Receipt linked.')).to_be_visible()
        finally:
            browser.close()


def test_maps_confirmed_round_trip_and_manual_return_persist_only_after_save(maps_runtime, commercial, commercial_server):
    alpha, beta, _, _ = commercial
    initial = len(alpha.mileage.list_trips())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.add_init_script(PLACES_STUB)
            page.goto(commercial_server + '/mileage/new')
            page.get_by_label('Business purpose', exact=True).fill('Client inspection')
            page.get_by_role('checkbox', name='Round trip', exact=True).check()
            for label, value in [('Starting location lookup', 'Office'), ('Destination lookup', 'Client')]:
                page.get_by_role('textbox', name=label, exact=True).fill(value)
                page.get_by_role('button', name='Choose ' + label, exact=True).click()
            page.get_by_role('button', name='Calculate mileage', exact=True).click()
            expect(page.get_by_label('Business miles', exact=True)).to_have_value('12.4')
            expect(page.get_by_label('Return business miles', exact=True)).to_have_value('14.6')
            assert len(alpha.mileage.list_trips()) == initial
            page.get_by_role('button', name='Save mileage trip', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='Review and confirm')).to_be_visible()
            assert len(alpha.mileage.list_trips()) == initial
            page.get_by_label('Return business miles', exact=True).fill('15.2')
            page.get_by_role('checkbox', name='I reviewed the recorded locations and mileage').check()
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/mileage')) as saved:
                page.get_by_role('button', name='Save mileage trip', exact=True).click()
            assert saved.value.status == 201
            assert 'place_id' not in saved.value.request.post_data and 'maps_reviewed' not in saved.value.request.post_data
            trips = [row for row in alpha.mileage.list_trips() if row.business_purpose == 'Client inspection']
            assert {row.miles for row in trips} == {'12.4', '15.2'}
            assert {(row.start_location, row.destination) for row in trips} == {('Office', 'Client'), ('Client', 'Office')}
            assert beta.mileage.list_trips() == () and maps_runtime.compute_route.call_count == 2
        finally:
            browser.close()


def test_maps_quota_and_lookup_failures_keep_manual_entry(maps_runtime, commercial, commercial_server):
    alpha, _, _, _ = commercial
    maps_runtime.compute_route.side_effect = GoogleRoutesQuotaError('Synthetic quota failure')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.add_init_script(PLACES_STUB)
            page.goto(commercial_server + '/mileage/new')
            page.get_by_label('Business purpose', exact=True).fill('Manual fallback')
            for label, value in [('Starting location lookup', 'Office'), ('Destination lookup', 'Client')]:
                page.get_by_role('textbox', name=label, exact=True).fill(value)
                page.get_by_role('button', name='Choose ' + label, exact=True).click()
            page.get_by_label('Business miles', exact=True).fill('9.8')
            page.get_by_role('button', name='Calculate mileage', exact=True).click()
            expect(page.get_by_role('alert').filter(has_text='quota has been reached')).to_be_visible()
            expect(page.get_by_label('Business miles', exact=True)).to_have_value('9.8')
            page.locator('test-place-widget').first.evaluate("element => element.dispatchEvent(new Event('gmp-error'))")
            expect(page.get_by_role('button', name='Retry Google suggestions')).to_be_visible()
            expect(page.get_by_label('Business miles', exact=True)).to_have_value('9.8')
            page.get_by_role('checkbox', name='I reviewed the recorded locations and mileage').check()
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/mileage')) as saved:
                page.get_by_role('button', name='Save mileage trip', exact=True).click()
            assert saved.value.status == 201
            assert next(row for row in alpha.mileage.list_trips() if row.business_purpose == 'Manual fallback').miles == '9.8'
        finally:
            browser.close()
