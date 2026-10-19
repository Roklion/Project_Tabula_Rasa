"""Scoped support adapter; every invocation rechecks the named session and grant.

No bookkeeping services, document providers or secret stores are composed here.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.application.support import (
    REASONS, AccountMetadata, AdministrativeResult, AuditPage, AuditSummary,
    ConnectionHealth, Diagnostics, JobStatus, MemberStatus, MigrationStatus,
)
from .audit import AuditContext, AuditReader, audit_context
from .control_plane import PostgresIdentityRepository, identity_operation
from .jobs import JobQueue, JobRegistry

AUDIT_CAPABILITIES = frozenset({'platform:operate', 'audit:inspect'})
ADMIN_OPERATIONS = frozenset({'revoke_sessions', 'suspend_member', 'suspend_organization'})
AUDIT_FILTERS = frozenset({'since', 'until', 'actor_id', 'action', 'source', 'target_type',
                          'target_id', 'batch_id', 'operation_id', 'after_sequence', 'through_sequence', 'limit'})


class PostgresSupport:
    def __init__(self, database, sessions):
        if sessions.database is not database:
            raise ValueError('Support requires the runtime session repository.')
        self.database, self.sessions = database, sessions

    @contextmanager
    def _operation(self, credential, organization_id, entity_id, reason, *, admin=False, correlation_id=''):
        if (reason not in REASONS or any(not isinstance(v, str) or not v.strip() or len(v) > 200
                                        for v in (organization_id, entity_id))):
            raise IdentityError('forbidden')
        # Context is established before the outer operation; validation is repeated
        # in that operation so an earlier HTTP session snapshot grants no authority.
        session = self.sessions.validate(credential)
        context = AuditContext('operator', session.user_id, 'support', entity_id, correlation_id=correlation_id)
        with audit_context(self.database, context), identity_operation(self.database) as connection:
            current = self.sessions.validate(credential)
            if current.user_id != session.user_id:
                raise IdentityError('forbidden')
            grant = connection.execute(text("""SELECT g.can_admin,o.state FROM support_grants g
                JOIN organizations o ON o.id=g.organization_id
                JOIN organization_entities e ON e.organization_id=o.id AND e.entity_id=:entity
                WHERE g.user_id=:user AND g.environment=:env AND g.organization_id=:org
                AND g.revoked_at IS NULL AND g.expires_at>clock_timestamp()
                FOR SHARE OF o"""),
                {'user': current.user_id, 'env': self.sessions.environment,
                 'org': organization_id, 'entity': entity_id}).mappings().first()
            if grant is None or admin and not grant['can_admin']:
                raise IdentityError('forbidden')
            yield connection, grant['state']

    @staticmethod
    def _record(connection, entity_id, operation, reason, target_user_id=None, *, environment, requested_operation=None,
                grant_environment=None, grant_can_admin=None, grant_expires_at=None, approval_reference=None):
        connection.execute(text("""INSERT INTO support_actions(environment,entity_id,id,operation,reason_code,target_user_id,
                requested_operation,grant_environment,grant_can_admin,grant_expires_at,approval_reference)
            VALUES (:execution_environment,:entity,:id,:operation,:reason,:target,:requested,:environment,:admin,:expires,:approval)"""),
            {'execution_environment': environment, 'entity': entity_id, 'id': uuid4().hex, 'operation': operation,
             'reason': reason, 'target': target_user_id, 'requested': requested_operation,
             'environment': grant_environment, 'admin': grant_can_admin, 'expires': grant_expires_at,
             'approval': approval_reference})

    def diagnostics(self, credential, organization_id, entity_id, reason, *, correlation_id=''):
        with self._operation(credential, organization_id, entity_id, reason, correlation_id=correlation_id) as (connection, state):
            params = {'scope': entity_id, 'org': organization_id, 'env': self.sessions.environment}
            accounts = tuple(AccountMetadata(**row) for row in connection.execute(text("""
                SELECT id,type,classification,active FROM accounts WHERE entity_id=:scope ORDER BY id LIMIT 100
                """), params).mappings())
            members = tuple(MemberStatus(**row) for row in connection.execute(text("""
                SELECT m.user_id,m.role,m.state,u.state AS user_state,
                    (SELECT count(*) FROM identity_sessions s
                     JOIN identity_environments env ON env.environment=s.environment
                     JOIN identity_bindings b ON b.id=s.binding_id AND b.user_id=s.user_id
                     WHERE s.user_id=m.user_id AND s.organization_id=:org AND s.environment=:env
                     AND s.user_epoch=u.session_epoch AND u.state='active'
                     AND s.environment_epoch=env.epoch AND s.revoked_at IS NULL
                     AND s.idle_expires_at>clock_timestamp() AND s.absolute_expires_at>clock_timestamp()
                     AND m.state='active' AND :state='active') AS active_sessions
                FROM memberships m JOIN identity_users u ON u.id=m.user_id
                WHERE m.organization_id=:org ORDER BY m.user_id LIMIT 100
                """), {**params, 'state': state}).mappings())
            connections = tuple(ConnectionHealth(**row) for row in connection.execute(text("""
                SELECT provider,status FROM external_connections WHERE entity_id=:scope
                AND organization_id=:org ORDER BY provider LIMIT 100"""), params).mappings())
            migrations = tuple(MigrationStatus(**row) for row in connection.execute(text("""
                SELECT id,status FROM migration_runs WHERE entity_id=:scope
                ORDER BY created_at DESC,id LIMIT 100"""), params).mappings())
            jobs = tuple(JobStatus(str(row['id']), row['job_type'], row['state'],
                                   row['attempts'], row['failure_code'])
                         for row in JobQueue(self.database, entity_id, JobRegistry(),
                                             service_id='support-reader').diagnostics(limit=100))
            self._record(connection, entity_id, 'diagnostics', reason, environment=self.sessions.environment)
            return Diagnostics(organization_id, entity_id, state, accounts, members, connections, migrations, jobs)

    def audit(self, credential, organization_id, entity_id, reason, *, correlation_id='', **filters):
        if (filters.keys() - AUDIT_FILTERS or type(filters.get('limit', 100)) is not int
                or not 1 <= filters.get('limit', 100) <= 100
                or type(filters.get('after_sequence', 0)) is not int or filters.get('after_sequence', 0) < 0):
            raise IdentityError('forbidden')
        through = filters.get('through_sequence')
        if through is not None and (type(through) is not int or not 0 <= through <= 9223372036854775807):
            raise IdentityError('forbidden')
        for key in ('since', 'until'):
            value = filters.get(key)
            if value is not None and (not hasattr(value, 'utcoffset') or value.utcoffset() is None):
                raise IdentityError('forbidden')
        if filters.get('since') and filters.get('until') and filters['since'] >= filters['until']:
            raise IdentityError('forbidden')
        with self._operation(credential, organization_id, entity_id, reason, correlation_id=correlation_id) as (connection, _):
            reader = AuditReader(self.database, entity_id, capabilities=AUDIT_CAPABILITIES)
            if through is None:
                with reader.operation() as scoped:
                    through = scoped.scalar(text('SELECT COALESCE(max(sequence),0) FROM audit_events '
                        'WHERE entity_id=:scope AND organization_id=:org'),
                        {'scope': entity_id, 'org': organization_id})
            rows = reader.query(organization_id=organization_id, **{**filters, 'through_sequence': through})
            events = []
            for row in rows:
                support = None
                if row['target_type'] == 'support_actions':
                    support = connection.execute(text("""SELECT operation,reason_code FROM support_actions
                        WHERE entity_id=:scope AND id=:id"""),
                        {'scope': entity_id, 'id': row['target_key'].get('id')}).mappings().first()
                events.append(AuditSummary(
                    row['sequence'], row['occurred_at'], row['actor_type'], row['actor_id'],
                    row['source'], row['action'], row['target_type'], row['target_key'],
                    row['operation_id'], row['batch_id'],
                    support['operation'] if support else None, support['reason_code'] if support else None))
            self._record(connection, entity_id, 'audit', reason, environment=self.sessions.environment)
            cursor = rows[-1]['sequence'] if len(rows) == filters.get('limit', 100) else None
            return AuditPage(tuple(events), cursor, through)

    def administer(self, credential, organization_id, entity_id, reason, operation, *,
                   target_user_id=None, confirm_plan=None, correlation_id=''):
        if operation not in ADMIN_OPERATIONS or (operation == 'suspend_organization') != (target_user_id is None):
            raise IdentityError('forbidden')
        with self._operation(credential, organization_id, entity_id, reason, admin=True, correlation_id=correlation_id) as (connection, state):
            member = None
            if target_user_id is not None:
                member = connection.execute(text("""SELECT role,state,authorization_version FROM memberships
                    WHERE organization_id=:org AND user_id=:user FOR UPDATE"""),
                    {'org': organization_id, 'user': target_user_id}).mappings().first()
                if member is None:
                    raise IdentityError('forbidden')
            # Scope and current state are part of the confirmation. New sessions or
            # a changed membership invalidate an earlier preview.
            sessions = tuple(connection.scalars(text("""SELECT cache_id FROM identity_sessions
                WHERE organization_id=:org AND user_id=:user AND environment=:env AND revoked_at IS NULL
                ORDER BY cache_id FOR UPDATE"""), {'org': organization_id, 'user': target_user_id,
                                       'env': self.sessions.environment})) if operation == 'revoke_sessions' else ()
            plan = sha256(json.dumps([organization_id, entity_id, self.sessions.environment,
                reason, operation, target_user_id, state, dict(member) if member else None, sessions],
                sort_keys=True).encode()).hexdigest()
            if confirm_plan is not None and confirm_plan != plan:
                raise IdentityError('concurrent_write')
            if confirm_plan is not None:
                repository = PostgresIdentityRepository(self.database)
                if operation == 'suspend_member':
                    repository.set_membership(organization_id, target_user_id, member['role'], active=False)
                elif operation == 'suspend_organization':
                    repository.set_organization_state(organization_id, 'suspended')
                else:
                    connection.execute(text("""UPDATE identity_sessions SET revoked_at=clock_timestamp()
                        WHERE organization_id=:org AND user_id=:user AND environment=:env AND revoked_at IS NULL
                        AND cache_id=ANY(:sessions)"""),
                        {'org': organization_id, 'user': target_user_id, 'env': self.sessions.environment,
                         'sessions': list(sessions)})
            self._record(connection, entity_id, operation if confirm_plan is not None else 'preview', reason, target_user_id,
                         environment=self.sessions.environment, requested_operation=operation)
            return AdministrativeResult(confirm_plan is not None, plan)
