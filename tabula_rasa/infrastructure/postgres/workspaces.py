"""Native workspace transactions joining the existing identity/ledger owners."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets
from uuid import uuid4

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.application.ledger_setup import LedgerSetupService
from tabula_rasa.application.workspaces import (
    InvitationCredential, grant_allowed, normalized_email, require_capability, require_bootstrap_id,
)
from .control_plane import PostgresIdentityRepository, identity_operation
from .reference_data import PostgresLedgerSetupRepository
from .sessions import credential_hash


class PostgresWorkspaceRepository:
    def __init__(self, database, *, clock=None):
        self.database = database
        self.identity = PostgresIdentityRepository(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _users(connection, *users):
        # Match the existing membership triggers: users before organization.
        rows = connection.execute(text('''SELECT id FROM identity_users
            WHERE id=ANY(:users) AND state='active' ORDER BY id FOR UPDATE'''),
            {'users': sorted(set(users))}).scalars().all()
        if len(rows) != len(set(users)):
            raise IdentityError('forbidden')

    @staticmethod
    def _role(connection, user, org, *, lock=False):
        if lock and not connection.scalar(text("SELECT id FROM organizations WHERE id=:org AND state='active' FOR UPDATE"), {'org': org}):
            raise IdentityError('forbidden')
        role = connection.scalar(text('''SELECT m.role FROM memberships m
            JOIN organizations o ON o.id=m.organization_id AND o.state='active'
            JOIN identity_users u ON u.id=m.user_id AND u.state='active'
            WHERE m.organization_id=:org AND m.user_id=:user AND m.state='active' '''),
            {'org': org, 'user': user})
        if role is None:
            raise IdentityError('forbidden')
        return role

    def _manage(self, connection, actor, org, *users):
        self._users(connection, actor, *users)
        role = self._role(connection, actor, org, lock=True)
        require_capability(role, 'members:manage')
        return role

    def bootstrap(self, actor, request_id, workspace_name, business_name, organization_id=None):
        require_bootstrap_id(request_id)
        names = [workspace_name, business_name]
        if any(not isinstance(name, str) or not name.strip() or len(name) > 160 for name in names):
            raise IdentityError('validation')
        workspace_name, business_name = [name.strip() for name in names]
        payload = sha256(json.dumps([workspace_name, business_name, organization_id]).encode()).hexdigest()
        with identity_operation(self.database) as connection:
            self._users(connection, actor)
            if organization_id:
                require_capability(self._role(connection, actor, organization_id, lock=True), 'entity:manage')
            previous = connection.execute(text('''SELECT * FROM workspace_bootstraps
                WHERE user_id=:user AND request_id=:request'''), {'user': actor, 'request': request_id}).mappings().first()
            if previous:
                if previous['payload_hash'] != payload:
                    raise IdentityError('conflict')
                self._role(connection, actor, previous['organization_id'])
                return self._bootstrap_result(previous)
            org = organization_id or self.identity.create_organization(actor, workspace_name)
            entity_id = uuid4().hex
            ledger = PostgresLedgerSetupRepository.create_entity(self.database, entity_id, business_name)
            self.identity.bind_entity(org, entity_id)
            LedgerSetupService(ledger).ensure_defaults()
            connection.execute(text('''INSERT INTO workspace_bootstraps
                (user_id,request_id,payload_hash,organization_id,entity_id) VALUES (:user,:request,:payload,:org,:entity)'''),
                {'user': actor, 'request': request_id, 'payload': payload, 'org': org, 'entity': entity_id})
            return {'state': 'ready', 'organization_id': org, 'entity_id': entity_id}

    @staticmethod
    def _bootstrap_result(row):
        return {'state': 'ready', 'organization_id': row['organization_id'], 'entity_id': row['entity_id']}

    def bootstrap_status(self, actor, request_id):
        require_bootstrap_id(request_id)
        with identity_operation(self.database, read_only=True) as connection:
            row = connection.execute(text('''SELECT * FROM workspace_bootstraps
                WHERE user_id=:user AND request_id=:request'''), {'user': actor, 'request': request_id}).mappings().first()
            if row is None:
                return {'state': 'not_started', 'organization_id': None, 'entity_id': None}
            self._role(connection, actor, row['organization_id'])
            return self._bootstrap_result(row)

    def members(self, actor, org):
        with identity_operation(self.database, read_only=True) as connection:
            require_capability(self._role(connection, actor, org), 'members:manage')
            return [dict(row) for row in connection.execute(text('''SELECT m.user_id,u.display_name,m.role,m.state,
                m.authorization_version FROM memberships m JOIN identity_users u ON u.id=m.user_id
                WHERE m.organization_id=:org ORDER BY m.user_id'''), {'org': org}).mappings()]

    def change_member(self, actor, org, target, role, active, version, *, session=None, ownership=False):
        with identity_operation(self.database) as connection:
            acting_role = self._manage(connection, actor, org, target)
            current = connection.execute(text('''SELECT role,state,authorization_version FROM memberships
                WHERE organization_id=:org AND user_id=:user'''), {'org': org, 'user': target}).mappings().first()
            if current is None:
                raise IdentityError('forbidden')
            if current['authorization_version'] != version:
                raise IdentityError('stale')
            # Admins can demote themselves, but cannot alter an Owner or peer
            # Admin. DB deferred constraints protect the last active Owner.
            if acting_role != 'owner' and (current['role'] == 'owner'
                    or current['role'] == 'admin' and actor != target
                    or role != current['role'] and not grant_allowed(acting_role, role)):
                raise IdentityError('forbidden')
            if role == 'owner' and acting_role != 'owner':
                raise IdentityError('forbidden')
            if role == 'owner' and (current['role'] != 'owner' or current['state'] != 'active' and active) and not ownership:
                raise IdentityError('forbidden')
            if ownership or current['role'] == 'owner' and (role != 'owner' or not active):
                self._require_fresh(session)
            self.identity.set_membership(org, target, role, active=active)

    def invite(self, actor, org, email, role):
        raw, invitation_id = secrets.token_urlsafe(32), uuid4().hex
        with identity_operation(self.database) as connection:
            acting_role = self._manage(connection, actor, org)
            if not grant_allowed(acting_role, role):
                raise IdentityError('forbidden')
            connection.execute(text('''INSERT INTO workspace_invitations
                (id,credential_hash,organization_id,email_key,role,inviter_id,expires_at)
                VALUES (:id,:hash,:org,:email,:role,:actor,:expiry)'''),
                {'id': invitation_id, 'hash': credential_hash(raw), 'org': org, 'email': normalized_email(email),
                 'role': role, 'actor': actor, 'expiry': self.clock() + timedelta(hours=48)})
        return InvitationCredential(invitation_id, raw)

    def invitations(self, actor, org):
        with identity_operation(self.database, read_only=True) as connection:
            require_capability(self._role(connection, actor, org), 'members:manage')
            return [dict(row) for row in connection.execute(text('''SELECT id,email_key AS recipient_email,role,expires_at,
                CASE WHEN state='pending' AND expires_at<=:now THEN 'expired' ELSE state END AS state
                FROM workspace_invitations WHERE organization_id=:org ORDER BY created_at DESC'''),
                {'org': org, 'now': self.clock()}).mappings()]

    def revoke_invitation(self, actor, org, invitation_id):
        with identity_operation(self.database) as connection:
            acting_role = self._manage(connection, actor, org)
            row = connection.execute(text('''SELECT role FROM workspace_invitations
                WHERE id=:id AND organization_id=:org FOR UPDATE'''), {'id': invitation_id, 'org': org}).mappings().first()
            if row is None or not grant_allowed(acting_role, row['role']):
                raise IdentityError('forbidden')
            connection.execute(text("UPDATE workspace_invitations SET state='revoked' WHERE id=:id AND state='pending'"), {'id': invitation_id})

    def respond(self, session, credential, accept):
        self._require_fresh(session)
        hashed = credential_hash(credential)
        with identity_operation(self.database) as connection:
            # Discover only internally, then use the standard user/org lock order.
            row = connection.execute(text('SELECT * FROM workspace_invitations WHERE credential_hash=:hash'), {'hash': hashed}).mappings().first()
            if row is None or row['email_key'] != normalized_email(session.verified_email):
                raise IdentityError('invitation_invalid')
            self._users(connection, session.user_id, row['inviter_id'])
            acting_role = self._role(connection, row['inviter_id'], row['organization_id'], lock=True)
            row = connection.execute(text('SELECT * FROM workspace_invitations WHERE credential_hash=:hash FOR UPDATE'), {'hash': hashed}).mappings().one()
            self._require_fresh(session)
            if row['state'] != 'pending':
                raise IdentityError('invitation_used')
            if row['expires_at'] <= self.clock():
                raise IdentityError('invitation_expired')
            if not grant_allowed(acting_role, row['role']):
                raise IdentityError('forbidden')
            if accept:
                existing = connection.scalar(text('''SELECT state FROM memberships
                    WHERE organization_id=:org AND user_id=:user'''), {'org': row['organization_id'], 'user': session.user_id})
                if existing != 'active':
                    self.identity.set_membership(row['organization_id'], session.user_id, row['role'])
            connection.execute(text('UPDATE workspace_invitations SET state=:state,responded_by=:user WHERE id=:id'),
                {'id': row['id'], 'user': session.user_id, 'state': 'accepted' if accept else 'declined'})
            return {'state': 'accepted' if accept else 'declined'}

    def _require_fresh(self, session):
        # Match the verified OIDC auth_time tolerance; retain the five-minute
        # upper bound rather than treating session validity as recent login.
        if (session is None or not session.verified_email
                or not -timedelta(seconds=60) <= self.clock() - session.authenticated_at <= timedelta(minutes=5)):
            raise IdentityError('reauthentication_required')
