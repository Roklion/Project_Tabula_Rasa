# Durable jobs and bookkeeping history

Issues [#333](https://github.com/Roklion/Project_Tabula_Rasa/issues/333) and
[#335](https://github.com/Roklion/Project_Tabula_Rasa/issues/335) deliver the
independent operations foundations under [EPIC #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Forward-only migration `0011_operations` extends the retained `0010` chain.
Run the normal explicit migration command before deploying this revision.
Schedule an operator migration window: the migration drains and blocks audited
table writers before recording the activation watermark, and holds those locks
through baseline capture and trigger installation. Reads may continue; pause old
application writers until the compatible audited runtime is deployed.
The commercial HTTP runtime starts and serves page loads without scheduler or
recurring mutations. The legacy internal Streamlit initialization route retains
its existing reconciliation; #334 owns the supported recurring worker integration.

## Reuse and ownership

The existing `Database.transaction`, repository operation, aggregate locks,
loaded baselines and canonical accounting writers remain the mutation owners.
Transaction, journal, reference, mileage, recurring, asset, document and import
services retain their existing validation and business rules. SQL capture uses
those canonical tables; it adds no accounting engine or Sheets audit worksheet.
HTTP service composition extends the existing server-authorized context and
request ID. Workspace bootstrap supplies its existing named actor.

The only new state machine owns queue execution and attempts. It does not
duplicate recurring occurrence state, depreciation calculation, document recovery,
import deduplication or remote-write reconciliation. #334 owns integration of
recurring reconciliation, including its independently committed occurrences;
#336 owns period locks/correction policy. No period-lock semantics are introduced.

## Jobs: supported effect boundary

`JobRegistry.register` is the single trusted source-code registration boundary.
A handler receives the shared database and an immutable `JobExecution` containing
the server-selected entity, job ID, stable idempotency key and worker service ID.
It invokes the existing services with that entity and stable domain record IDs.
The queue stores no arbitrary payload, credentials, Python module name or browser
session. Job rows cannot choose handler code or service identity.

The default supports **short, atomic, same-database effects**: the worker opens
one transaction and participating repositories join it. A second explicit
registration option, `independent_idempotent=True`, supports existing services
that already guarantee stable identities and safe replay after partial commits.
That service receives a separate one-connection participant against the exact
same database while the worker retains the job-row execution fence. Its existing
outer transaction boundaries stay intact; each committed service mutation keeps
its same-transaction audit event. A failed job may therefore have committed
partial effects, and replay must confirm them through the existing service's
idempotency rules. The scheduler does not simulate rollback or invent those rules.

External provider writes, browser impersonation and handlers that swallow failed
operations are outside both contracts. A service requiring an independent outer
transaction must explicitly select the idempotent option. Native tests prove
`RecurringService.reconcile` works through it after a failure following committed
occurrences. #334 still owns the production handler, budget, due-schedule selection
and classification of returned attention/failure results; returning a domain
failure as ordinary success is not a valid handler. Future document/import/export
delivery must declare its stable-effect contract before registering.

`job_definitions` stores interval, next due time and pause state. `jobs` is the
durable run, uniquely keyed by entity and idempotency key. `job_attempts` stores
each claim, worker identity, start/finish and fixed outcome code. There is no
additional Redis broker, scheduler daemon or application transaction manager.

1. A bounded scheduler tick locks due definitions with `SKIP LOCKED` and atomically
   materializes one job per definition's due slot. After downtime it coalesces
   missed ticks into one catchup invocation and advances to the next interval.
   A workload owns actual domain catchup, rather than the scheduler inventing
   historical bookkeeping occurrences.
2. A worker claims one due run using `FOR UPDATE SKIP LOCKED`, commits its lease
   and records an attempt. Default lease is 60 seconds, configurable 1–3,600.
3. Execution locks that run and checks the exact unexpired lease. That transaction
   lock is the exclusivity fence, including after the wall-clock lease expires.
   Reclaimers skip a live execution. Statement timeouts are 30 seconds. Atomic
   execution also has a 30-second idle-in-transaction timeout; independently
   committing services disable that idle timeout on their orchestration connection
   so its fence survives participant work. Handlers must be bounded and must not
   do external I/O.
4. For atomic handlers, effects, audit events, successful attempt and job success
   commit together. For independently committing services, each effect/event pair
   commits through that service, and job success is recorded only after it returns
   successfully; stable domain identities prevent duplicate effects after a crash.
   Repeated/obsolete claims cannot repeat committed atomic effects.
   If the commit response is lost, one fresh locked status read accepts committed
   success; otherwise it records a safe retry/failure. A database outage can leave
   a run unconfirmed until lease recovery; it never justifies a blind external
   side effect or an unbounded readback loop.
5. Process death before execution leaves an expiring claim; death during atomic
   execution rolls back its effects. Independently committed effects remain for
   idempotent service confirmation. A later worker records `lease_expired` and reclaims,
   subject to the original attempt budget. No heartbeat thread is required while
   the transaction lock is held.

Only sanitized database unavailable/concurrent-write failures retry automatically.
Backoff is `min(300, 2 ** attempts)` seconds; default attempt budget is three,
with a hard maximum of ten. Domain/validation errors, unknown handlers and other
exceptions become `poison` in `dead` state. They do not block healthy runs.
Diagnostics expose fixed codes and operational IDs/times, never exception text,
idempotency keys, ledger values or credentials. Inspection includes both run
status and attempt history. Dead runs remain available for operator inspection.

Pause prevents definition materialization and queued/reclaimed claims; an already
executing transaction finishes. Resume preserves the next due time for catchup.
Cancel fences a queued or abandoned claim, records a cancelled attempt, and waits
for an executing transaction; it cannot undo success. After fixing the cause,
explicit operator retry grants one additional attempt to a dead run, up to ten,
preserving identity/history. Do not delete and recreate a job to bypass deduplication.

## Operator entrypoints and manual hosted checkpoint

Use the isolated environment and a separately approved target. Database settings
and secret handling follow [PostgreSQL operations](POSTGRESQL.md). The CLI never
prints database URLs and never creates a schema or selects an entity implicitly.
Read diagnostics with:

```powershell
python -m tabula_rasa.infrastructure.postgres.job_cli inspect --entity SYNTHETIC_ENTITY --service-id staging-operator
python -m tabula_rasa.infrastructure.postgres.job_cli attempts --entity SYNTHETIC_ENTITY --service-id staging-operator --id JOB_UUID
```

Only `ledger.probe` is registered in the shipped operator command. It reads the
existing ledger service without producing accounting changes; it exercises durable
queue execution. After approving the exact synthetic database/entity, an operator
may use these explicit mutations for staging:

```powershell
python -m tabula_rasa.infrastructure.postgres.job_cli enqueue-probe --entity SYNTHETIC_ENTITY --service-id staging-worker --id probe-1 --allow-mutations
python -m tabula_rasa.infrastructure.postgres.job_cli define-probe --entity SYNTHETIC_ENTITY --service-id staging-worker --id hourly-probe --interval-seconds 3600 --allow-mutations
python -m tabula_rasa.infrastructure.postgres.job_cli tick --entity SYNTHETIC_ENTITY --service-id staging-worker --budget 5 --allow-mutations
```

`pause`, `resume`, `cancel` and `retry` use the same explicit entity, service ID,
`--id` and mutation flag. Each invocation exits after a bounded budget (1–100
ticks). Exit failure instructs inspection of durable status before retrying.
The flag is an execution guard, not proof of human approval or membership.
No HTTP job-control route is added. Future member-triggered creation must use
the existing #313 capability/membership resolver before selecting entity/service;
role membership alone never provisions a platform worker.

| Stage | Selected execution ownership |
| --- | --- |
| Development | Explicit local CLI against disposable PostgreSQL; no hosted schedule. |
| Staging / restricted technical alpha | Manual bounded invocation first. If periodic execution is needed, an operator-approved OS/NAS timer invokes the CLI with a private staging URL and exact synthetic entity. A stopped timer delays work until catchup; this is not an uptime guarantee. |
| Commercial background execution | Evaluate a bounded Render cron invocation against accepted latency/capacity/recovery objectives. A paid always-on worker is optional if later workloads justify it. #334 supplies the first real recurring handler; #342 supplies readiness evidence; #224/#298 retain launch/activation authority. |

Provider facts checked October 16, 2026: [Render Free](https://render.com/docs/free)
web services sleep after 15 idle minutes and do not offer free worker/cron types.
[Render cron](https://render.com/docs/cronjobs) uses UTC schedules, exits per
invocation and has a $1 monthly minimum per cron service plus metered compute.
An HTTP keepalive is not a scheduler. [Neon plans](https://neon.com/docs/introduction/plans)
list Free compute/storage quotas and five-minute suspension; frequent polling
can prevent suspension. Estimate usage using actual duration/frequency, event
growth and database capacity, and confirm the account's current limits before
selecting a cadence. No paid plan, always-on compute or provider scheduler is assumed.

**Manual setup/approval remains required:** approve the exact environment and
entity allowlist, responsible operator, release image/branch, handler inventory,
timer/cron owner and cadence, spend/compute/storage limits, protected secret
injection, narrow runtime DB role, missing-run/dead-run alert destination and
staging crash/retry drill. Install runtime dependencies, migrate with a separate
owner role, configure a low pool size and run the synthetic probe. Verify provider
run history and `inspect`/`attempts`, and test stopping/resuming the timer. Record
the evidence before enabling any real workload. Secrets belong in the operator's
protected environment/provider secret store, never commands, logs or Git.
This change provisions no scheduler, installs no hosted secrets and activates
no production writes.

## Atomic audit contract

The guarantee covers **application-service-mediated PostgreSQL mutations after
activation**. Ledger and matching events commit in the same transaction: audit
failure aborts bookkeeping; bookkeeping failure leaves no phantom audit event.
Deferred capture reads final canonical state and coalesces intermediate/detail
version updates into one event per operation/entity/table/primary key. Replacing
postings produces logical updates, rather than misleading delete/create pairs.
An operation can legitimately contain many target events. No-op replay through
existing domain identities creates no new event. Reusing a committed operation
ID for a new change to the same target fails rather than silently dropping history.

| Field | Contract |
| --- | --- |
| `event_id`, `schema_version` | Stable generated UUID, event schema 1. |
| `operation_id` | New UoW ID by default; stable `job:UUID` for an atomic job. Independently committing services retain one ID per UoW and share the job correlation ID. Import record/batch identities remain the existing canonical identities. |
| `entity_id`, `organization_id` | Selected entity and its persisted organization when known; no invented organization for old internal entities. |
| `occurred_at`, `sequence` | UTC database instant and ordering key. Sequence gaps are normal after aborted transactions. |
| `actor_type`, `actor_id` | Named user ID from authorized HTTP context, explicit worker service ID, approved operator ID, or truthful `system/internal-application` for internal/shared-password paths. Never retrospectively attribute a historical human. |
| `correlation_id`, `source` | Server request ID and registered route operation, job ID/`job`, or explicit internal/operator source. No client-provided actor. |
| `action`, `target_type`, `target_key` | Create/update/delete of canonical table and typed primary-key components. Account deactivation/reactivation is an update to `active`; existing domain rules still decide allowed removals. |
| `before_summary`, `after_summary` | Allowlisted IDs, financial measures, classifications, dates/status/provenance; `_redacted` marks intentional minimization. Text-only corrections still advance version. |
| `batch_id` | Stable import batch/chunk where applicable; import events include source, committed count and first/last accepted source positions. |
| `after_digest`, `transaction_id` | Internal final-state reconciliation and same-UoW coalescing aids. They are not cryptographic tamper evidence or an independent historical source. |

Captured tables cover transaction/journal roots and postings; mileage; account,
category, payee and tag changes; relationship repoints during reference merges;
mixed-use records; recurring definitions/occurrences; assets/overrides/depreciation;
document metadata and receipt link/unlink; import batches/records and migration-run
administration. Free-text names, memos, references, addresses, filenames, provider
locators, private bytes and credentials are excluded. Receipts remain external;
unlink events do not delete bytes. Implemented corrections use existing updates
and new immutable history. Future close/unlock/restore workflows must join this
transaction contract when implemented, not invent unsupported current actions.

CSV/QuickBooks transaction and QuickBooks mileage imports already commit at most
1,000 source rows per atomic submission. Each committed batch, record, canonical
target and relationship has matching evidence. Retries reuse canonical IDs and
produce no duplicate history. A failed submission rolls back its ledger/events.
Larger files remain explicitly split submissions. `AuditReader.import_status`
accepts the caller's expected stable chunk IDs and reports complete, partial or
unconfirmed with committed counts and missing chunks. A failed/unknown chunk does
not erase earlier committed chunks or manufacture an all-or-nothing claim.
Retain the import plan/IDs; preview and inspect unconfirmed chunks before resuming.
An absent event cannot establish whether a submission was attempted; worker attempt
failures are separately visible in job history. No raw rejected contents are retained.

## Inspection, immutability, retention and recovery

`AuditReader(database, authorized_entity, capabilities=...)` requires the separate
`audit_inspect` platform policy. Ordinary bookkeeping read/export rights do not
grant it. `query` supports time range, organization, actor, action, source, target
type/ID, batch and operation filters, with bounded keyset pages. For consistent
multi-page inspection, keep calls within `reader.operation()`'s repeatable-read
snapshot. A sequence cursor alone is not a live change-feed guarantee: concurrent
transactions can commit in a different order. #341 owns the restricted UI and
ongoing caller authorization; #345 owns permitted customer export. Ordinary
telemetry and canonical v1 exports exclude audit content and job tables.

Database triggers reject event update/delete/truncate and direct inserts.
Row-level read policies scope non-owner roles to a server-selected reader entity;
the read contract also includes an explicit entity predicate for owner connections.
Deploy with a separate migration/function-owner role and a runtime role that has
only canonical bookkeeping DML and required job DML; **no audit INSERT/UPDATE/
DELETE/TRUNCATE, DDL, schema CREATE, trigger bypass, table ownership or BYPASSRLS**.
Grant SELECT on `audit_events`, `audit_baseline` and `audit_activation` only to the
separately provisioned inspector role (plus selected canonical SELECT for verification). Context
settings and capabilities are server infrastructure, never browser claims.
DB owners/superusers can bypass these controls, as PostgreSQL documents in its
[row-security model](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
This is append-only application history, not protection against a malicious DBA.

Direct old Sheets edits, pre-activation transactions and out-of-band administrator
SQL are outside the historical guarantee. The activation watermark and immutable
`audit_baseline` identify pre-existing records without invented create events or
actors. `verify()` checks live canonical rows against their latest event or that
baseline, including deleted targets, and emits counts/status only. It detects
missing/stale current-state evidence; it is not a complete history-chain proof.
`boundary()` returns the original activation instant and unavailable-history
marker for an entity or selected target. Later edits never remove that marker.
Attention timestamps are operational fields, not bookkeeping edits. The verifier
must preserve this exclusion when comparing current-state evidence.

Retain all audit/baseline/activation and job history by default; no expiry, pruning
or deletion API is installed. Pending #346 owns accepted retention/legal holds
and any separately approved redaction process. A hold therefore has no automatic
expiry path to override in this version. Sensitive-field minimization happens
before storage; do not silently rewrite old events for future redaction requests.
Customer content/access policy and storage capacity require #346's acceptance.

Database dump/PITR recovery must retain these tables, functions, triggers, sequences,
policies and the original activation watermark. An older recovery point loses
later history along with later bookkeeping; an internally consistent old state
does not prove the missing tail never existed. Record the restore point, unavailable
interval and independently retained evidence; never reset the watermark or backfill
fictional actors. #342 owns full archive/PITR restoration acceptance; older #259
drills and the existing bookkeeping-only recovery verifier do not establish audit
history recovery. #346 owns retention/legal hold interpretation after disaster recovery.

Legacy #15's Sheets mechanism is retired. Its atomic history, identity, domain/
import coverage, retry/concurrency, minimization, inspection and integrity objectives
map to this contract/tests; authorized UI/export, retention and real restore evidence
retain owners #341/#345/#346/#342. Closing that legacy route never certifies those
separate launch outcomes.

## Validation

Native tests in `tests/postgres/test_jobs.py` and `test_audit.py` cover competing
workers, abandoned claims, fencing, rollback, lost commit responses, retry budgets,
poison isolation, pause/resume, entity boundaries, named attribution, append-only
tamper attempts, RLS, pre-activation gaps, imports and current-state reconciliation.
Affected repository/HTTP/export tests continue to exercise existing success/failure
and accounting behavior. Use disposable PostgreSQL and synthetic records only;
CI's current-revision `Full test suite` remains the authoritative full-suite gate.
