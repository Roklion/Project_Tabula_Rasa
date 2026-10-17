"""Durable adapters around the existing recurring service and occurrence owner."""

from datetime import date, datetime, timezone
from dataclasses import replace
from contextvars import ContextVar
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from tabula_rasa.application.recurring import RecurringService
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from .jobs import JobQueue, JobRegistry
from .audit import audit_context
from .operations import repository_operation


DEFINITION = 'recurring-dispatch'
_generation_revision = ContextVar('recurring_generation_revision', default=None)


def business_today(time_zone, *, instant=None):
    return (instant or datetime.now(timezone.utc)).astimezone(ZoneInfo(time_zone)).date()


def policy(database, scope):
    with repository_operation(database, read_only=True) as connection:
        row = connection.execute(text('SELECT * FROM recurring_generation_policy WHERE entity_id=:scope'),
                                 {'scope': scope}).mappings().first()
        return dict(row) if row else {'authority': 'explicit', 'time_zone': 'UTC', 'revision': 0}


def set_authority(database, scope, authority, time_zone):
    """Operator-only provisioning. Shared occurrence fences drain before switching."""
    if authority not in {'explicit', 'worker'}:
        raise StorageValidationError('Invalid recurring authority.')
    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise StorageValidationError('Supply an IANA business time zone.') from None
    with repository_operation(database, require_outer=True) as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(334,hashtext(:scope))'), {'scope': scope})
        context = database._audit_context.get()
        if context.actor_type != 'operator' or context.entity_id != scope:
            raise StorageValidationError('An explicit trusted operator context is required.')
        connection.execute(text('''INSERT INTO recurring_generation_policy(entity_id,authority,time_zone)
            VALUES (:scope,:authority,:zone) ON CONFLICT(entity_id) DO UPDATE
            SET authority=EXCLUDED.authority,time_zone=EXCLUDED.time_zone,revision=recurring_generation_policy.revision+1
            WHERE recurring_generation_policy.authority IS DISTINCT FROM EXCLUDED.authority
               OR recurring_generation_policy.time_zone IS DISTINCT FROM EXCLUDED.time_zone'''),
            {'scope': scope, 'authority': authority, 'zone': time_zone})
        definition = connection.scalar(text('''INSERT INTO job_definitions(entity_id,id,job_type,interval_seconds,next_due,paused)
            VALUES (:scope,:id,'recurring.dispatch',3600,clock_timestamp(),:paused)
            ON CONFLICT(entity_id,id) DO UPDATE SET paused=EXCLUDED.paused
            WHERE job_definitions.job_type='recurring.dispatch' RETURNING id'''),
            {'scope': scope, 'id': DEFINITION, 'paused': authority != 'worker'})
        if definition is None:
            raise StorageConflictError('The recurring job definition identity is already in use.')


def enqueue_reconciliation(database, scope, *, through_date=None, service_id='recurring-dispatcher', limit=100):
    """Both explicit HTTP requests and timer dispatch use this exact queue path.

    A next-due identity advances after each bounded batch. Repeated submissions
    before completion select the same job; a later dispatch continues catchup.
    """
    from .composition import create_postgres_services
    if not 1 <= limit <= 1000:
        raise StorageValidationError('Invalid recurring dispatch budget.')
    selected = policy(database, scope)
    if selected['authority'] != 'worker':
        return []
    today = business_today(selected['time_zone'])
    cutoff = date.fromisoformat(str(through_date)) if through_date is not None else today
    if cutoff > today:
        raise StorageValidationError('Worker reconciliation cannot generate future business dates.')
    service = create_postgres_services(database, scope).recurring
    queue = JobQueue(database, scope, recurring_registry(), service_id=service_id)
    identities = []
    # Sort oldest due first, so a large entity cannot starve catchup schedules.
    rows = sorted(service.list(fresh=True), key=lambda row: (row.get('next_due_date') or '9999', row['id']))
    for row in rows:
        due = row.get('next_due_date')
        if row['status'] != 'active' or not due or due > cutoff.isoformat():
            continue
        token = sha256((row['id'] + '\0' + due + '\0' + cutoff.isoformat()
                        + '\0' + row['baseline'] + '\0' + str(selected['revision'])).encode()).hexdigest()
        identity = queue.enqueue('recurring.schedule', 'recurring:' + token,
                                 target_id=row['id'], business_date=cutoff, generation_revision=selected['revision'])
        with repository_operation(database, read_only=True) as connection:
            state = connection.scalar(text('SELECT state FROM jobs WHERE entity_id=:scope AND id=:id'),
                                      {'scope': scope, 'id': identity})
        # Terminal failures remain inspectable/retryable, and never consume the
        # dispatch budget repeatedly at the expense of unrelated schedules.
        if state in {'queued', 'running'}:
            identities.append(identity)
        if len(identities) >= limit:
            break
    return identities


def recurring_registry():
    registry = JobRegistry()

    def dispatch(database, execution):
        enqueue_reconciliation(database, execution.entity_id, service_id=execution.service_id)

    def reconcile(database, execution):
        from .composition import create_postgres_services
        if not execution.target_id or not execution.business_date:
            raise StorageValidationError('Recurring job target is missing.')
        # Deleted/paused/ended schedules and authority rollback are safe no-ops.
        selected = policy(database, execution.entity_id)
        if selected['authority'] != 'worker' or selected['revision'] != execution.generation_revision:
            return
        service = create_postgres_services(database, execution.entity_id).recurring
        token = _generation_revision.set(execution.generation_revision)
        try:
            with audit_context(database, replace(database._audit_context.get(), source='recurring.worker')):
                result = RecurringService.reconcile(service, as_of=execution.business_date, schedule_id=execution.target_id,
                                                    max_occurrences=100, raise_on_error=True)
                if result['attention']:
                    raise StorageValidationError('The recurring schedule requires attention.')
        finally:
            _generation_revision.reset(token)

    registry.register('recurring.dispatch', dispatch, independent_idempotent=True)
    registry.register('recurring.schedule', reconcile, independent_idempotent=True)
    return registry


class DurableRecurringService(RecurringService):
    def reconcile(self, *, as_of=None, **options):
        repository = self._repository
        if policy(repository.database, repository.entity_id)['authority'] == 'worker':
            identities = enqueue_reconciliation(repository.database, repository.entity_id, through_date=as_of)
            return {'generated': [], 'attention': {}, 'queued_count': len(identities), 'execution_mode': 'worker'}
        return super().reconcile(as_of=as_of, **options)


def check_generation_authority(connection, scope):
    """Called under the existing occurrence mutation boundary, before effects."""
    connection.execute(text('SELECT pg_advisory_xact_lock_shared(334,hashtext(:scope))'), {'scope': scope})
    selected = connection.execute(text('SELECT authority,revision FROM recurring_generation_policy WHERE entity_id=:scope'),
                                  {'scope': scope}).mappings().first()
    authority = selected['authority'] if selected else 'explicit'
    context = connection.scalar(text("SELECT current_setting('tabula.audit_context',true)::jsonb"))
    worker = context.get('actor_type') == 'worker' and context.get('source') == 'recurring.worker'
    if ((authority == 'worker') != worker
            or worker and _generation_revision.get() != selected['revision']):
        raise StorageConflictError('Recurring generation authority changed. Reload before reconciling.')
