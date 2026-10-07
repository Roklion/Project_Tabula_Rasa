# Sheets to PostgreSQL migration framework

Implementation of #254 under EPIC #220 and commercialization initiative #124.
The framework starts from dependency PR #266 at `aeee01eb` and consumes the
merged #243 canonical model, #244 runtime, #253 integrity rules, and #261 frozen
format-13 source contract.

## Reuse and ownership

- Source schema: `storage/google_sheets/schema.py` owns exact headers. The
  existing source table validators own hierarchy, references, journals,
  recurring provenance, mixed pairs and depreciation history.
- Domain normalization: existing reference, transaction, recurring, asset and
  accounting-posting rules retain ownership; migration does not replay jobs.
- Target writes: the shared PostgreSQL Database, reference value builders and
  accounting line writer own SQL boundaries and canonical posting construction.
- New logic: read-only extraction, private frozen snapshots, deterministic
  mappings, dependency-complete units, run metadata and checkpoint orchestration.
  Specialized loader registration is the extension point for #255/#256.
- No parallel runtime recovery or accounting state machine is introduced.

## Initial schema decision

On 2026-10-05 the operator confirmed that only disposable development/test
databases have used revisions `0001_canonical`–`0003_domain_integrity`; no
persistent staging database exists. Consolidate these pre-production revisions
into one initial baseline before provisioning staging. Git preserves their
original implementation history. Never stamp an old database to the new
baseline. Recreate only an explicitly confirmed disposable target; preserve
any unexpectedly retained database and investigate before proceeding.

Persistent staging provision and a representative rehearsal remain required
before #254 acceptance. #257 owns whole-profile acceptance; #258 owns authority
switching. Matching core totals and local disposable tests do not authorize
cutover. #259 recovery and #260 complete export remain independent gates.

The initial baseline is `0001_initial`; the current head is the forward
`0004_mileage_order` revision from #250. The baseline's four SQL assets preserve the existing
canonical definitions, balance/hierarchy checks, aggregate-version triggers and
domain/history enforcement. The mapping table additionally records original
source update timestamps. The original revision modules are removed from the
active chain; zero-to-head, repeat upgrade, all current guards, downgrade/rebuild
and two-entity behavior are tested against native PostgreSQL.

Parallel #248–#252 implementations can proceed. If they need a schema change,
add a coordinated forward revision after `0001_initial`; adapter code alone need
not add a revision. Before initializing retained staging, integrate required
schema changes and inspect the exact head. After a retained deployment, the
baseline is immutable. Do not regenerate it to absorb later repository work.

## Operator procedure

Install the development/PostgreSQL dependencies. Use the existing approved
profile configuration and human Google OAuth grant; do not copy credentials
into commands or repository files. Pause source edits and recurring/asset jobs
for the extraction/load window. Sheets provides no cross-worksheet transaction;
the operator-maintained source freeze is required for a coherent snapshot.

Run from the repository root:

```powershell
python scripts/migrate_sheets_to_postgres.py --profile alpha --entity rehearsal-alpha
```

Dry-run is the default. It opens only the selected final-format live workbook
through `from_secrets_read_only`, consumes the shared exact-header validator,
validates domain/reference/provenance relationships, creates a private in-memory
frozen snapshot and plans every source row. It never initializes Sheets, creates
a PostgreSQL pool or writes run metadata. Backup archives are not accepted.
Unsupported/retired schemas fail before either source-ledger or target writes.
Record and reference identifiers must be unpadded; fix surrounding whitespace
in the source privately before extracting a new snapshot.

The JSON report contains versions, opaque run/digest identifiers, unit counts,
missing loaders and explicit provisional acceptance/cutover=false fields. It
contains no amounts, balances, descriptions, names, receipt content or secrets.
Errors expose fixed diagnostics and worksheet/row coordinates only. Snapshots
and unit reprs hide their contents. No private snapshot is automatically written
to disk, logged or committed.

Use `--secrets <approved-path>` only to select a different approved configuration
file. Profile selection is required; the tool has no selected-profile fallback.
Source workbook identity must match that explicit binding. Target entity scope
is mandatory on every SQL operation and relationship. These operator settings
do not grant commercial tenant membership or permission.

After dry-run, provision/inspect an inactive, empty target and initialize its
schema separately with the PostgreSQL operator tools. Supply
`TABULA_RASA_DATABASE_URL` through approved secret injection. Then explicitly load:

```powershell
python scripts/migrate_sheets_to_postgres.py --profile alpha --entity rehearsal-alpha --load
```

The tool refuses a populated entity or one bound to a different profile,
workbook, snapshot, mapping or manifest. It can provision an entity root in an
already initialized database; it never upgrades schema, seeds defaults, resets
data, selects the live backend or dual-writes traffic. A new entity currently
uses its explicit target identifier as its ledger name; later onboarding/whole
profile loading can supply display identity through its owning contract.

## Determinism and unit extensions

Manifest/mapping version `1` is independent of Sheets format `13` and the
PostgreSQL revision. A run ID derives from versions + explicit
profile/workbook/entity binding + normalized source digest. Header order,
worksheet row order and extraction time do not change it. Financial values use
existing Decimal/domain normalization. Source creation times stay on canonical
records; missing category metadata uses the documented UTC epoch
`1970-01-01T00:00:00Z`. Original update times stay in
`migration_id_mappings.source_updated_at`. PostgreSQL aggregate `updated_at`
continues to record actual target mutations; its version/history triggers are
never disabled or bypassed. This is an explicit normalization difference for
#257 to reconcile.

