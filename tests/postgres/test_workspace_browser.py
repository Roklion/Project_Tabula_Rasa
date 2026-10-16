"""Two-user native workspace lifecycle and desktop/mobile cache isolation."""

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres.test_identity import verified
from tests.postgres.test_identity_browser import named_server as named_server, configure_login
from tests.postgres.browser_quality_support import assert_accessible
from tests.test_oidc import oidc as oidc


@pytest.mark.parametrize('width', [1440, 390, 320])
def test_first_ledger_retry_refresh_repeat_visit_and_two_entity_switch(named_server, width):
    origin, repo, _, _, _, _, claims, info = named_server
    claims['sub'] = info['sub'] = 'new-owner'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            configure_login(context, origin, claims)
            page = context.new_page()
            page.goto(origin)
            page.get_by_role('link', name='Sign in', exact=True).click()
            expect(page.get_by_role('button', name='Start fresh', exact=True)).to_be_visible()
            actor = context.request.get(origin + '/api/v1/session').json()['actor_id']
            page.get_by_role('button', name='Start fresh', exact=True).click()
            page.get_by_label('Workspace name').fill('Fresh workspace')
            page.get_by_label('Business name').fill('First business')
            page.get_by_role('button', name='Review defaults').click()
            page.get_by_role('button', name='Back', exact=True).click()
            expect(page.get_by_label('Business name')).to_have_value('First business')
            page.get_by_role('button', name='Review defaults').click()
            assert_accessible(page)
            endpoint = '**/api/v1/workspaces/bootstrap'
            page.route(endpoint, lambda route: route.fulfill(status=503, content_type='application/json',
                body='{"error":{"code":"unavailable"},"request_id":"synthetic-failure"}'))
            page.get_by_role('button', name='Create ledger', exact=True).click()
            expect(page.get_by_role('alert')).to_be_visible()
            receipt = page.evaluate('Object.values(sessionStorage)[0]')
            page.reload()
            page.get_by_role('button', name='Start fresh', exact=True).click()
            expect(page.get_by_text('Setup was interrupted.', exact=False)).to_be_visible()
            page.get_by_label('Workspace name').fill('Fresh workspace')
            page.get_by_label('Business name').fill('First business')
            page.get_by_role('button', name='Review defaults').click()
            # Commit on the real API, then lose only its response.
            def lost_response(route):
                response = route.fetch()
                assert response.status == 200
                route.fulfill(status=503, content_type='application/json',
                    body='{"error":{"code":"unavailable"},"request_id":"synthetic-lost-response"}')
            page.unroute(endpoint)
            page.route(endpoint, lost_response)
            page.get_by_role('button', name='Create ledger', exact=True).click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            assert context.request.get(origin + '/api/v1/workspaces/bootstrap/' + receipt).json()['state'] == 'ready'
            with repo.database.transaction(read_only=True) as connection:
                assert connection.scalar(text('SELECT count(*) FROM workspace_bootstraps WHERE user_id=:user'), {'user': actor}) == 1
            page.reload()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            expect(page.get_by_role('button', name='Start fresh', exact=True)).to_have_count(0)
            page.get_by_role('link', name='Review accounts', exact=True).click()
            expect(page.get_by_role('heading', name='Accounts', exact=True)).to_be_visible()
            assert context.request.get(origin + '/api/v1/entities/alpha/accounts').status == 403
            page.goto(origin + '/workspace')
            page.get_by_label('Business name').fill('Second business')
            page.get_by_role('button', name='Review defaults').click()
            page.get_by_role('button', name='Create ledger', exact=True).click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            choices = context.request.get(origin + '/api/v1/entities').json()['items']
            assert len(choices) == 2
            first = next(item['id'] for item in choices if item['name'] == 'First business')
            page.get_by_label('Select business').select_option(first)
            page.get_by_role('button', name='Discard draft and switch').click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
            assert context.request.get(origin + '/api/v1/session').json()['entity']['id'] == first
            assert_accessible(page)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        finally:
            browser.close()


def test_onboarding_invitee_joins_existing_workspace_without_new_ownership(named_server):
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
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            context.add_cookies([{'name': 'tabula_dev_session', 'value': raw, 'url': origin, 'httpOnly': True, 'sameSite': 'Lax'}])
            page = context.new_page()
            page.goto(origin + '/invitations')
            expect(page.get_by_role('button', name='Start fresh', exact=True)).to_have_count(0)
            page.get_by_label('Invitation credential', exact=True).fill(invitation.credential)
            page.get_by_role('button', name='Accept invitation').click()
            expect(page.get_by_role('heading', name='Your ledger is ready')).to_be_visible()
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
            owner.get_by_role('link', name='Workspace & members').click()
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
            expect(member.get_by_text('Workspace: B', exact=True)).to_be_visible()
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
