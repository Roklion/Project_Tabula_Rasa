"""Named-user workspace workflows, separate from ledger and provider identity."""

from dataclasses import dataclass, field

from .identity import IdentityError, capabilities


def grant_allowed(actor_role, target_role):
    return (actor_role == 'owner' and target_role in {'admin', 'editor', 'accountant', 'read_only'}
            or actor_role == 'admin' and target_role in {'editor', 'accountant', 'read_only'})


def normalized_email(value):
    if not isinstance(value, str) or not value.strip() or '@' not in value or len(value) > 320:
        raise IdentityError('validation')
    return value.strip().casefold()


@dataclass(frozen=True)
class InvitationCredential:
    id: str
    credential: str = field(repr=False)


class WorkspaceService:
    def __init__(self, repository):
        self.repository = repository

    def bootstrap(self, session, request_id, workspace_name, business_name, organization_id=None):
        return self.repository.bootstrap(session.user_id, request_id, workspace_name, business_name, organization_id)

    def bootstrap_status(self, session, request_id):
        return self.repository.bootstrap_status(session.user_id, request_id)

    def members(self, session, organization_id):
        return self.repository.members(session.user_id, organization_id)

    def invitations(self, session, organization_id):
        return self.repository.invitations(session.user_id, organization_id)

    def invite(self, session, organization_id, email, role):
        return self.repository.invite(session.user_id, organization_id, normalized_email(email), role)

    def change_member(self, session, organization_id, user_id, role, active, version):
        return self.repository.change_member(session.user_id, organization_id, user_id, role, active, version, session=session)

    def grant_ownership(self, session, organization_id, user_id, version):
        return self.repository.change_member(session.user_id, organization_id, user_id, 'owner', True, version, session=session, ownership=True)

    def revoke_invitation(self, session, organization_id, invitation_id):
        return self.repository.revoke_invitation(session.user_id, organization_id, invitation_id)

    def respond(self, session, credential, accept):
        return self.repository.respond(session, credential, accept)


def require_capability(role, capability):
    if capability not in capabilities(role):
        raise IdentityError('forbidden')
