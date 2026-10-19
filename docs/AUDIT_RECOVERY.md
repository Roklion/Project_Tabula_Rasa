# Audit-aware PostgreSQL recovery verification

This is #342's bounded #335 recovery procedure. It extends
[#259 managed recovery](POSTGRESQL_RECOVERY.md) and
[#294 encrypted NAS archives](NAS_POSTGRESQL_BACKUP.md); it adds no backup system,
production restore command, history reconstruction or retention cleanup.
The companion #346 audit policy records the interim owner decision; its statutory
and commercial decisions remain separate.

## Reuse and verification contract

`audit-capture` and `audit-verify` extend `scripts/verify_postgres_recovery.py`.
They reuse `AuditReader`, its capabilities/entity scope and current-state
integrity check, the canonical export snapshot/validators, existing endpoint
fingerprints and private no-clobber artifact writer. `audited_keys` shares the
known capture inventory between current-state and archived-revision checks.
No new mutation/retry workflow or public customer export route is introduced.

One REPEATABLE READ, read-only transaction captures each entity's canonical
bookkeeping, full ordered audit-event hash/count, baseline hash/count, activation
watermark, schema and original ordering state. Hashing includes every event field:
UUID/sequence, actor/org/entity, operation/batch/correlation, summaries/digests,
time and transaction ID. PostgreSQL jsonb text preserves numeric precision.
It streams history rather than keeping all events in application memory.
The private manifest contains comparison hashes/counts, not event rows; it still
contains sensitive scope/binding information and belongs outside Git/logs.

The schema fingerprint covers audited and audit tables/columns, constraints,
indexes, enabled triggers, RLS/policies, sequence definition and public functions
(including capture/period dependencies), owners and effective default/explicit
table/function ACLs. Audit capture/immutability triggers, scoped-read policies,
RLS and sequence presence are required even when building the source oracle.
The verifier also runs the shared current-state reconciliation, including #336
period/correction evidence and #341 support history at applicable revisions.
Matching an Alembic revision alone is insufficient.

Supported archived revisions are `0013_accounting_controls`,
`0014_document_locations` and `0015_support_controls`, with exact expected revision
matching. Pre-activation revisions report `audit_history_unavailable`; other
unsupported revisions stop with `audit_schema_unsupported`. Use their retained
compatible release/tooling in isolation. Never migrate or stamp a target before
verifying the original point. A separate forward-upgrade test proves original
event identities and activation/baseline survive; it does not convert unavailable
history into captured events. No permanent startup conversion is added.

Sequence values can contain gaps after rollback or advance during logical dump
cache handling. A sequence must be at least the highest retained event sequence
and the expected sequence position, with valid called state. A harmless forward
advance is accepted; resetting behind retained evidence is rejected. Sequences
are not tenant-local; freeze **all** writers/jobs during capture and verification.

## Authorized operator procedure

1. Complete the existing #259/#294 exact source/target, role, secret-custody and
   artifact checkpoint. Use a separately approved new isolated target, never
   production/UAT or the configured live ledger. Retain provider/namespace lineage
   independently; endpoint hashes cannot prove it. Inventory every expected
   entity, including overlapping local IDs; this CLI checks one entity per call.
2. Use the compatible release and separately provisioned recovery/inspector DB
   role. It needs canonical and audit SELECT, sequence SELECT and catalog access
   with the correct RLS scope. Ordinary customer bookkeeping export is insufficient.
   The operator CLI supplies the fixed trusted audit capabilities; database
   privileges still enforce actual access. Do not expose it as an HTTP route.
3. Pause source writers, workers and migrations. Inject only the approved source
   into `TABULA_RASA_RECOVERY_DATABASE_URL` from protected custody. This command
   never reads `.env.local` or falls back to the application/test URL. Use `inspect`
   to retain the source fingerprint. For **each** expected entity capture:

   ```powershell
   python scripts/verify_postgres_recovery.py audit-capture --entity entity-alpha --output <private-directory>/alpha-at-point.json
   ```

   Retain the manifests independently from the backup under restricted ACLs and
   encryption. The writer refuses a repository path or existing file. Capture
   the actual managed snapshot or #294 generation while the same source is
   frozen. A manifest is a comparison oracle, **not a backup**; it cannot restore
   events. Resume only the approved workload after both captures finish.
4. For requested-point PITR, retain the intended point/LSN and controlled
   included/excluded commit evidence. After a distinct committed canary, freeze
   again and capture `alpha-after-point.json` on the **same source**. Failed writes
   consuming sequence numbers alone do not make a valid later-state control.
   Restore at the intended point through #259's provider procedure. A logical
   dump/template clone does not establish managed snapshot/PITR behavior.
5. For NAS, use #294's existing manifest/ciphertext check, protected decryption
   and `pg_restore` into a new empty isolated database. Preserve the retained
   generation and review ownership/ACL restoration, including any provider-only
   exceptions; never silently omit permissions to make verification pass.
6. Inject the isolated target's recovery URL, inspect its fingerprint and run:

   ```powershell
   python scripts/verify_postgres_recovery.py audit-verify --entity entity-alpha --expected <private-directory>/alpha-at-point.json --source-database-sha256 <source-fingerprint> --target-database-sha256 <target-fingerprint>
   # For requested-point PITR add:
   # --later <private-directory>/alpha-after-point.json
   ```

   Repeat for every expected entity. Any absent expected entity, wrong scope,
   invalid oracle, changed schema/protections, missing or altered older event,
   watermark/baseline drift, regressed sequence or ledger mismatch stops acceptance
   with nonzero exit and a fixed code. Retain the target and inspect privately;
   do not repair by deleting events, disabling protections or recreating actors.
7. Record requested/actual recovery point, known unavailable tail, activation
   boundary, source/target lineage, protected oracle/archive references, every
   entity result, role/grant exceptions, command/release and declaration-to-verified
   elapsed time. A pre-audit point has unavailable history; an older consistent
   point has no proof of the missing later tail. Never invent events/identities.

Only `status=matched`, `scope=entity_bookkeeping_and_audit`, counts, revision and
history-availability status leave successful verification. Errors expose fixed
codes. A matched entity does **not** attest a provider restore, independent
database-wide entity inventory, deployed runtime role, job queue readiness,
receipt bytes, malicious-DBA resistance, RPO/RTO or full-service readiness.
Use existing #259/#294 broader inventory/permission checks and #338 bytes recovery.

## Reproducible synthetic checks

Use the repository Python 3.12 development environment and a new loopback-only
PostgreSQL 18.6 container. Select only its synthetic test endpoint via
`TABULA_RASA_TEST_DATABASE_URL`; never use application credentials. Set
`TABULA_RASA_TEST_PG_CONTAINER` to that exact disposable container name/ID for the
real archive case. CI supplies its PostgreSQL service ID to this test; a local
run without the variable explicitly skips the archive case rather than passing it.

```powershell
python -m pytest tests/postgres/test_audit_recovery.py tests/postgres/test_audit.py tests/postgres/test_recovery.py tests/postgres/test_jobs.py tests/postgres/test_recurring_jobs.py tests/postgres/test_periods.py tests/postgres/test_entity_export.py tests/postgres/test_migrations.py tests/postgres/test_authorization_http.py tests/postgres/test_security_acceptance.py tests/test_postgres_recovery_cli.py tests/test_nas_postgres_backup.py tests/tooling/test_ci_workflow.py -q
ruff check .
git diff --check
```

The native tests reuse the existing disposable snapshot-clone fixture and stable
domain import/job handlers. The archive case invokes real `pg_dump -Fc` and
`pg_restore --single-transaction --exit-on-error` in the disposable service and
verifies a fresh empty database. It does not restore onto an existing database.
The existing [NAS developer harness](NAS_POSTGRESQL_BACKUP.md#developer-validation)
separately proves TLS, age encryption, restore and failed/corrupt archive handling.
That small client fixture does not contain canonical audit history. Together
these checks prove separate layers, not a real NAS audit-aware drill.

See [the dated evidence matrix](evidence/AUDIT_RECOVERY_2026-10-19.md) for executed
results and blocked operator prerequisites. CI `Full test suite` remains the
authoritative current-head/candidate merge gate.
