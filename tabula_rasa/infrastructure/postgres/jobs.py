"""Bounded PostgreSQL jobs with explicit same-database service effect contracts.

Claim leases survive process death; a transaction row lock fences execution.
Atomic handlers couple effects, audit and success. Independently committing
services must already guarantee stable effect identities and idempotent replay.
External side effects need their own delivery contract and are not supported.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from tabula_rasa.errors import StorageError
from .audit import AuditContext, audit_context
from .config import DatabaseSettings
from .runtime import Database, DatabaseError


class JobError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Job operation failed (' + code + ').')


@dataclass(frozen=True)
class JobExecution:
    entity_id: str
    job_id: str
    idempotency_key: str
    service_id: str


@dataclass(frozen=True)
class RegisteredJob:
    handler: Callable[[Database, JobExecution], object]
    independent_idempotent: bool


class JobRegistry:
    def __init__(self):
        self._handlers = {}

    def register(self, job_type, handler, *, independent_idempotent=False):
        """Trusted source registration; handler(database, execution) joins UoW.

        Never import code, choose a service identity or accept credentials from
        a job row. Handlers use existing application services, stable target IDs,
        and must not perform external I/O. Independently committing services
        require explicit registration and their own proven idempotency contract.
        """
        if (not isinstance(job_type, str) or not job_type.strip() or job_type in self._handlers
                or not callable(handler) or not isinstance(independent_idempotent, bool)):
            raise ValueError('Invalid job registration.')
        self._handlers[job_type] = RegisteredJob(handler, independent_idempotent)

    def handler(self, job_type):
        if job_type not in self._handlers:
            raise JobError('poison')
        return self._handlers[job_type]


class JobQueue:
    """Server-selected entity binding, never browser-session authority.

    Construct only in operator/worker composition after exact environment/entity
    approval. Member-triggered controls must first use #313 authorization.
    """
    def __init__(self, database, entity_id, registry, *, service_id):
        if not all(isinstance(v, str) and v.strip() and len(v) <= 200 for v in (entity_id, service_id)):
            raise ValueError('An explicit entity and service identity are required.')
        self.database = database
        self.entity_id = entity_id
        self.registry = registry
        self.service_id = service_id

    def enqueue(self, job_type, key, *, due_at=None, max_attempts=3):
        self.registry.handler(job_type)
        if not isinstance(key, str) or not key.strip() or len(key) > 200 or not 1 <= max_attempts <= 10:
            raise ValueError('Invalid job identity or attempt budget.')
        with self.database.transaction(require_outer=True) as connection:
            return self._enqueue(connection, job_type, key, due_at or datetime.now(timezone.utc), max_attempts)

    def _enqueue(self, connection, job_type, key, due_at, max_attempts=3, definition_id=None):
        params = {'scope': self.entity_id, 'kind': job_type, 'key': key, 'due': due_at,
                  'max': max_attempts, 'definition': definition_id}
        connection.execute(text('''INSERT INTO jobs(entity_id,job_type,idempotency_key,due_at,max_attempts,definition_id)
            VALUES (:scope,:kind,:key,:due,:max,:definition)
            ON CONFLICT (entity_id,idempotency_key) DO NOTHING'''), params)
        row = connection.execute(text('SELECT * FROM jobs WHERE entity_id=:scope AND idempotency_key=:key'), params).mappings().one()
        if row['job_type'] != job_type or row['definition_id'] != definition_id:
            raise JobError('identity_conflict')
        return str(row['id'])

    def define(self, identity, job_type, *, interval_seconds, first_due):
        self.registry.handler(job_type)
        if not isinstance(identity, str) or not identity.strip() or not 60 <= interval_seconds <= 31536000:
            raise ValueError('Invalid job schedule.')
        with self.database.transaction(require_outer=True) as connection:
            connection.execute(text('''INSERT INTO job_definitions(entity_id,id,job_type,interval_seconds,next_due)
                VALUES (:scope,:id,:kind,:interval,:due)'''), {'scope': self.entity_id, 'id': identity,
                    'kind': job_type, 'interval': interval_seconds, 'due': first_due})

    def schedule_due(self, *, limit=100):
        """One catchup job per due definition; no unbounded missed-slot fanout.

        A slot represents a service reconciliation up to its run time. #334 owns
        actual recurring occurrence catchup. This infrastructure invents none.
        """
        if not 1 <= limit <= 1000:
            raise ValueError('Invalid scheduler budget.')
        with self.database.transaction(require_outer=True) as connection:
            rows = connection.execute(text('''SELECT * FROM job_definitions
                WHERE entity_id=:scope AND NOT paused AND next_due<=clock_timestamp()
                ORDER BY next_due,id LIMIT :limit FOR UPDATE SKIP LOCKED'''),
                {'scope': self.entity_id, 'limit': limit}).mappings().all()
            for row in rows:
                key = 'schedule:' + row['id'] + ':' + row['next_due'].isoformat()
                self._enqueue(connection, row['job_type'], key, row['next_due'], definition_id=row['id'])
                connection.execute(text('''UPDATE job_definitions SET next_due=next_due +
                    (floor(extract(epoch FROM (clock_timestamp()-next_due))/interval_seconds)+1)
                    * interval_seconds * interval '1 second' WHERE entity_id=:scope AND id=:id'''),
                    {'scope': self.entity_id, 'id': row['id']})
            return len(rows)

    def pause(self, identity, *, paused=True):
        """Pause materialization and queued claims; executing transactions finish."""
        with self.database.transaction(require_outer=True) as connection:
            if not connection.scalar(text('''UPDATE job_definitions SET paused=:paused
                WHERE entity_id=:scope AND id=:id RETURNING id'''),
                {'scope': self.entity_id, 'id': identity, 'paused': paused}):
                raise JobError('not_found')

    def claim(self, *, lease_seconds=60):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid job lease.')
        with self.database.transaction(require_outer=True) as connection:
            row = connection.execute(text('''SELECT j.* FROM jobs j
                LEFT JOIN job_definitions d ON d.entity_id=j.entity_id AND d.id=j.definition_id
                WHERE j.entity_id=:scope AND (d.id IS NULL OR NOT d.paused)
                AND ((j.state='queued' AND j.due_at<=clock_timestamp())
                    OR (j.state='running' AND j.lease_until<clock_timestamp()))
                ORDER BY j.due_at,j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED'''),
                {'scope': self.entity_id}).mappings().first()
            if row is None:
                return None
            params = {'scope': self.entity_id, 'id': row['id'], 'lease': row['lease_id']}
            if row['state'] == 'running':
                connection.execute(text('''UPDATE job_attempts SET outcome='lease_expired',finished_at=clock_timestamp()
                    WHERE entity_id=:scope AND job_id=:id AND lease_id=:lease AND outcome='running' '''), params)
            if row['attempts'] >= row['max_attempts']:
                connection.execute(text('''UPDATE jobs SET state='dead',lease_id=NULL,lease_until=NULL,
                    failure_code='lease_expired',finished_at=clock_timestamp() WHERE entity_id=:scope AND id=:id'''), params)
                return None
            lease = uuid4()
            params.update(lease=lease, worker=self.service_id, seconds=lease_seconds)
            connection.execute(text('''UPDATE jobs SET state='running',attempts=attempts+1,lease_id=:lease,
                lease_until=clock_timestamp()+:seconds * interval '1 second',failure_code=NULL
                WHERE entity_id=:scope AND id=:id'''), params)
            connection.execute(text('''INSERT INTO job_attempts(entity_id,job_id,lease_id,worker_id)
                VALUES (:scope,:id,:lease,:worker)'''), params)
            return str(row['id']), str(lease)

    def execute(self, job_id, lease_id):
        """Return false for an obsolete/completed claim; never repeat its effects."""
        params = {'scope': self.entity_id, 'id': job_id, 'lease': lease_id}
        context = AuditContext('worker', self.service_id, 'job', self.entity_id,
                               operation_id='job:' + job_id, correlation_id=job_id)
        try:
            with audit_context(self.database, context), self.database.transaction(require_outer=True) as connection:
                connection.execute(text("SET LOCAL statement_timeout='30s'"))
                connection.execute(text("SET LOCAL idle_in_transaction_session_timeout='30s'"))
                row = connection.execute(text('''SELECT * FROM jobs WHERE entity_id=:scope AND id=:id
                    AND state='running' AND lease_id=:lease AND lease_until>=clock_timestamp()
                    AND (definition_id IS NULL OR EXISTS (SELECT 1 FROM job_definitions d
                        WHERE d.entity_id=jobs.entity_id AND d.id=jobs.definition_id AND NOT d.paused))
                    FOR UPDATE'''), params).mappings().first()
                if row is None:
                    return False
                registration = self.registry.handler(row['job_type'])
                if registration.independent_idempotent:
                    # This connection legitimately idles while its participant
                    # works. Keep the row-lock fence until that service returns.
                    connection.execute(text("SET LOCAL idle_in_transaction_session_timeout='0'"))
                execution = JobExecution(self.entity_id, job_id, row['idempotency_key'], self.service_id)
                self._invoke(registration, execution)
                # The lock remains held even past lease expiry. Reclaimers skip it;
                # a process crash rolls back both effects and this status update.
                connection.execute(text('''UPDATE jobs SET state='succeeded',lease_id=NULL,lease_until=NULL,
                    finished_at=clock_timestamp() WHERE entity_id=:scope AND id=:id'''), params)
                connection.execute(text('''UPDATE job_attempts SET outcome='succeeded',finished_at=clock_timestamp()
                    WHERE entity_id=:scope AND job_id=:id AND lease_id=:lease'''), params)
                return True
        except Exception as error:
            # No exception messages or arbitrary handler content enter diagnostics.
            code = 'transient' if isinstance(error, (DatabaseError, StorageError)) and error.code in {
                'unavailable', 'concurrent_write'} else 'poison'
        return self._fail(params, code)

    def _invoke(self, registration, execution):
        if not registration.independent_idempotent:
            registration.handler(self.database, execution)
            return
        # Keep the job-row fence on the orchestration connection. A separate
        # one-connection participant preserves existing service require_outer
        # boundaries against the exact same DB, with no browser context.
        participant = Database(DatabaseSettings(self.database.engine.url, pool_size=1, max_overflow=0))
        try:
            with audit_context(participant, AuditContext('worker', self.service_id, 'job', self.entity_id,
                                                       correlation_id=execution.job_id)):
                registration.handler(participant, execution)
        finally:
            participant.dispose()

    def _fail(self, params, code):
        # Also reconciles commit-with-lost-response: a committed success cannot
        # match running+lease, so it is never overwritten or retried.
        with self.database.transaction(require_outer=True) as connection:
            row = connection.execute(text('''SELECT attempts,max_attempts,state,lease_id FROM jobs WHERE entity_id=:scope
                AND id=:id FOR UPDATE'''), params).mappings().first()
            if row is None or row['state'] != 'running' or str(row['lease_id']) != str(params['lease']):
                return row is not None and row['state'] == 'succeeded'
            state = 'queued' if code == 'transient' and row['attempts'] < row['max_attempts'] else 'dead'
            connection.execute(text('''UPDATE jobs SET state=:state,lease_id=NULL,lease_until=NULL,failure_code=:code,
                due_at=clock_timestamp()+:backoff * interval '1 second',
                finished_at=CASE WHEN :state='dead' THEN clock_timestamp() ELSE NULL END
                WHERE entity_id=:scope AND id=:id'''),
                {**params, 'state': state, 'code': code, 'backoff': min(300, 2 ** row['attempts'])})
            connection.execute(text('''UPDATE job_attempts SET outcome=:code,finished_at=clock_timestamp()
                WHERE entity_id=:scope AND job_id=:id AND lease_id=:lease'''), {**params, 'code': code})
            return False

    def cancel(self, job_id):
        with self.database.transaction(require_outer=True) as connection:
            # Waits for any executing transaction; cannot undo a committed effect.
            changed = bool(connection.scalar(text('''UPDATE jobs SET state='cancelled',lease_id=NULL,lease_until=NULL,
                finished_at=clock_timestamp() WHERE entity_id=:scope AND id=:id AND state IN ('queued','running','dead')
                RETURNING id'''), {'scope': self.entity_id, 'id': job_id}))
            if changed:
                connection.execute(text('''UPDATE job_attempts SET outcome='cancelled',finished_at=clock_timestamp()
                    WHERE entity_id=:scope AND job_id=:id AND outcome='running' '''), {'scope': self.entity_id, 'id': job_id})
            return changed

    def retry(self, job_id):
        """Explicit operator recovery grants one additional bounded attempt."""
        with self.database.transaction(require_outer=True) as connection:
            return bool(connection.scalar(text('''UPDATE jobs SET state='queued',max_attempts=max_attempts+1,
                due_at=clock_timestamp(),finished_at=NULL WHERE entity_id=:scope AND id=:id AND state='dead'
                AND max_attempts<10 RETURNING id'''), {'scope': self.entity_id, 'id': job_id}))

    def diagnostics(self, *, limit=100):
        if not 1 <= limit <= 1000:
            raise ValueError('Invalid diagnostic budget.')
        with self.database.transaction(read_only=True) as connection:
            return tuple(dict(row) for row in connection.execute(text('''SELECT id,job_type,state,attempts,max_attempts,
                due_at,lease_until,failure_code,finished_at FROM jobs WHERE entity_id=:scope
                ORDER BY created_at DESC,id LIMIT :limit'''), {'scope': self.entity_id, 'limit': limit}).mappings())

    def attempts(self, job_id):
        with self.database.transaction(read_only=True) as connection:
            return tuple(dict(row) for row in connection.execute(text('''SELECT lease_id,worker_id,started_at,finished_at,outcome
                FROM job_attempts WHERE entity_id=:scope AND job_id=:id ORDER BY started_at'''),
                {'scope': self.entity_id, 'id': job_id}).mappings())

    def tick(self):
        self.schedule_due()
        claim = self.claim()
        return self.execute(*claim) if claim else False
