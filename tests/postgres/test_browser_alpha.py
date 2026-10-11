"""The hosted #288 journey uses the same actual compiled HTTP/PostgreSQL path."""

from uuid import uuid4
from time import sleep

from playwright.sync_api import sync_playwright
import pytest

from tabula_rasa.deployment.alpha import ENGINES, WIDTHS, journey
from tabula_rasa.deployment import alpha as alpha_gate
from tabula_rasa.application.documents import DocumentError
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_http_mileage_documents import commercial as commercial, document_store as document_store


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


@pytest.mark.parametrize('engine', ENGINES)
@pytest.mark.parametrize('width', WIDTHS)
def test_staging_journey_and_preserved_other_entity(commercial, commercial_server, document_store, engine, width):
    alpha, beta, _, _ = commercial
    before_alpha = alpha.transactions.list(fresh=True)
    before_journals = alpha.journals.list(fresh=True)
    before_beta = (beta.accounts.list(), beta.categories.list(), beta.payees.list(), beta.tags.list(), beta.transactions.list(fresh=True))
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            options = dict(base_url=commercial_server, viewport={'width': width, 'height': 1000 if width == 1440 else 844})
            with browser.new_context(**options) as context, browser.new_context(**options) as peer:
                journey(context, peer, origin=commercial_server, entity='alpha', marker='Alpha-' + uuid4().hex)
                assert context.request.get('/api/v1/entities/beta/documents').status == 403
        finally:
            browser.close()
    assert alpha.transactions.list(fresh=True) == before_alpha
    assert alpha.journals.list(fresh=True) == before_journals
    assert (beta.accounts.list(), beta.categories.list(), beta.payees.list(), beta.tags.list(), beta.transactions.list(fresh=True)) == before_beta
    assert document_store.upload_calls == 1 and document_store.delete_calls == 0
    assert all(profile == 'alpha' for profile, _ in document_store.files)


@pytest.mark.parametrize('slow_operation', ['upload', 'unlink', 'relink'])
def test_journey_with_slow_receipt_operation(commercial, commercial_server, document_store, monkeypatch, slow_operation):
    if slow_operation == 'upload':
        owner, method = document_store, 'upload'
    else:
        owner, method = PostgresReceiptRepository, 'unlink' if slow_operation == 'unlink' else 'link'
    original = getattr(owner, method)
    calls = 0

    def delayed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == (2 if slow_operation == 'relink' else 1):
            sleep(5.5)  # Beyond Playwright's default five-second assertion wait.
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, method, delayed)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            options = dict(base_url=commercial_server, viewport={'width': 1440, 'height': 1000})
            with browser.new_context(**options) as context, browser.new_context(**options) as peer:
                journey(context, peer, origin=commercial_server, entity='alpha', marker='Alpha-' + uuid4().hex)
        finally:
            browser.close()
    assert document_store.upload_calls == 1 and document_store.delete_calls == 0


@pytest.mark.parametrize('failure', ['receipt_download', 'receipt_unlink', 'receipt_relink', 'receipt_bytes'])
def test_receipt_failure_stops_with_safe_operation_and_retained_bytes(
        commercial, commercial_server, document_store, monkeypatch, failure):
    alpha, beta, _, _ = commercial
    before_beta = beta.transactions.list(fresh=True)
    monkeypatch.setattr(alpha_gate, 'RECEIPT_TIMEOUT_MS', 1_000)
    if failure in {'receipt_download', 'receipt_bytes'}:
        def fetch(*args, **kwargs):
            if failure == 'receipt_bytes':
                return b'synthetic wrong bytes'
            raise DocumentError('PRIVATE provider response')
        monkeypatch.setattr(document_store, 'fetch', fetch)
    else:
        method = 'unlink' if failure == 'receipt_unlink' else 'link'
        original = getattr(PostgresReceiptRepository, method)
        calls = 0

        def mutate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (2 if failure == 'receipt_relink' else 1):
                raise DocumentError('PRIVATE provider response')
            return original(*args, **kwargs)

        monkeypatch.setattr(PostgresReceiptRepository, method, mutate)
    marker = 'Alpha-' + uuid4().hex
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            options = dict(base_url=commercial_server, viewport={'width': 1440, 'height': 1000})
            with browser.new_context(**options) as context, browser.new_context(**options) as peer:
                with pytest.raises(alpha_gate.AlphaError) as result:
                    journey(context, peer, origin=commercial_server, entity='alpha', marker=marker)
                assert result.value.operation == failure and 'PRIVATE' not in str(result.value)
                rows = [row for row in alpha.transactions.list(fresh=True) if row['description'].startswith(marker)]
                assert len(rows) == 1 and str(rows[0]['amount']) == '11.25'
                response = context.request.get('/api/v1/entities/alpha/transactions/' + rows[0]['id'] + '/receipts')
                assert response.status == 200
                references = response.json()['items']
                assert len(references) == (0 if failure == 'receipt_relink' else 1)
        finally:
            browser.close()
    assert beta.transactions.list(fresh=True) == before_beta
    assert document_store.upload_calls == 1 and document_store.delete_calls == 0
    assert all(profile == 'alpha' for profile, _ in document_store.files)
    assert all(len(content) == 63 for content in document_store.contents.values())
