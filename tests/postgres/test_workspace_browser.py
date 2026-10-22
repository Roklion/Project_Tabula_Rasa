"""Two-user native workspace lifecycle and desktop/mobile cache isolation."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres.test_identity import verified
from tests.postgres.test_identity_browser import named_server as named_server, configure_login
from tests.postgres.browser_quality_support import assert_accessible
from tests.test_oidc import oidc as oidc


@pytest.mark.parametrize('engine', ['chromium', 'firefox', 'webkit'])
@pytest.mark.parametrize('width', [1440, 390, 320])
def test_first_ledger_retry_refresh_repeat_visit_and_two_entity_switch(named_server, width, engine):
    origin, repo, _, _, _, _, claims, info = named_server
    claims['sub'] = info['sub'] = 'new-owner'
    first_name = 'IndependentStudio' * 9
    def evidence(page, stage):
        assert_accessible(page)
        if root := os.environ.get('TABULA_RASA_BROWSER_EVIDENCE'):
            target = Path(root)
            target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / f'{engine}-{width}-{stage}.png'), full_page=True)
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            configure_login(context, origin, claims)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'})")
            page.goto(origin)
            page.get_by_role('link', name='Sign in', exact=True).click()
            expect(page.get_by_role('button', name='Create your first business', exact=True)).to_be_visible()
            actor = context.request.get(origin + '/api/v1/session').json()['actor_id']
            page.get_by_role('button', name='Create your first business', exact=True).click()
            page.get_by_label('Business name').fill(first_name)
            page.get_by_role('button', name='Review defaults').focus()
            page.keyboard.press('Enter')
            page.get_by_role('button', name='Back', exact=True).click()
            expect(page.get_by_label('Business name')).to_have_value(first_name)
            page.get_by_role('button', name='Review defaults').click()
            expect(page.get_by_label('Workspace name')).to_have_count(0)
            page.get_by_role('button', name='Back', exact=True).focus()
            page.keyboard.press('Tab')
            expect(page.get_by_role('button', name='Create business', exact=True)).to_be_focused()
            evidence(page, 'review-first')
            peer = context.new_page()
            # Disable focus/periodic authority checks: only the broadcast may refresh this peer.
            peer.add_init_script("Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'})")
            peer.goto(origin)
            peer.get_by_role('button', name='Create your first business', exact=True).click()
            peer.get_by_label('Business name').fill('Unsubmitted peer draft')
            page.bring_to_front()
            endpoint = '**/api/v1/businesses'
            def unavailable(route):
                expect(page.get_by_role('button', name='Retry same setup', exact=True)).to_be_disabled()
                evidence(page, 'pending-first')
                route.fulfill(status=503, content_type='application/json',
                    body='{"error":{"code":"unavailable"},"request_id":"synthetic-failure"}')
            page.route(endpoint, unavailable)
            page.get_by_role('button', name='Create business', exact=True).click()
            expect(page.get_by_role('alert')).to_be_visible()
            evidence(page, 'uncertain-first')
            expect(peer.get_by_label('Business name')).to_have_value('Unsubmitted peer draft')
            receipt = page.evaluate('Object.values(sessionStorage)[0]')
            page.reload()
            page.get_by_role('button', name='Create your first business', exact=True).click()
            expect(page.get_by_text('Setup was interrupted.', exact=False)).to_be_visible()
            page.get_by_label('Business name').fill(first_name)
            page.get_by_role('button', name='Review defaults').click()
            # Commit on the real API, then lose only its response.
            def lost_response(route):
                response = route.fetch()
                assert response.status == 200
                route.fulfill(status=503, content_type='application/json',
                    body='{"error":{"code":"unavailable"},"request_id":"synthetic-lost-response"}')
            page.unroute(endpoint)
            page.route(endpoint, lost_response)
            page.get_by_role('button', name='Create business', exact=True).click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_label('Business name')).to_have_count(0)
            assert context.request.get(origin + '/api/v1/businesses/creation/' + receipt).json()['state'] == 'ready'
            with repo.database.transaction(read_only=True) as connection:
                assert connection.scalar(text('SELECT count(*) FROM workspace_bootstraps WHERE user_id=:user'), {'user': actor}) == 1
            # Model a reload after commit but before the first receipt is retired.
            page.evaluate("([key, receipt]) => sessionStorage.setItem(key, receipt)",
                [f'tabula-setup:{actor}:first', receipt])
            page.reload()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(page.get_by_role('button', name='Create your first business', exact=True)).to_have_count(0)
            page.get_by_role('link', name='Review accounts', exact=True).click()
            expect(page.get_by_role('heading', name='Accounts', exact=True)).to_be_visible()
            expect(page.get_by_role('alert')).to_have_count(0)
            assert context.request.get(origin + '/api/v1/entities/alpha/accounts').status == 403
            peer.goto(origin + '/businesses')
            expect(peer.get_by_role('region', name='Available businesses').get_by_role('listitem')).to_have_count(1)
            peer.get_by_role('button', name='Create another business', exact=True).click()
            expect(peer.get_by_label('Business name')).to_be_visible()
            peer.get_by_label('Business name').fill('Another unsubmitted peer draft')
            page.bring_to_front()
            page.goto(origin + '/businesses')
            # Wait for the async list before clicking a control below it.
            expect(page.get_by_role('region', name='Available businesses').get_by_role('listitem')).to_have_count(1)
            page.get_by_role('button', name='Create another business', exact=True).click()
            expect(page.get_by_label('Business name')).to_be_visible()
            page.get_by_label('Business name').fill('Second business')
            review_action = page.get_by_role('button', name='Review defaults')
            # A focused field may still scroll the viewport. Read both rectangles
            # in one layout snapshot rather than mixing separate viewport offsets.
            section = page.get_by_role('region', name='Other ways to get started')
            gap = section.evaluate("""(section, action) =>
                section.getBoundingClientRect().top - action.getBoundingClientRect().bottom""",
                review_action.element_handle())
            assert gap >= 32
            expect(page.get_by_label('Business name')).to_have_value('Second business')
            evidence(page, 'another-business')
            expect(page.get_by_label('Business name')).to_have_value('Second business')
            expect(review_action).to_be_enabled()
            review_action.click()
            page.get_by_role('button', name='Create business', exact=True).click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_label('Select business')).to_have_value(
                context.request.get(origin + '/api/v1/session').json()['entity']['id'])
            choices = context.request.get(origin + '/api/v1/entities').json()['items']
            assert len(choices) == 2
            assert len({item['organization_id'] for item in choices}) == 2
            first = next(item['id'] for item in choices if item['name'] == first_name)
            page.get_by_label('Select business').select_option(first)
            page.get_by_role('button', name='Discard draft and switch').click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            assert context.request.get(origin + '/api/v1/session').json()['entity']['id'] == first
            assert_accessible(page)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()


@pytest.mark.parametrize('engine', ['chromium', 'firefox', 'webkit'])
@pytest.mark.parametrize('width', [1440, 390, 320])
def test_onboarding_invitee_joins_existing_workspace_without_new_ownership(named_server, width, engine):
    from tabula_rasa.application.workspaces import WorkspaceService
    from tabula_rasa.infrastructure.postgres.workspaces import PostgresWorkspaceRepository

    origin, repo, _, _, org, _, _, _ = named_server
    with repo.database.transaction(read_only=True) as connection:
        configuration_hash = connection.scalar(text("SELECT configuration_hash FROM identity_environments WHERE environment='test'"))
    sessions = PostgresSessionRepository(repo.database, 'test', configuration_hash)
    _, owner = sessions.issue(verified())
    raw, invitee = sessions.issue(verified('new-invitee'))
    service = WorkspaceService(PostgresWorkspaceRepository(repo.database))
    invitation = service.invite(owner, org, 'shared@example.test', 'editor')
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            context.add_cookies([{'name': 'tabula_dev_session', 'value': raw, 'url': origin, 'httpOnly': True, 'sameSite': 'Lax'}])
            page = context.new_page()
            page.add_init_script("Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'})")
            page.goto(origin + '/invitations')
            expect(page.get_by_role('button', name='Create your first business', exact=True)).to_have_count(0)
            credential_field = page.get_by_label('Invitation credential', exact=True)
            credential_field.focus()
            expect(credential_field).to_be_focused()
            assert_accessible(page)
            if root := os.environ.get('TABULA_RASA_BROWSER_EVIDENCE'):
                page.screenshot(path=str(Path(root) / f'{engine}-{width}-invitation.png'), full_page=True)
            credential_field.fill(invitation.credential)
            peer = context.new_page()
            peer.add_init_script("Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'})")
            peer.goto(origin)
            peer.get_by_role('button', name='Create your first business', exact=True).click()
            peer.get_by_label('Business name').fill('Unsubmitted invitee draft')
            page.bring_to_front()
            page.get_by_role('button', name='Accept invitation').click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(peer.get_by_label('Business name')).to_have_count(0)
            page.reload()
            assert context.request.get(origin + '/api/v1/session').json()['entity']['role'] == 'editor'
            with repo.database.transaction(read_only=True) as connection:
                assert connection.scalar(text('SELECT count(*) FROM workspace_bootstraps WHERE user_id=:user'), {'user': invitee.user_id}) == 0
                assert connection.scalar(text('SELECT count(*) FROM memberships WHERE user_id=:user'), {'user': invitee.user_id}) == 1
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_workspace_switch_invite_demote_remove_and_logout(named_server, width):
    origin, repo, alice, bob, a, b, _, _ = named_server
    database = repo.database
    with database.transaction(read_only=True) as connection:
        configuration_hash = connection.scalar(text("SELECT configuration_hash FROM identity_environments WHERE environment='test'"))
    sessions = PostgresSessionRepository(database, 'test', configuration_hash)
    alice_raw, _ = sessions.issue(verified())
    bob_raw, _ = sessions.issue(verified('bob'))
    repo.set_membership(b, alice.id, 'read_only')
    create_postgres_services(database, 'alpha').accounts.create('Private alpha account', 'Bank', '0', classification='Asset', parent_id='')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            first = browser.new_context(viewport={'width': width, 'height': 1000})
            second = browser.new_context(viewport={'width': width, 'height': 1000})
            for context, raw in ((first, alice_raw), (second, bob_raw)):
                context.add_cookies([{'name': 'tabula_dev_session', 'value': raw, 'url': origin, 'httpOnly': True, 'sameSite': 'Lax'}])
            owner, member = first.new_page(), second.new_page()
            owner.goto(origin + '/accounts')
            expect(owner.get_by_text('Private alpha account', exact=True)).to_be_visible()
            assert first.request.get(origin + '/api/v1/entities/unknown/accounts').status == 403
            owner.get_by_label('Select business').select_option('beta')
            owner.get_by_role('button', name='Discard draft and switch').click()
            expect(owner.get_by_text('Role: read only', exact=True)).to_be_visible()
            expect(owner).to_have_url(origin + '/')
            expect(owner.get_by_text('Private alpha account', exact=True)).to_have_count(0)
            owner.goto(origin + '/accounts')
            expect(owner.get_by_text('Private alpha account', exact=True)).to_have_count(0)
            owner.get_by_label('Select business').select_option('alpha')
            owner.get_by_role('button', name='Discard draft and switch').click()
            expect(owner.get_by_text('Role: owner', exact=True)).to_be_visible()
            expect(owner).to_have_url(origin + '/')
            owner.get_by_role('link', name='Business & members').click()
            owner.get_by_label('Recipient email').fill('shared@example.test')
            owner.get_by_label('Invitation role').select_option('editor')
            owner.get_by_role('button', name='Create invitation', exact=True).click()
            credential_input = owner.get_by_label('New invitation credential')
            expect(credential_input).to_be_visible()
            credential = credential_input.input_value()
            owner.get_by_role('button', name='Dismiss credential').click()
            member.goto(origin + '/workspace')
            member.get_by_label('Invitation credential', exact=True).fill(credential)
            member.get_by_role('button', name='Accept invitation').click()
            expect(member.get_by_label('Select business')).to_be_visible()
            member.get_by_label('Select business').select_option('alpha')
            member.get_by_role('button', name='Discard draft and switch').click()
            expect(member.get_by_text('Role: editor', exact=True)).to_be_visible()
            owner.reload()
            editor = owner.locator('section.surface').filter(has=owner.get_by_text('Current role: Editor · active', exact=True))
            editor.get_by_label('Member role').select_option('read_only')
            editor.get_by_role('button', name='Review membership change').click()
            owner.get_by_role('button', name='Confirm membership change', exact=True).click()
            expect(owner.get_by_text('Current role: Read-only · active', exact=True)).to_be_visible()
            member.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(member.get_by_text('Role: read only', exact=True)).to_be_visible()
            read_only = owner.locator('section.surface').filter(has=owner.get_by_text('Current role: Read-only · active', exact=True))
            read_only.get_by_label('Active membership').uncheck()
            read_only.get_by_role('button', name='Review membership change').click()
            owner.get_by_role('button', name='Confirm membership change', exact=True).click()
            expect(owner.get_by_text('Current role: Read-only · inactive', exact=True)).to_be_visible()
            member.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(member.get_by_text('Role: owner', exact=True)).to_be_visible()
            assert second.request.get(origin + '/api/v1/entities/alpha/accounts').status == 403
            assert_accessible(owner)
            assert_accessible(member)
            assert owner.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            peer = first.new_page()
            peer.goto(origin)
            expect(peer.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
            owner.get_by_role('button', name='Sign out', exact=True).click()
            expect(peer.get_by_role('link', name='Sign in', exact=True)).to_be_visible()
            assert second.request.get(origin + '/api/v1/session').status == 200
        finally:
            browser.close()


@pytest.mark.parametrize('engine', ['chromium', 'firefox', 'webkit'])
@pytest.mark.parametrize('width', [1440, 320])
def test_same_name_businesses_remain_distinct_through_selection(named_server, width, engine):
    origin, repo, alice, _, _, b, _, _ = named_server
    repo.set_membership(b, alice.id, 'read_only')
    name = 'Shared independent business ' * 4
    with repo.database.transaction() as connection:
        connection.execute(text("UPDATE business_entities SET name=:name WHERE id IN ('alpha','beta')"), {'name': name})
        configuration_hash = connection.scalar(text("SELECT configuration_hash FROM identity_environments WHERE environment='test'"))
    sessions = PostgresSessionRepository(repo.database, 'test', configuration_hash)
    raw, _ = sessions.issue(verified())
    sessions.select(raw, 'alpha')
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            context.add_cookies([{'name': 'tabula_dev_session', 'value': raw, 'url': origin, 'httpOnly': True, 'sameSite': 'Lax'}])
            page = context.new_page()
            # Isolate explicit selection from focus/periodic authority checks.
            page.add_init_script("Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'})")
            page.goto(origin)
            selector = page.get_by_label('Select business')
            expect(selector.locator('option[value="alpha"]')).to_have_text(name.strip() + ' (reference: alpha)')
            expect(selector.locator('option[value="beta"]')).to_have_text(name.strip() + ' (reference: beta)')
            selector.select_option('beta')
            dialog = page.get_by_role('alertdialog', name='Switch business')
            expect(dialog).to_be_visible()
            expect(dialog.get_by_text('Business reference: beta', exact=True)).to_be_visible()
            dialog.get_by_role('button', name='Keep current business').click()
            expect(selector).to_have_value('alpha')
            assert context.request.get(origin + '/api/v1/session').json()['entity']['id'] == 'alpha'
            selector.select_option('beta')
            page.get_by_role('button', name='Discard draft and switch').click()
            expect(page.get_by_text('Role: read only', exact=True)).to_be_visible()
            expect(page.get_by_text('Business reference: beta', exact=True)).to_be_visible()
            assert context.request.get(origin + '/api/v1/session').json()['entity']['id'] == 'beta'
            assert context.request.get(origin + '/api/v1/entities/unknown/accounts').status == 403
            page.goto(origin + '/businesses')
            businesses = page.get_by_role('region', name='Available businesses')
            expect(businesses.get_by_text(name.strip() + ' (reference: alpha)', exact=False)).to_be_visible()
            expect(businesses.get_by_text(name.strip() + ' (reference: beta)', exact=False)).to_be_visible()
            expect(businesses.get_by_text('Selected business', exact=True)).to_be_visible()
            assert_accessible(page)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()
