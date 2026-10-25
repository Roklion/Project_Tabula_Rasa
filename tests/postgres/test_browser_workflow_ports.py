"""Compiled browser existing-workflow ports against disposable PostgreSQL."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from playwright.sync_api import expect
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
from tests.http.test_maps_quota import CONFIG as QUOTA_CONFIG, report as quota_report
from tabula_rasa.http.maps_quota import MapsQuotaAdapter


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


@pytest.fixture
def quota_runtime(monkeypatch):
    original = PostgresRuntime.__init__
    provider = Mock()
    provider.fetch_report.return_value = quota_report()
    def initialize(self, *args, **kwargs):
        kwargs['maps_quota'] = MapsQuotaAdapter(QUOTA_CONFIG, client_factory=lambda _: provider)
        original(self, *args, **kwargs)
    monkeypatch.setattr(PostgresRuntime, '__init__', initialize)
    return provider


@pytest.mark.parametrize('width', [1440, 390])
def test_usage_load_refresh_and_business_reset_use_production_handlers(quota_runtime, commercial, commercial_server, width, native_browser):
    with native_browser('chromium') as browser:
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        page.goto(commercial_server + '/accounts')
        summary = page.locator('summary').filter(has_text='Google Maps API usage')
        expect(summary).to_be_visible()
        quota_runtime.fetch_report.assert_not_called()
        summary.focus()
        summary.press('Enter')
        expect(page.get_by_role('button', name='Load usage', exact=True)).to_be_enabled()
        quota_runtime.fetch_report.assert_not_called()
        page.get_by_role('button', name='Load usage', exact=True).click()
        expect(page.get_by_text('ComputeRoutes: 120/Unlimited (per minute)', exact=True)).to_be_visible()
        expect(page.get_by_text('Autocomplete requests: 0/Unlimited (per minute)', exact=True)).to_be_visible()
        assert quota_runtime.fetch_report.call_count == 1
        page.get_by_role('button', name='Refresh', exact=True).click()
        expect(page.get_by_role('button', name='Refresh', exact=True)).to_be_enabled()
        assert quota_runtime.fetch_report.call_count == 2
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
        page.get_by_label('Select business').select_option('beta')
        page.get_by_role('button', name='Discard draft and switch', exact=True).click()
        expect(page.get_by_label('Select business')).to_have_value('beta')
        expect(page.get_by_role('button', name='Refresh', exact=True)).to_have_count(0)
        expect(summary.locator('..')).not_to_have_attribute('open', '')
        summary.click()
        page.get_by_role('button', name='Load usage', exact=True).click()
        expect(page.get_by_text('ComputeRoutes: 120/Unlimited (per minute)', exact=True)).to_be_visible()
        assert quota_runtime.fetch_report.call_count == 2  # Authorized deployment cache reuse.


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
def test_complete_selected_journal_and_full_financial_downloads(commercial, commercial_server, width, native_browser):
    with native_browser('chromium') as browser:
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        page.goto(commercial_server + '/transactions')
        expect(page.get_by_role('checkbox')).to_have_count(2)
        page.get_by_role('checkbox', name='Select 2026-10-05 · Loaded · 12.50', exact=True).check()
        with page.expect_download() as download:
            page.get_by_role('button', name='Export selected', exact=True).click()
        rows = csv_rows(Path(download.value.path()).read_bytes())[1]
        assert [row['Type'] for row in rows] == ['Journal', '↳ Posting', '↳ Posting']
        assert rows[1]['Debit'] == rows[2]['Credit'] == '12.50'
        page.get_by_label('Search transactions').fill('not present')
        expect(page.get_by_role('checkbox')).to_have_count(0)
        page.goto(commercial_server + '/data')
        expect(page.get_by_role('heading', name='Data & backup', exact=True)).to_be_visible()
        for label, column in [('Download transactions CSV', 'ID'), ('Download journal postings CSV', 'Entry ID')]:
            with page.expect_download() as download:
                page.get_by_role('button', name=label, exact=True).click()
            assert len(csv_rows(Path(download.value.path()).read_bytes())[1]) >= 1
            assert column in csv_rows(Path(download.value.path()).read_bytes())[0]


def test_mixed_source_stale_link_reload_retry_download_and_reference_only_remove(commercial, commercial_server, document_store, native_browser):
    alpha, _, _, _ = commercial
    created = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed())
    with native_browser('chromium') as browser:
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
        # Failed inventory refresh must not clear the stale-source guard.
        page.route('**/api/v1/entities/alpha/documents', lambda route: route.fulfill(
            status=503, json={'error': {'code': 'unavailable'}, 'request_id': 'inventory-refresh'}))
        page.get_by_role('button', name='Review latest source', exact=True).click()
        page.get_by_role('button', name='Reload source', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='inventory-refresh').first).to_be_visible()
        expect(page.get_by_role('button', name='Retry unresolved receipts')).to_be_disabled()
        page.unroute('**/api/v1/entities/alpha/documents')
        page.get_by_role('button', name='Review latest source', exact=True).click()
        with page.expect_response(lambda response: response.request.method == 'GET'
                                  and response.url.endswith('/entities/alpha/documents')) as refreshed:
            page.get_by_role('button', name='Reload source', exact=True).click()
        assert refreshed.value.status == 200
        assert refreshed.value.json()['items'][0]['filename'] == 'source.pdf'
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


def test_maps_confirmed_round_trip_and_manual_return_persist_only_after_save(maps_runtime, commercial, commercial_server, native_browser):
    alpha, beta, _, _ = commercial
    initial = len(alpha.mileage.list_trips())
    with native_browser('chromium') as browser:
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.add_init_script(PLACES_STUB)
        page.goto(commercial_server + '/mileage/new')
        page.get_by_label('Business purpose', exact=True).fill('Client inspection')
        page.get_by_role('checkbox', name='Round trip', exact=True).check()
        assert page.get_by_role('button', name='Calculate mileage', exact=True).evaluate(
            "button => !!(button.compareDocumentPosition(document.querySelector('input[name=miles]')) & Node.DOCUMENT_POSITION_FOLLOWING)")
        for label, value in [('Starting location lookup', 'Office'), ('Destination lookup', 'Client')]:
            page.get_by_role('textbox', name=label, exact=True).fill(value)
            page.get_by_role('button', name='Choose ' + label, exact=True).click()
        assert page.get_by_label('New tag name (optional)', exact=True).evaluate(
            "tags => !!(tags.compareDocumentPosition(document.querySelector('[aria-label=\"Google Maps attribution\"]')) & Node.DOCUMENT_POSITION_FOLLOWING)")
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


def test_maps_quota_and_lookup_failures_keep_manual_entry(maps_runtime, commercial, commercial_server, native_browser):
    alpha, _, _, _ = commercial
    maps_runtime.compute_route.side_effect = GoogleRoutesQuotaError('Synthetic quota failure')
    with native_browser('chromium') as browser:
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
