# PostgreSQL mutations and loaded-record baselines

This is the initial implementation of [#253](https://github.com/Roklion/Project_Tabula_Rasa/issues/253)
under [EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It extends #244's database runtime; the supported commit units, canonical
relationships and concurrency semantics remain defined by
[ADR 0001](adr/0001-canonical-accounting-schema.md#operation-boundaries).
It prepares later PostgreSQL repositories and the #221 API without activating
PostgreSQL in the current Sheets/Streamlit application.

## Reuse and ownership

- Inspected `postgres/runtime.py`, the canonical migration/ADR, reference-data,
  transaction/journal and mileage ports/services, and their Sheets adapters.
  The runtime already owns shared connections and outer commit/rollback;
  services/domain modules already own normalization and bookkeeping decisions.
- Reuse that runtime through `postgres/operations.py`; extend existing ports
  with optional `expected` inputs instead of adding parallel mutation APIs.
  Sheets snapshots reuse the existing fresh row, lock and uncertain-write paths.
- New logic is limited to token transport, ordered aggregate locks, error
  translation, and database version triggers. These are concurrency mechanics,
  not a second domain workflow or generic CRUD framework. There is no new
  process-local lock or Sheets retry/reconciliation mechanism.

## Repository operation boundary

Compose all participating adapters with **the same `Database` instance**.
Use `repository_operation(database)` inside infrastructure for mutations and
`repository_operation(database, read_only=True)` for reporting snapshots.
Nested participating calls share the outer connection and cannot commit.
Repository code must not manually commit or create an independent connection
for participating payee/tag, source/projection or other coupled writes.
Services do not import connections, SQLAlchemy, Psycopg or these helpers.

Return a successful supported operation only after its outer context exits.
Callbacks run once, after fresh identity/baseline/reference validation.
Return nested mapped values only to the orchestrating outer operation, which
must not expose them as committed results before commit. Deferred checks can
fail at that exit. A caught nested failure poisons the operation; a later
outer exit fails rather than reporting success after rollback.

An occurrence creation or independent attention write uses
`repository_operation(database, require_outer=True)`. This refuses nesting in
an all-run transaction. Each committed occurrence can then enter `generated`;
a failed occurrence rolls back before attention writes or the next schedule.
#248 still owns the actual recurring adapter and best-effort attention policy.
Native primitive tests do not constitute its final cross-adapter verification.

Connection loss can leave commit status uncertain. The safe `unavailable`
result makes no rollback claim and does not retry. Domain adapters must classify
that outcome using stable operation/record identity before any safe resubmission;
no blind retry or unconditional successful-write readback is introduced here.

## Token and caller policy

`application.baselines.RecordBaseline` encodes an opaque `v1` string containing
entity, aggregate kind/ID, immutable persisted incarnation, and integer version.
It contains no SQL/ORM values and grants no authorization. #222 still owns
server-derived entity authorization. Tokens must be compared against the
server's selected entity and record, never used to select that entity.

Mapped PostgreSQL records return a `baseline` string from the **same snapshot**
as the loaded aggregate. `baseline_for(key, row)` builds it from infrastructure
metadata. `MileageTrip.baseline` carries the same optional metadata through
service normalization. Sheets records continue to return their existing shapes.

An edit/delete request carries the loaded baseline separately from changes:

```python
service.update(record_id, expected={"baseline": loaded_record["baseline"]}, name="New name")
```

The adapter locks all affected roots with `lock_aggregates(connection, keys)`
and then calls `check_baseline(key, locked_row, token, required=True)` **before**
any write or inline reference callback. A mismatched entity, kind, ID,
incarnation or version raises `StorageConflictError(code="stale")`. Absence
raises `StorageValidationError(code="baseline_required")`; malformed tokens
fail validation. A baseline from before delete/recreate remains stale even if
the domain ID and version are reused. Do not reread on submit to manufacture
a new baseline: it must describe the record the user loaded.

| Caller / port | Policy |
| --- | --- |
| #221 supported commercial interactive edit/delete/bulk/merge | Require the loaded token, or a complete normalized expected snapshot enforced by the adapter under the same locks. Propagate it through load response, form state and mutation request separately from editable fields. |
| Account update/rename/deactivate; Category update/delete (#245) | Additive optional `expected` transport implemented. No account-delete port is added. Sheets accepts complete loaded snapshots. |
| Mileage edit/delete (#250) | Additive optional `expected` transport and returned token metadata implemented. Sheets accepts complete loaded trip snapshots. |
| Payee/Tag/Transaction optional `expected` paths (#245/#246) | Existing transport retained; commercial composition/callers must require their loaded baseline. Omission remains legacy/internal only. |
| Journal edit/delete (#246) | Existing required `expected` input retained. PostgreSQL maps the entry token or complete normalized entry/posting snapshot. |
| Other owner/source ports (#248/#249/#251/#252) | Apply the same aggregate convention in their adapters and extend typed metadata where their implemented read models need it. |
| Legacy/internal calls without `expected` | Preserve fresh locks, domain/reference checks and existing results; do not claim stale-form detection. Services omit the newly added keyword for this calling path to preserve older internal ports. |

For existing full snapshots, the domain adapter compares normalized persisted
fields and relationships, excluding derived display labels/totals/next-due and
attention fields. A partial expected record is insufficient for a commercial
guard. This foundation does not implement SQL/domain snapshot projections;
#245–#252 own those mappings. The token path covers database metadata without
embedding SQL columns in services.

The new Sheets account comparison includes ID, name, type, classification,
opening balance, active, creation timestamp and parent ID. Category comparison
includes ID, name, kind and parent ID. Mileage comparison includes every stored
trip field, including sorted tag IDs and creation timestamp, excluding resolved
tag names. Comparisons normalize decimal and boolean representations. They run
against the existing fresh row while holding the workbook's existing lock.
They do not add tokens/columns to frozen workbook format 13, and do not change
current Streamlit form behavior or upgrade existing optional snapshot semantics.
Snapshot equality cannot detect an edit/revert or recreation with identical
persisted values; PostgreSQL incarnation/version tokens provide that protection.

## Locking and version advancement

Lock the complete affected root set before details and callbacks. The helper
orders keys by entity, infrastructure table name and ID, independently of client
selection order. Hierarchy mutations first acquire the existing database entity
guard, matching the canonical hierarchy triggers. Include merge sources/targets,
mixed owners/projections and asset roots when an operation can affect them.
Do not discover additional earlier-order roots after already taking later locks;
domain adapters must construct their supported operation's set deliberately.
These are database row locks, not authorization or process-local workbook locks.
See PostgreSQL's [row locking and deadlock guidance](https://www.postgresql.org/docs/current/explicit-locking.html).

Lock existing roots, not absent create IDs. Prepare stable new IDs/incarnations
before creation and let unique constraints arbitrate collisions. Use constraints
for uniqueness and entity-qualified references. When a supported domain check
depends on a reference's active/type/classification fields staying unchanged
until commit, the adapter must also take an appropriate database reference lock
in its consistent operation order. `FOR SHARE` protects those field reads;
`FOR KEY SHARE` only protects keys/deletion and is insufficient for that check.
Do not replace these targeted checks with a whole-ledger lock or graph snapshot.

Revision `0002_aggregate_versions` leaves the frozen baseline migration intact:

- Business-field root updates advance `version` and `updated_at`; no-op updates
  do not. Explicit counter decreases/jumps are rejected. Attention code/time
  changes update the schedule timestamp without advancing its editable baseline.
- Posting, entry-tag and document-link changes advance their entry; changes to
  owned entries propagate to mixed sources/assets. Source, schedule, asset and
  mileage tag joins advance their owners. Asset overrides/events advance assets.
- Document links advance document and target baselines; import attribution
  advances batch and entry/mileage targets. Relationship repointing invalidates
  both old and new owners. Reference display-name changes advance only that
  reference, not every referring accounting record.

A counter can advance multiple times during one operation, including creation.
Consumers require equality, not a particular increment or initial counter.
Build the returned baseline after all participating detail writes, using the
same transaction; a root `RETURNING` value captured before details is obsolete.
This is an in-transaction mapping read, not post-success verification. Counters
and changes roll back together. Downgrading this revision removes its machinery
but preserves records/counters; the existing explicit downgrade gate still applies.

## Safe failures and remaining acceptance

`repository_operation` translates raw/nested/deferred provider failures into
existing neutral errors, with a stable `code` and no provider exception context:

| Code | Application exception |
| --- | --- |
| `duplicate`, `concurrent_write`, `stale` | `StorageConflictError` |
| `reference`, `invariant`, `required`, `read_only`, baseline validation | `StorageValidationError` |
| `unavailable`, `operation_aborted`, `boundary_mismatch`, other infrastructure failure | `StorageError` |
| Missing selected-entity aggregate | `StorageNotFoundError(code="not_found")` |

Provider messages, SQL, parameters, constraint DETAIL and private record values
are never interpolated into these errors. Domain repositories can add safe
domain-specific guidance without retaining the provider error.

Native tests cover independent loaded callers, a later stale update/delete,
an overlapping writer, incarnation/scope checks, versioned detail/link changes,
inline accounting atomicity, isolated occurrence commit units, migration
downgrade/reupgrade, and safe nested failures. Existing native catalog tests
verify entity-qualified FKs across all 26 tables. Sheets tests cover optional
baselines, no-baseline compatibility, failure before inline tags, normalization
and two-workbook isolation.

**#253 remains open.** #245–#252 have not supplied their PostgreSQL adapters on
this foundation. Remaining work is their actual boundary/baseline/read-model
integration and cross-adapter concurrent verification; specialized mixed-use
complete/inspectable relationships, recurring target/provenance/history rules,
asset override/committed-event protections, and allowed document/import targets;
plus #221's required commercial caller propagation. Occurrence provenance and
other secondary relationships must be covered as their supported adapters land.
Each adapter must enforce its supported invariants from its first release.
This slice does not satisfy #258's production activation gate, #257 migration
acceptance, #259 recovery rehearsal or #260 complete entity export.
