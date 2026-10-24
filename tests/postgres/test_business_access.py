"""Independent business roles through public APIs; synthetic native records only."""

from dataclasses import replace
from datetime import timedelta
import json
import logging

import pytest

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.application.workspaces import WorkspaceService
from tabula_rasa.infrastructure.postgres.workspaces import PostgresWorkspaceRepository
from tests.postgres.test_authorization_http import named_client
from tests.postgres.test_identity import verified
from tests.postgres.test_workspaces import context, create


def test_public_business_contract_and_foreign_member_invitation_ids(database, caplog, monkeypatch):
    monkeypatch.setenv('TABULA_RASA_TELEMETRY_SCOPE_KEY', 'synthetic-business-scope-key-32-chars')
    with named_client(database) as (client, auth, repo, identities, factory, _, headers):
        alice, bob, a, b = identities
        choices = client.get('/api/v1/businesses').json()['items']
        assert choices == [{'id': 'alpha', 'name': 'alpha', 'role': 'owner'}]
        # An Owner of A has no administrative rights in B, including when a
        # browser forges backing-container selectors or a real foreign user ID.
        invite = WorkspaceService(PostgresWorkspaceRepository(database)).invite(
            auth.sessions.validate(client.cookies.get(auth.session_cookie)), a, 'shared@example.test', 'accountant')
        endpoints = [
            ('GET', '/members', None), ('GET', '/invitations', None),
            ('POST', '/invitations', {'email': 'shared@example.test', 'role': 'read_only'}),
            ('PATCH', '/members/' + bob.id, {'role': 'read_only', 'active': False, 'authorization_version': 1}),
            ('POST', '/members/' + bob.id + '/ownership', {'authorization_version': 1}),
            ('DELETE', '/invitations/' + invite.id, None),
        ]
        factory.reset_mock()
        for method, suffix, body in endpoints:
            response = client.request(method, '/api/v1/businesses/beta' + suffix, json=body,
                headers={**headers, 'X-Organization-ID': a, 'X-Entity-ID': 'alpha'})
            assert response.status_code == 403
            assert invite.credential not in response.text
        assert client.delete('/api/v1/businesses/alpha/invitations/foreign', headers=headers).status_code == 403
        assert client.post('/api/v1/businesses/alpha/invitations', headers=headers, json={
            'email': 'shared@example.test', 'role': 'read_only', 'organization_id': b,
        }).status_code == 422
        # Independent authorization applies even when the same actor owns both.
        repo.set_membership(b, alice.id, 'owner')
        assert {item['role'] for item in client.get('/api/v1/businesses').json()['items']} == {'owner'}
        assert client.get('/api/v1/businesses/beta/invitations').json()['items'] == []
        assert client.delete('/api/v1/businesses/beta/invitations/' + invite.id, headers=headers).status_code == 403
        repo.set_membership(b, alice.id, 'admin')
        with caplog.at_level(logging.INFO, logger='tabula_rasa.http'):
            result = client.get('/api/v1/businesses/beta/members')
        assert result.status_code == 200
        event = json.loads(next(record.message for record in reversed(caplog.records) if record.name == 'tabula_rasa.http'))
        telemetry = client.app.state.telemetry
        assert event['entity_ref'] == telemetry.reference('entity', 'beta')
        assert event['organization_ref'] == telemetry.reference('organization', b)
        assert all(value not in caplog.text for value in (invite.credential, 'shared@example.test'))
        assert client.get('/api/v1/session').json()['entity']['id'] == 'alpha'
        # Admin cannot elevate itself or another Owner via business adapters.
        member = next(item for item in result.json()['items'] if item['user_id'] == alice.id)
        assert client.post('/api/v1/businesses/beta/members/' + alice.id + '/ownership',
            headers=headers, json={'authorization_version': member['authorization_version']}).status_code == 403
        factory.assert_not_called()


