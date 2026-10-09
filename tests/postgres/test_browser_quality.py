"""#287 accessibility, responsive keyboard use and actual HTTP failure states."""

from threading import Event

from playwright.sync_api import expect, sync_playwright
import pytest

from tabula_rasa.http.context import TrustedDevelopmentContext
from tests.postgres.browser_quality_support import VIEWPORTS, assert_accessible, assert_dialog_keyboard
from tests.postgres.test_browser_baselines import commercial_server as commercial_server
from tests.postgres.test_http_baselines import commercial as commercial, snapshot


@pytest.fixture
def browser_resolver():
    return TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))


@pytest.mark.parametrize('viewport', VIEWPORTS)
def test_accessibility_shell_core_forms_and_tables(commercial_server, viewport):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport=dict(zip(('width', 'height'), viewport)))
            for route, label in [('accounts/new', 'Account name'), ('categories/new', 'Category name'),
                                 ('payees/new', 'Name'), ('tags/new', 'Name'),
                                 ('transactions/new', 'Amount'), ('journals/new', 'Date')]:
                page.goto(commercial_server + '/' + route)
                expect(page.get_by_label(label, exact=True)).to_be_visible()
                assert_accessible(page)
            page.goto(commercial_server + '/accounts')
            expect(page.get_by_role('button', name='Edit cash', exact=True)).to_be_visible()
            assert_accessible(page)
            page.goto(commercial_server + '/transactions')
            expect(page.get_by_role('region', name='Ledger', exact=True)).to_be_visible()
            assert_accessible(page)
            if viewport[0] <= 390:
                table = page.get_by_role('region', name='Ledger', exact=True)
                table.focus()
                table.press('ArrowRight')
                page.wait_for_function("document.querySelector('[aria-label=Ledger]').scrollLeft > 0")
            page.goto(commercial_server + '/reports')
            expect(page.get_by_role('heading', name='Balance sheet', exact=True)).to_be_visible()
            assert_accessible(page)
        finally:
            browser.close()