Preserve original IDs within their valid target namespaces. When a simple entry
and journal share an ID, preserve the simple entry and deterministically remap
the journal to an unused UUID, recording the reason. Journal posting IDs stay in
their separate namespace; simple posting IDs use the existing shared expansion.
Historical ordinary generated occurrences may have UUIDv4 identities: the
original recurring caller calculated a UUIDv5 but did not pass the explicit
transaction identity into preparation. The application-service path corrected
that caller in `84893b0`. Migration preserves those existing UUIDv4 IDs rather
than rewriting the source or regenerating history. Schedule references, complete
provenance and unique occurrence dates remain mandatory; other generated-ID
mismatches remain rejected. This allowance belongs only to one-time extraction.

Mapping rows and unit hashes are persisted before loading and compared on every
restart. No historical batch/actor facts are invented.

Unit planning covers entity/references, ordinary entries, complete journals,
schedule foundations, recurring entries, mixed owners/projections/occurrences,
asset/acquisition/depreciation history and mileage. Each source row belongs to
exactly one unit. References precede owners; schedule precedes occurrence; a
complete acquisition unit precedes its asset/history unit. Missing dependencies
or cycles stop planning. Existing projections/events are preserved in each
unit, never regenerated by a scheduler or asset-posting service.

The representative loaders shipped here support foundation, ordinary/simple
entries, journals, schedules and ordinary recurring occurrences through the
existing canonical value builders and accounting line writer. #255 owns complete
core reconciliation; #256 owns mixed, asset, mileage and receipt/document loads,
including external/unreferenced receipt inventory. Receipt-bearing entries have
distinct required loader kinds and cannot silently use the receipt-free loader.
Missing complete-unit loaders are reported by dry-run and block a load before
any target mutation. Intentionally inspectable historical source states and
their reconciliation remain secondary-loader work; this initial preflight
accepts complete supported owner/projection relationships.

Register additional infrastructure loaders through
`PostgresMigrationRunner(database, loaders={unit_kind: loader})`. Each loader
implements `load(connection, plan, unit)` and
`verify(connection, plan, unit)`. The runner owns the outer transaction and
checkpoint; loaders must use the supplied connection, explicit entity scope and
`plan.target_id(...)`, preserve original owners/history, and never commit,
initialize schema, generate new occurrences or move document bytes.
`verify` compares committed target meaning with the frozen unit on an explicit
restart, including its references/details. A success response is authoritative;
the runner does not add post-success readbacks.

## Failure and restart

Run preparation and each complete unit commit atomically. A unit's bookkeeping
rows and `loaded` checkpoint share one transaction. A failed uncommitted unit
rolls back; prior units survive. Status records contain no financial payload.
The run remains `loading` while all units are loaded; this is framework evidence,
not the `validated` status reserved for the acceptance process in #257.

After a failure, keep source edits paused and rerun the same explicit command
against the same source/entity. Matching loaded units are verified and skipped;
pending units load once. A different source digest, identity map, checkpoint
manifest or altered/deleted committed target stops the run. There is no automatic
retry. An uncertain commit may already have its atomic checkpoint; explicit
restart inspects it instead of inserting a second entry.

If a source changed or target cannot be trusted, preserve the source and stop.
An operator may explicitly abandon/reset only a confirmed inactive rehearsal
target, then create a new run from a newly frozen source. The tool provides no
destructive reset command and never touches the configured live workbook.
After PostgreSQL becomes active, divergent-write recovery belongs to #258/#259,
not this restart procedure.

## Persistent staging checkpoint

Before #254 acceptance, the operator must provision a durable non-production
PostgreSQL database, separate from eventual production, with approved secret
injection and an explicit disposable rehearsal target. Verify current schema
initialization from zero and connectivity to the frozen live Sheets source.
Run a representative source-owned load/restart through the core path on that
environment and retain safe evidence. Local UUID test databases prove the code
path but do not meet this infrastructure checkpoint.

#254 remains open until that rehearsal exists. Secondary loaders, whole-profile
acceptance (#257), complete export (#260), recovery/PITR (#259) and authority
switching (#258) retain their separate initiative responsibilities.

On 2026-10-05 the operator explicitly deferred persistent staging setup and
requested that the tested implementation remain ready. No persistent target
or live Sheets rehearsal was provisioned/run in this implementation session.

## Implementation validation

Validated from the isolated issue-254 worktree using the project's existing
Python 3.12 development environment and real PostgreSQL 18.6 on the disposable
loopback test service. The test fixtures create/drop only synthetic UUID-named
databases; no operator database or real bookkeeping data was reset/read.

- `ruff check .` passed.
- `python -m pytest` passed all **1,538 tests in 86.76 seconds**, with native
  PostgreSQL coverage and no skipped tests.
- Working/staged diff checks passed; the committed branch is also checked
  against `origin/main`.
- Native framework coverage demonstrates stable source-owned recurring
  occurrences, complete/disjoint journal projections and ID collision mappings,
  atomic unit failure, explicit uncertain-commit restart without duplication,
  changed-source/target refusal, explicit schema initialization, and two-profile
  isolation. Planning coverage retains existing mixed/depreciation history and
  verifies acquisition dependencies and cycle refusal.
- Shared backup/source validation and the unchanged aggregate/history guards
  pass their existing regression suites. Zero-to-head/repeat initialization and
  explicit disposable downgrade/rebuild pass on the consolidated baseline.

Dependency PR #266 merged while implementation was underway. The branch
first integrated main `86988422`, whose tree matches the starting dependency
head `aeee01eb`. Before publication it also integrated main `2cca151f`,
including #247 reporting from PR #268, without conflicts. Its implementation
diff against current main remains scoped to #254.

The publication gate after that integration passed Ruff and all **1,564 tests
in 98.63 seconds**, with native PostgreSQL coverage and no skips. Working,
staged and committed-branch diff checks also passed. Persistent staging remains
deferred and is tracked as an unchecked acceptance item in #254.
