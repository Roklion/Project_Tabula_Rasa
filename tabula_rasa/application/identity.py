"""Provider/storage-neutral identity records and the single v1 role policy."""

from dataclasses import dataclass, field
from datetime import datetime


class IdentityError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


READ = frozenset({'bookkeeping:read'})
WRITE = READ | {'bookkeeping:write'}
HANDOFF = WRITE | {'bookkeeping:import', 'bookkeeping:export'}
ADMIN = HANDOFF | {'members:manage'}
ROLE_CAPABILITIES = {
    'owner': ADMIN | {'entity:manage', 'organization:manage', 'connections:manage',
                      'ownership:manage', 'backup:create', 'backup:list', 'backup:download',
                      'archive:recover', 'restore:execute', 'migration:execute', 'cutover:execute',
                      'ledger:reset', 'recovery:authorize', 'business:admin'},
    'admin': ADMIN, 'editor': WRITE, 'accountant': HANDOFF, 'read_only': READ,
}


def capabilities(role):
    return frozenset(ROLE_CAPABILITIES.get(role, ()))


@dataclass(frozen=True)
class User:
    id: str
    state: str
    session_epoch: int


@dataclass(frozen=True)
class EntityAccess:
    entity_id: str
    organization_id: str
    name: str
    role: str
    authorization_version: int


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str = field(repr=False)
    subject: str = field(repr=False)
    email: str = field(repr=False)
    display_name: str = field(repr=False)
    authenticated_at: datetime


@dataclass(frozen=True)
class AuthenticatedSession:
    user_id: str
    cache_id: str
    csrf_token: str = field(repr=False)
    authenticated_at: datetime
    absolute_expires_at: datetime
    selected: EntityAccess | None


@dataclass(frozen=True)
class LoginTransaction:
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    return_path: str


class IdentityService:
    """Narrow internal control-plane facade; caller authorization lives in #313/#315."""

    def __init__(self, repository):
        self.repository = repository

    def resolve_user(self, identity):
        return self.repository.resolve_user(identity)

    def create_organization(self, owner_id, name):
        return self.repository.create_organization(owner_id, name)

    def active_memberships(self, user_id):
        return self.repository.active_memberships(user_id)

    def allowed_entities(self, user_id):
        return self.repository.allowed_entities(user_id)

    def bind_entity(self, organization_id, entity_id):
        return self.repository.bind_entity(organization_id, entity_id)

    def set_membership(self, organization_id, user_id, role, *, active=True):
        return self.repository.set_membership(organization_id, user_id, role, active=active)

    def set_user_state(self, user_id, state):
        return self.repository.set_user_state(user_id, state)

    def set_organization_state(self, organization_id, state):
        return self.repository.set_organization_state(organization_id, state)

    def revoke_user_sessions(self, user_id):
        return self.repository.revoke_user_sessions(user_id)
