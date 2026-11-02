"""Scoped lifecycle transactions; no document, backup or deletion executor."""

from sqlalchemy import text

from tabula_rasa.application.customer_lifecycle import (
    DELETION_BLOCKERS, KINDS, POLICY_VERSION, RECOVERY_WINDOW, transition,
)
from tabula_rasa.application.identity import IdentityError
from tabula_rasa.application.workspaces import require_bootstrap_id
from .control_plane import identity_operation
from .workspaces import PostgresWorkspaceRepository


class PostgresCustomerLifecycle:
    def __init__(self, database):
        self.database = database
        self.workspaces = PostgresWorkspaceRepository(database)

    def _authorize(self, c, session, entity, *, lock=False):
        if entity and lock:
            # Drain bookkeeping before the existing user/organization lock order.
            c.execute(text('SELECT pg_advisory_xact_lock(346,hashtext(:entity))'), {'entity': entity})
        self.workspaces._users(c, session.user_id)
        if entity is None:
            return
        row = c.execute(text('''SELECT o.id FROM organization_entities e
            JOIN organizations o ON o.id=e.organization_id AND o.state='active'
            JOIN memberships m ON m.organization_id=o.id AND m.user_id=:actor
            AND m.state='active' AND m.role='owner'
            WHERE e.entity_id=:entity AND e.state='active' ''' + ('FOR UPDATE OF o,m' if lock else '')),
            {'actor': session.user_id, 'entity': entity}).first()
        if row is None:
            raise IdentityError('forbidden')

    @staticmethod
    def _last_owned(c, actor):
        return c.execute(text('''SELECT e.entity_id FROM memberships mine
            JOIN organizations o ON o.id=mine.organization_id AND o.state='active'
            JOIN organization_entities e ON e.organization_id=o.id AND e.state='active'
            WHERE mine.user_id=:actor AND mine.role='owner' AND mine.state='active'
            AND NOT EXISTS (SELECT 1 FROM memberships other JOIN identity_users u
                ON u.id=other.user_id AND u.state='active'
                WHERE other.organization_id=o.id AND other.user_id<>:actor
                AND other.role='owner' AND other.state='active') ORDER BY e.entity_id'''),
            {'actor': actor}).scalars().all()

    @staticmethod
    def _result(c, row):
        result = dict(row)
        result['effective_state'] = row['state']
        if row['kind'] == 'business_closure' and row['state'] == 'confirmed':
            now = c.scalar(text('SELECT clock_timestamp()'))
            result['effective_state'] = 'read_only' if now < row['recover_until'] else 'closed_retained'
        result['events'] = [dict(event) for event in c.execute(text('''SELECT action,occurred_at,actor_id
            FROM customer_lifecycle_events WHERE request_id=:id ORDER BY sequence'''), {'id': row['id']}).mappings()]
        return result

    def status(self, session, entity=None):
        # User locks are needed by the shared ownership boundary; this is not
        # a ledger mutation or a provider inventory/readback.
        with identity_operation(self.database) as c:
            self._authorize(c, session, entity)
            rows = c.execute(text('''SELECT * FROM customer_lifecycle_requests WHERE
                (entity_id=:entity AND :entity IS NOT NULL) OR
                (:entity IS NULL AND entity_id IN (SELECT e.entity_id FROM organization_entities e
                    JOIN organizations o ON o.id=e.organization_id AND o.state='active'
                    JOIN memberships m ON m.organization_id=e.organization_id
                    WHERE m.user_id=:actor AND m.role='owner' AND m.state='active' AND e.state='active')) OR
                (entity_id IS NULL AND requester_id=:actor) ORDER BY created_at,id'''),
                {'actor': session.user_id, 'entity': entity}).mappings().all()
            return {'policy_version': POLICY_VERSION, 'recovery_days': RECOVERY_WINDOW.days,
                    'deletion_available': False, 'deletion_blockers': list(DELETION_BLOCKERS),
                    'last_owned_businesses': self._last_owned(c, session.user_id),
                    'requests': [self._result(c, row) for row in rows]}

    def request(self, session, request_id, kind, entity=None):
        require_bootstrap_id(request_id)
        if kind not in KINDS or kind == 'business_closure' and not entity or kind != 'business_closure' and entity is not None:
            raise IdentityError('validation')
        with identity_operation(self.database) as c:
            self._authorize(c, session, entity, lock=bool(entity))
            existing = c.execute(text('SELECT * FROM customer_lifecycle_requests WHERE id=:id'),
                                 {'id': request_id}).mappings().first()
            if existing:
                if (existing['requester_id'], existing['kind'], existing['entity_id']) != (session.user_id, kind, entity):
                    raise IdentityError('conflict')
                return self._result(c, existing)
            if kind == 'account_closure' and self._last_owned(c, session.user_id):
                raise IdentityError('invariant')
            row = c.execute(text('''INSERT INTO customer_lifecycle_requests
                (id,requester_id,entity_id,kind,policy_version) VALUES (:id,:actor,:entity,:kind,:policy) RETURNING *'''),
                {'id': request_id, 'actor': session.user_id, 'entity': entity, 'kind': kind, 'policy': POLICY_VERSION}).mappings().one()
            self._event(c, row, session.user_id, 'requested')
            return self._result(c, row)

    def change(self, session, request_id, action, expected_version, *, export_saved=False):
        require_bootstrap_id(request_id)
        with identity_operation(self.database) as c:
            initial = c.execute(text('SELECT * FROM customer_lifecycle_requests WHERE id=:id'), {'id': request_id}).mappings().first()
            if initial is None:
                raise IdentityError('forbidden')
            entity = initial['entity_id']
            self._authorize(c, session, entity, lock=bool(entity))
            if entity is None and initial['requester_id'] != session.user_id:
                raise IdentityError('forbidden')
            self.workspaces._require_fresh(session)
            row = c.execute(text('SELECT * FROM customer_lifecycle_requests WHERE id=:id FOR UPDATE'), {'id': request_id}).mappings().one()
            if not transition(row['state'], action, row['version'], expected_version):
                return self._result(c, row)
            now = c.scalar(text('SELECT clock_timestamp()'))
            if action == 'cancel' and row['recover_until'] and now >= row['recover_until']:
                raise IdentityError('conflict')
            if action == 'confirm' and row['kind'] == 'business_closure' and not export_saved:
                raise IdentityError('required')
            if action == 'confirm' and row['kind'] == 'account_closure' and self._last_owned(c, session.user_id):
                raise IdentityError('invariant')
            confirmed = now if action == 'confirm' else row['confirmed_at']
            until = (now + RECOVERY_WINDOW if row['kind'] == 'business_closure' and action == 'confirm'
                     else row['recover_until'])
            updated = c.execute(text('''UPDATE customer_lifecycle_requests SET state=:state,
                version=version+1,confirmed_at=:confirmed,recover_until=:until WHERE id=:id RETURNING *'''),
                {'id': request_id, 'state': 'confirmed' if action == 'confirm' else 'cancelled',
                 'confirmed': confirmed, 'until': until}).mappings().one()
            if action == 'confirm' and row['kind'] == 'account_closure':
                # Existing identity triggers bump the epoch and enforce last Owner
                # safety at commit. Revoke every environment's retained sessions.
                c.execute(text("UPDATE identity_users SET state='disabled' WHERE id=:actor"), {'actor': session.user_id})
                c.execute(text('''UPDATE identity_sessions SET revoked_at=clock_timestamp()
                    WHERE user_id=:actor AND revoked_at IS NULL'''), {'actor': session.user_id})
            self._event(c, updated, session.user_id, 'confirmed' if action == 'confirm' else 'cancelled')
            return self._result(c, updated)

    @staticmethod
    def _event(c, row, actor, action):
        c.execute(text('''INSERT INTO customer_lifecycle_events(request_id,actor_id,action,policy_version)
            VALUES (:id,:actor,:action,:policy)'''),
            {'id': row['id'], 'actor': actor, 'action': action, 'policy': row['policy_version']})
