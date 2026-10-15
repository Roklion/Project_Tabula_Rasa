"""Two-user native workspace lifecycle and desktop/mobile cache isolation."""

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres.test_identity import verified
from tests.postgres.test_identity_browser import named_server as named_server
from tests.postgres.browser_quality_support import assert_accessible
from tests.test_oidc import oidc as oidc


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
