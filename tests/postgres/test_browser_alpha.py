"""The hosted #288 journey uses the same actual compiled HTTP/PostgreSQL path."""

from uuid import uuid4

from playwright.sync_api import sync_playwright
import pytest

from tabula_rasa.deployment.alpha import ENGINES, WIDTHS, journey
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