@pytest.mark.parametrize('engine', ['chromium', 'firefox', 'webkit'])
@pytest.mark.parametrize('width', [1440, 390])
def test_keyboard_confirmations_conflict_and_entity_isolation(commercial, commercial_server, engine, width):
    alpha, beta, _, _ = commercial
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 760 else 844})
            page.goto(commercial_server + '/transactions')
            page.get_by_role('button', name='Edit 2026-10-05 · Expense · 12.50', exact=True).click()
            memo = page.get_by_label('Description / memo', exact=True)
            memo.fill('Synthetic keyboard draft')
            remove = page.get_by_role('button', name='Delete', exact=True)
            memo.focus()
            remove.click()
            page.get_by_role('alertdialog', name='Delete record').get_by_role('button', name='Keep record', exact=True).click()
            expect(remove).to_be_focused()
            remove.focus()
            page.keyboard.press('Enter')
            assert_dialog_keyboard(page, 'Delete record', 'Keep record', 'Confirm delete', remove)
            expect(memo).to_have_value('Synthetic keyboard draft')
            alpha.transactions.update('expense', description='Other writer')
            with page.expect_response(lambda response: response.request.method == 'PATCH') as stale:
                page.get_by_role('button', name='Save changes', exact=True).click()
            assert stale.value.status == 409
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            assert_accessible(page)
            review = page.get_by_role('button', name='Review latest record', exact=True)
            memo.focus()
            review.click()
            page.keyboard.press('Escape')
            expect(review).to_be_focused()
            review.focus()
            page.keyboard.press('Enter')
            assert_dialog_keyboard(page, 'Reload record', 'Keep draft', 'Discard draft and reload', review)
            page.route('**/api/v1/entities/alpha/transactions', lambda route: route.abort('failed') if route.request.method == 'GET' else route.continue_())
            review.click()
            page.get_by_role('button', name='Discard draft and reload', exact=True).click()
            expect(page.get_by_role('alertdialog', name='Reload record')).to_have_count(0)
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(memo).to_have_value('Synthetic keyboard draft')
            page.unroute('**/api/v1/entities/alpha/transactions')
            page.get_by_role('button', name='Reload', exact=True).click()
            page.get_by_role('button', name='Discard draft and reload', exact=True).click()
            expect(memo).to_have_value('Other writer')
            selector = page.get_by_label('Select business', exact=True)
            memo.focus()
            selector.select_option('beta')
            assert_dialog_keyboard(page, 'Switch business', 'Keep current business', 'Discard draft and switch', selector)
            expect(selector).to_have_value('alpha')
            assert not beta.transactions.list()
            page.goto(commercial_server + '/transactions/new')
            memo = page.get_by_label('Description / memo', exact=True)
            memo.fill('Preserved create draft')
            close = page.get_by_role('button', name='Back to records', exact=True)
            memo.focus()
            close.click()
            page.keyboard.press('Escape')
            expect(close).to_be_focused()
            close.focus()
            page.keyboard.press('Enter')
            assert_dialog_keyboard(page, 'Discard draft', 'Keep editing', 'Discard draft and close', close)
            if width <= 760:
                menu = page.get_by_role('button', name='Menu', exact=True)
                menu.focus()
                page.keyboard.press('Enter')
            navigation = page.get_by_role('navigation', name='Main navigation').get_by_role('link', name='Transactions', exact=True)
            memo.focus()
            navigation.click()
            page.keyboard.press('Escape')
            expect(navigation).to_be_focused()
            navigation.focus()
            page.keyboard.press('Enter')
            assert_dialog_keyboard(page, 'Unsaved changes', 'Keep editing', 'Discard draft and leave', navigation)
            expect(memo).to_have_value('Preserved create draft')
            held = []
            page.route('**/api/v1/session/entity', lambda route: held.append(route))
            selector.select_option('beta')
            page.get_by_role('button', name='Discard draft and switch', exact=True).click()
            expect(page.get_by_role('button', name='Keep current business', exact=True)).to_be_disabled()
            expect(page.get_by_role('button', name='Discard draft and switch', exact=True)).to_be_disabled()
            page.keyboard.press('Escape')
            expect(page.get_by_role('alertdialog', name='Switch business')).to_be_visible()
            assert len(held) == 1
            held[0].abort('failed')
            expect(page.get_by_role('alertdialog', name='Switch business')).to_have_count(0)
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(selector).to_have_value('alpha')
            expect(memo).to_have_value('Preserved create draft')
            selector.select_option('beta')
            page.get_by_role('button', name='Discard draft and switch', exact=True).click()
            expect(page.get_by_role('button', name='Keep current business', exact=True)).to_be_disabled()
            assert len(held) == 2
            held[1].continue_()  # Complete the actual selection handler, cookie and context response.
            expect(selector).to_have_value('beta')
            expect(memo).to_have_value('')
            page.get_by_role('button', name='Back to records', exact=True).click()
            expect(page.get_by_role('heading', name='No matching entries', exact=True)).to_be_visible()
            assert_accessible(page)
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_real_loading_validation_unexpected_and_network_failure_states(database, commercial, commercial_server, monkeypatch, width):
    alpha, _, _, _ = commercial
    entered, release = Event(), Event()
    account_type = type(alpha.accounts)
    original_list = account_type.list

    def delayed_list(self, *args, **kwargs):
        entered.set()
        assert release.wait(10), 'Test did not release synthetic loading response'
        return original_list(self, *args, **kwargs)

    monkeypatch.setattr(account_type, 'list', delayed_list)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 760 else 844})
            page.goto(commercial_server + '/accounts')
            assert entered.wait(5)
            expect(page.get_by_role('status').filter(has_text='Loading')).to_be_visible()
            assert_accessible(page)
            release.set()
            expect(page.get_by_role('button', name='Edit cash', exact=True)).to_be_visible()
            monkeypatch.setattr(account_type, 'list', original_list)
            page.goto(commercial_server + '/transactions/new')
            amount = page.get_by_label('Amount', exact=True)
            amount.fill('invalid')
            page.get_by_label('From account', exact=True).select_option('cash')
            page.get_by_label('Category', exact=True).select_option('office')
            memo = page.get_by_label('Description / memo', exact=True)
            memo.fill('Unexpected synthetic')
            before = snapshot(database)
            with page.expect_response(lambda response: response.request.method == 'POST') as invalid:
                page.get_by_role('button', name='Save transaction', exact=True).click()
            assert invalid.value.status == 422
            expect(amount).to_be_focused()
            expect(amount).to_have_attribute('aria-invalid', 'true')
            expect(amount).to_have_attribute('aria-describedby', 'amount-error')
            expect(page.locator('#amount-error')).to_have_text('Check this value.')
            expect(page.get_by_role('alert').first).to_contain_text('Check the highlighted fields')
            assert_accessible(page)
            assert snapshot(database) == before
            amount.fill('7.25')
            transaction_type = type(alpha.transactions)
            original_create = transaction_type.create
            attempts = []

            def failed_create(self, *args, **kwargs):
                attempts.append(kwargs['transaction_id'])
                raise RuntimeError('Synthetic internal detail must not be displayed')

            monkeypatch.setattr(transaction_type, 'create', failed_create)
            with page.expect_response(lambda response: response.request.method == 'POST') as unexpected:
                page.get_by_role('button', name='Save transaction', exact=True).click()
            assert unexpected.value.status == 500
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(page.get_by_role('alert')).to_contain_text('Request reference:')
            expect(page.get_by_role('alert')).not_to_contain_text('Synthetic internal detail')
            expect(memo).to_have_value('Unexpected synthetic')
            assert_accessible(page)
            assert attempts == [unexpected.value.request.post_data_json['transaction_id']]
            assert snapshot(database) == before
            monkeypatch.setattr(transaction_type, 'create', original_create)
            # A dropped transport is deliberately intercepted; conflicts above and
            # validation/unexpected errors here traverse the actual HTTP handlers.
            page.route('**/api/v1/entities/alpha/transactions', lambda route: route.abort('failed') if route.request.method == 'POST' else route.continue_())
            page.get_by_role('button', name='Save transaction', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Your draft is preserved')
            expect(page.get_by_role('alert')).not_to_contain_text('Request reference:')
            expect(amount).to_have_value('7.25')
            assert snapshot(database) == before
            page.unroute('**/api/v1/entities/alpha/transactions')
            with page.expect_response(lambda response: response.request.method == 'POST') as saved:
                page.get_by_role('button', name='Save transaction', exact=True).click()
            assert saved.value.status == 201
            assert saved.value.request.post_data_json['transaction_id'] == attempts[0]
            expect(page.get_by_role('status').filter(has_text='Record created.')).to_be_visible()
            assert len([row for row in alpha.transactions.list(fresh=True) if row['id'] == attempts[0]]) == 1
        finally:
            release.set()
            browser.close()
