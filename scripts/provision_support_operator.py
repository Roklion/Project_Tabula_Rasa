"""Database-administrator-only, explicit support grant provisioning.

Run only after human approval for the exact target. Support staff use the HTTP
client instead. Preview is default; applying requires its plan hash.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.audit import AuditContext, audit_context
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.control_plane import identity_operation
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.infrastructure.postgres.support import PostgresSupport


def provision(database, *, administrator_id, user_id, organization_id, entity_id, environment,
              approval_reference, expires_at=None, can_admin=False, revoke=False, confirm_plan=None):
    if (environment not in {'test', 'development', 'staging', 'production'}
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', approval_reference)
            or type(can_admin) is not bool or type(revoke) is not bool
            or not revoke and (not isinstance(expires_at, datetime) or expires_at.utcoffset() is None
                               or expires_at <= datetime.now(timezone.utc))):
        raise IdentityError('forbidden')
    context = AuditContext('operator', administrator_id, 'support_provisioning', entity_id)
    with audit_context(database, context), identity_operation(database) as connection:
        # The command's authority is the separately approved database administrator
        # connection, never a tenant's claimed user ID or role.
        if not connection.scalar(text("""SELECT e.entity_id FROM organization_entities e
            JOIN identity_users a ON a.id=:administrator AND a.state='active'
            JOIN identity_users u ON u.id=:user AND (u.state='active' OR :revoke)
            JOIN identity_environments env ON env.environment=:env
            WHERE e.organization_id=:org AND e.entity_id=:entity FOR SHARE OF e,a,u,env"""),
            {'administrator': administrator_id, 'user': user_id, 'env': environment,
             'org': organization_id, 'entity': entity_id, 'revoke': revoke}):
            raise IdentityError('forbidden')
        connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,341))'),
                           {'key': json.dumps([user_id, organization_id, environment])})
        previous = connection.execute(text("""SELECT can_admin,expires_at,revoked_at,approval_reference
            FROM support_grants WHERE user_id=:user AND organization_id=:org AND environment=:env FOR UPDATE"""),
            {'user': user_id, 'org': organization_id, 'env': environment}).mappings().first()
        plan = sha256(json.dumps([administrator_id, user_id, organization_id, entity_id, environment,
            approval_reference, expires_at, can_admin, revoke, dict(previous) if previous else None],
            default=str, sort_keys=True).encode()).hexdigest()
        if confirm_plan is None:
            return {'applied': False, 'plan_sha256': plan}
        if confirm_plan != plan:
            raise IdentityError('concurrent_write')
        params = {'user': user_id, 'org': organization_id, 'env': environment,
                  'expires': expires_at, 'admin': can_admin, 'approval': approval_reference}
        if revoke:
            if previous is None:
                raise IdentityError('forbidden')
            connection.execute(text("""UPDATE support_grants SET revoked_at=clock_timestamp(),
                approval_reference=:approval WHERE user_id=:user AND organization_id=:org AND environment=:env"""), params)
        else:
            connection.execute(text("""INSERT INTO support_grants
                (user_id,organization_id,environment,expires_at,can_admin,approval_reference)
                VALUES (:user,:org,:env,:expires,:admin,:approval)
                ON CONFLICT (user_id,organization_id,environment) DO UPDATE SET
                expires_at=EXCLUDED.expires_at,can_admin=EXCLUDED.can_admin,
                approval_reference=EXCLUDED.approval_reference,revoked_at=NULL"""), params)
        PostgresSupport._record(connection, entity_id, 'revoke_grant' if revoke else 'provision_grant',
                                'access_request', user_id, environment=environment, grant_environment=environment,
                                grant_can_admin=can_admin if not revoke else previous['can_admin'],
                                grant_expires_at=expires_at if not revoke else previous['expires_at'],
                                approval_reference=approval_reference)
        return {'applied': True, 'plan_sha256': plan}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('administrator', 'user', 'organization', 'entity', 'environment', 'approval-reference'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--expires-at', type=datetime.fromisoformat)
    parser.add_argument('--admin', action='store_true')
    parser.add_argument('--revoke', action='store_true')
    parser.add_argument('--confirm-plan')
    args = parser.parse_args(argv)
    database = None
    try:
        database = Database(DatabaseSettings.from_environment(required=True))
        result = provision(database, administrator_id=args.administrator, user_id=args.user,
            organization_id=args.organization, entity_id=args.entity, environment=args.environment,
            approval_reference=args.approval_reference, expires_at=args.expires_at,
            can_admin=args.admin, revoke=args.revoke, confirm_plan=args.confirm_plan)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'error': 'support_provisioning_refused'}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