def test_invited_accountant_and_revoke_in_a_preserve_b_membership_session_and_private_bytes(database):
    with named_client(database) as (client, auth, repo, identities, _, _, headers):
        alice, bob, a, b = identities
        path = '/api/v1/businesses/alpha'
        issued = client.post(path + '/invitations', headers=headers,
            json={'email': 'shared@example.test', 'role': 'accountant'}).json()
        # Bob independently owns B before accepting A.
        bob_raw, bob_session = auth.sessions.issue(verified('bob'))
        client.cookies.set(auth.session_cookie, bob_raw)
        bob_headers = {**headers, 'X-CSRF-Token': bob_session.csrf_token}
        doc = '/api/v1/entities/beta/documents/' + 'b' * 32 + '/content'
        assert client.put(doc, params={'filename': 'receipt.pdf'}, headers=bob_headers,
            content=b'%PDF synthetic B').status_code == 200
        preview = client.post('/api/v1/invitations/preview', headers=bob_headers,
            json={'credential': issued['credential']})
        assert preview.status_code == 200
        assert preview.json()['business_id'] == 'alpha' and preview.json()['role'] == 'accountant'
        assert set(preview.json()) == {'business_id', 'business_name', 'role', 'expires_at'}
        assert client.get('/api/v1/businesses').json()['items'] == [{'id': 'beta', 'name': 'beta', 'role': 'owner'}]
        assert client.post('/api/v1/invitations/respond', headers=bob_headers,
            json={'credential': issued['credential'], 'accept': True}).status_code == 200
        assert {item['id']: item['role'] for item in client.get('/api/v1/businesses').json()['items']} == {
            'alpha': 'accountant', 'beta': 'owner'}
        assert client.get(path + '/members').status_code == 403
        assert client.post('/api/v1/invitations/preview', headers=bob_headers,
            json={'credential': issued['credential']}).status_code == 409
        beta_before = next(m for m in repo.active_memberships(bob.id) if m['organization_id'] == b)
        owner_raw, _ = auth.sessions.issue(verified())
        client.cookies.set(auth.session_cookie, owner_raw)
        owner_session = client.get('/api/v1/session').json()
        member = next(item for item in client.get(path + '/members').json()['items'] if item['user_id'] == bob.id)
        change = client.patch(path + '/members/' + bob.id, headers={**headers, 'X-CSRF-Token': owner_session['csrf_token']},
            json={'role': 'read_only', 'active': False, 'authorization_version': member['authorization_version']})
        assert change.status_code == 204
        assert next(m for m in repo.active_memberships(bob.id) if m['organization_id'] == b) == beta_before
        client.cookies.set(auth.session_cookie, bob_raw)
        assert client.get('/api/v1/session').json()['entity']['id'] == 'beta'
        assert client.get(doc).content == b'%PDF synthetic B'
        assert client.post('/api/v1/session/entity', headers=bob_headers, json={'entity_id': 'alpha'}).status_code == 403
        for suffix in ('accounts', 'reports/summary', 'documents/' + 'b' * 32 + '/content', 'exports/transactions.csv'):
            assert client.get('/api/v1/entities/alpha/' + suffix).status_code == 403


@pytest.mark.parametrize('failure', ['wrong_recipient', 'stale_auth', 'revoked', 'expired', 'suspended', 'inviter_demoted'])
def test_recipient_preview_has_no_discovery_or_mutation_on_failure(database, failure):
    _, _, owner = context(database)
    _, _, recipient = context(database, 'recipient')
    repository = PostgresWorkspaceRepository(database)
    service = WorkspaceService(repository)
    business = create(service, owner)
    invitation = service.invite(owner, business['organization_id'], recipient.verified_email, 'admin')
    if failure == 'wrong_recipient':
        recipient = owner
    elif failure == 'stale_auth':
        recipient = replace(recipient, authenticated_at=recipient.authenticated_at - timedelta(minutes=6))
    elif failure == 'revoked':
        service.revoke_invitation(owner, business['organization_id'], invitation.id)
    elif failure == 'expired':
        repository.clock = lambda: owner.authenticated_at + timedelta(hours=49)
        recipient = replace(recipient, authenticated_at=repository.clock())
    elif failure == 'suspended':
        repository.identity.set_organization_state(business['organization_id'], 'suspended')
    else:
        repository.identity.set_membership(business['organization_id'], recipient.user_id, 'owner')
        repository.identity.set_membership(business['organization_id'], owner.user_id, 'admin')
    before = repository.identity.active_memberships(recipient.user_id)
    with pytest.raises(IdentityError):
        service.preview_invitation(recipient, invitation.credential)
    assert repository.identity.active_memberships(recipient.user_id) == before


def test_preview_existing_membership_keeps_independent_role_and_never_consumes(database):
    _, _, owner = context(database)
    _, _, recipient = context(database, 'recipient')
    repository = PostgresWorkspaceRepository(database)
    service = WorkspaceService(repository)
    business = create(service, owner)
    repository.identity.set_membership(business['organization_id'], recipient.user_id, 'read_only')
    invitation = service.invite(owner, business['organization_id'], recipient.verified_email, 'admin')
    first = service.preview_invitation(recipient, invitation.credential)
    assert first['role'] == 'read_only'
    assert service.preview_invitation(recipient, invitation.credential) == first
    assert service.respond(recipient, invitation.credential, True)['state'] == 'accepted'
