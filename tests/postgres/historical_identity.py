"""Synthetic pre-admission schema fixtures for explicit forward-migration tests.

Normal runtime requires current schema; historical records are seeded directly.
"""

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from unittest.mock import patch
from hashlib import sha256
import json
import secrets
from uuid import uuid4

from sqlalchemy import text

from tabula_rasa.application.ledger_setup import LedgerSetupService
from tabula_rasa.application.workspaces import InvitationCredential
from tabula_rasa.infrastructure.postgres.control_plane import PostgresIdentityRepository
from tabula_rasa.infrastructure.postgres.reference_data import (
    PostgresLedgerSetupRepository,
)
from tabula_rasa.infrastructure.postgres.sessions import credential_hash


@contextmanager
def historical_access():
    """Frozen access query only while seeding a pre-lifecycle migration source.

    Current runtime always requires the current schema. Exit before testing the
    upgraded runtime so new lifecycle authorization is never stubbed there.
    """
    query = '''SELECT e.entity_id,e.organization_id,b.name,b.currency_code,m.role,
        m.authorization_version,o.name AS organization_name FROM organization_entities e
        JOIN business_entities b ON b.id=e.entity_id
        JOIN organizations o ON o.id=e.organization_id AND o.state='active'
        JOIN memberships m ON m.organization_id=o.id AND m.user_id=:user AND m.state='active'
        JOIN identity_users u ON u.id=m.user_id AND u.state='active'
        WHERE e.state='active' AND NOT EXISTS (SELECT 1 FROM organization_entities other
            WHERE other.organization_id=e.organization_id AND other.entity_id<>e.entity_id) '''
    with patch('tabula_rasa.infrastructure.postgres.control_plane.ENTITY_ACCESS_SQL', query), \
            patch('tabula_rasa.infrastructure.postgres.workspaces.ENTITY_ACCESS_SQL', query):
        yield


def legacy_business(database, actor, request=None, workspace="Workspace", name=None):
    request, name = request or uuid4().hex, name or workspace + " business"
    identity = PostgresIdentityRepository(database)
    with database.transaction() as connection:
        org = identity.create_organization(actor.user_id, workspace)
        entity = uuid4().hex
        ledger = PostgresLedgerSetupRepository.create_entity(database, entity, name)
        identity.bind_entity(org, entity)
        LedgerSetupService(ledger).ensure_defaults()
        connection.execute(
            text("""INSERT INTO workspace_bootstraps(user_id,request_id,payload_hash,organization_id,entity_id)
            VALUES (:user,:request,:payload,:org,:entity)"""),
            {
                "user": actor.user_id,
                "request": request,
                "payload": sha256(
                    json.dumps([workspace, name, None]).encode()
                ).hexdigest(),
                "org": org,
                "entity": entity,
            },
        )
    return {"state": "ready", "organization_id": org, "entity_id": entity}


def legacy_invitation(database, actor, org, email, role):
    key, raw = uuid4().hex, secrets.token_urlsafe(32)
    with database.transaction() as connection:
        connection.execute(
            text("""INSERT INTO workspace_invitations
            (id,credential_hash,organization_id,email_key,role,inviter_id,expires_at)
            VALUES (:id,:hash,:org,:email,:role,:actor,:expiry)"""),
            {
                "id": key,
                "hash": credential_hash(raw),
                "org": org,
                "email": email,
                "role": role,
                "actor": actor.user_id,
                "expiry": datetime.now(timezone.utc) + timedelta(hours=48),
            },
        )
    return InvitationCredential(key, raw)
