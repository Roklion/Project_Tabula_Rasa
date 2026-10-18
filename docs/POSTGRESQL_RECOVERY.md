# Managed PostgreSQL backup and point-in-time recovery

This is the operator contract for [#259](https://github.com/Roklion/Project_Tabula_Rasa/issues/259),
under [EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
[EPIC #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223) owns ongoing
monitoring, incident response, document recovery and retention. Neon is selected
by [ADR 0002](adr/0002-commercial-web-runtime.md); this guide does not select or
purchase a plan, provision resources, enable protection or execute a restore.

## Status and production checkpoint

The read-only verifier and rehearsal procedure are implemented. [#259](https://github.com/Roklion/Project_Tabula_Rasa/issues/259)
closed on 2026-10-07 for completed current-stage Neon Free managed-snapshot
restore and requested-point PITR, including two-entity content, schema/security
inventory and accounting verification. Production and UAT were distinct branches
in one project, with the production root as the drill source. Those recorded
results establish that controlled technical recovery evidence, not ongoing
commercial guarantees or a live bookkeeping authority switch. Reinspect settings
and capacity before each new operation; do not infer current protection from an
old drill or synthetic tests.

[#298](https://github.com/Roklion/Project_Tabula_Rasa/issues/298) retains commercial
protection/objective agreement, human evidence acceptance, operator handoff and
final commercial cutover. The [#299 owner-operated procedure](BOOKKEEPING_CUTOVER.md#owner-operated-production-procedure-299)
supports lasting use of the shared production application under explicit current
recovery limitations without requiring those commercial sign-offs or a provider
purchase. [#294](https://github.com/Roklion/Project_Tabula_Rasa/issues/294) owns NAS
backup automation and isolated restore verification. The standalone
[NAS backup tooling and operator runbook](NAS_POSTGRESQL_BACKUP.md) are implemented;
actual device enablement and retained-archive drill evidence remain required.
NAS protection cannot be claimed before it works; if the owner requires it before live writes,
complete it before that deployment. #299's technical closure is independent.
Database metadata/dumps do not establish receipt-byte or full-service recovery;
#223 retains that responsibility. Commercial evidence gates remain intact.

Before provider configuration or a production-derived rehearsal, the operator
must complete #259's manual setup checkpoint:

- Identify the actual production Neon project, root branch and database. Keep
  production and UAT on distinct branches/endpoints in the shared project,
  with separately scoped connection configuration and access controls per the
  current-stage amendment to ADR 0002. Verify the branch identities; do not
  substitute UAT or restore onto either retained source branch.
- Configure the approved production secret store, authenticated database roles,
  direct/unpooled TLS endpoint and reachable configuration. Verify actual TLS;
  do not publish connection strings, usernames, tokens or screenshots of secrets.
- Inspect the effective Free-plan history window (reported six hours, capped
  at 1 GB of history), manual snapshot availability/expiration and spare branch,
  storage and compute capacity for isolated targets. Stop if the requested point
  is no longer recoverable or capacity is insufficient. No paid schedule or
  seven-day window is a prerequisite for these current-stage drills.
- Approve exact isolated recovery targets and access controls. Production-derived
  branches contain private data: they are restricted recovery environments, not
  ordinary developer/staging branches or automatic production clones.
- Record the authorized drill scope, current limits, owner and date; identify
  a second operator with authorized console, secret-store and evidence access.
  Measure observed RPO/RTO honestly. The proposed commercial objectives below
  do not require approval before these limited drills, but remain unapproved
  until an explicit agreement is recorded before commercial activation.

If any item is missing, stop provider-specific work and request operator setup.
No schema reset, production overwrite, finalization, source edits, document
movement or cleanup is authorized by this document.

## Current Free-plan rehearsal boundary

The current goal is to complete a real managed **manual-snapshot restore** and
separate **requested-point PITR** within Free-plan capabilities. Retain the
manual snapshot and each isolated target/evidence through sign-off. Free allows
one manual snapshot; do not delete an existing required snapshot to make room
without separate approval. Plan both milestones while the requested point is
still available within the effective history window and its 1 GB cap. Confirm
capacity before creating targets; record a blocker rather than overwriting UAT
or production. The six-hour lookback is a recovery-point availability limit,
**not RPO**, a six-hour data-loss promise or proof that every point remains
available under the history cap.

No automated snapshot production, daily frequency, 14-day retention or seven-day
history evidence is required to execute these current-stage drills. A successful
drill records what the current plan recovered and how long it took; it does not
establish ongoing production protection or commercial readiness.

## Future protection and commercial objective agreement

The following numbers are **proposals for formal commercialization**, not approved
objectives or claims about Free. Under #220/#258/#223, before commercial
activation the operator must agree or explicitly revise the protection strategy,
capacity and RPO/RTO objectives, enable/inspect those agreed controls and obtain
matching recovery evidence. This includes reviewing environment isolation and
shared-project operational access/blast radius under ADR 0002. Keep proposed,
approved and observed values separately in private evidence. Current Free-plan
drills may proceed before that agreement and paid-plan procurement.

| Protection or objective | Proposed requirement |
| --- | --- |
| Managed snapshots | Automatic daily backup; retain each scheduled snapshot for 14 days. Explicit pre-migration/pre-cutover snapshot retained through sign-off. |
| PITR | Continuous provider history, configured to at least 7 days on the actual production root branch. |
| Snapshot-only RPO | At most 24 hours of committed data loss, measured from the newest recoverable snapshot; this fallback does not meet the PITR objective. |
| PITR RPO | At most 5 minutes of committed data loss for the normal incident recovery route. |
| Database RTO, each milestone | At most 4 hours from incident/rehearsal declaration through verified database readiness. Full service RTO is a separate #223 agreement and measurement. |
| Encryption/access | Provider encryption at rest and TLS in transit; restricted console, recovery roles and private artifact storage. Verify actual client TLS and provider controls. |
| Operational ownership | Named primary and alternate operator; #223 monitoring for failed/missing snapshots, history-window/plan changes and approaching expiration. |
| Rehearsal cadence | Both milestones before commercial activation, after material recovery/schema/provider changes, and quarterly thereafter under #223. |

Daily snapshots alone have a different data-loss budget from PITR. Agree both
milestone budgets explicitly. If the operator requires the same 5-minute RPO
for snapshot-only recovery, revise the protection strategy before acceptance;
do not label a daily backup as meeting it. Changes to objectives after a failed
drill require explicit operator approval and a recorded reason before activation.

Use UTC instants throughout. RPO is the interval between the last acknowledged
commit before the simulated incident and the latest acknowledged commit retained
by recovery. For an intentional earlier requested point, separately record the
requested point, actual included/excluded commits and the intentional rollback
interval; choosing an older point does not establish a small operational RPO.
With a sparse canary workload, record the recoverability bound from provider
history and deliberate recent commits; do not infer sub-minute RPO from the
absence of writes. Snapshot age and PITR recoverability are separate measures.

Database RTO starts when the incident/drill is declared, before console access, target
creation and secret retrieval. Database-ready time ends after restored schema,
all expected entities and integrity/content checks pass. Full service readiness
also requires the matching application release, trusted authority/configuration,
authorization/control-plane checks, DocumentStore availability and application
smoke sign-off under #223. Include access/operator delays and any replay or repair;
record incident occurrence/detection times separately from declaration.
The verifier's execution time or Neon's restore-operation duration alone is not
RTO. If the future commercial runtime cannot yet be exercised, record that gap
under #223/#258 without claiming full-service recovery or introducing a new
#221 dependency for #259's database recovery milestones.

## Neon settings and restore semantics

Provider details and the Free-plan amendment were checked on 2026-10-07.
Recheck current primary documentation and effective console/API settings during execution; a plan name or default is
not configuration evidence.

- Free supports up to six hours of history, capped at 1 GB. Inspect the actual
  project setting and recoverable point; volume can constrain usable history.
  [History window](https://neon.com/docs/postgres/backup-restore/history-window).
- Free supports one manual snapshot and no automated backup schedules. Confirm
  its availability and expiration/retention without deleting required evidence.
  Paid-plan scheduling and longer history are future protection improvements,
  with plan capacity verified before commercial acceptance.
  [Plans](https://neon.com/docs/introduction/plans),
  [Snapshots and schedules](https://neon.com/docs/guides/backup-restore).
- Snapshot restore can create a new branch for inspection. Keep it unfinalized;
  finalization moves compute/identity and is a separate production operation.
  Always identify the exact target rather than relying on a default.
  [Snapshot restore API](https://api-docs.neon.tech/reference/restoresnapshot).
- Instant restore requires root-branch history and applies to all databases and
  schemas in the selected target branch. Source and target must be approved
  explicitly. Omitted time/LSN means head, which cannot prove requested-point
  recovery. A snapshot-restored branch currently cannot serve as a PITR source;
  use the original production root's history for the second milestone.
  [Instant restore](https://neon.com/docs/postgres/backup-restore/branch-restore).
- Provider security documentation describes encryption; retain evidence of the
  applicable controls and verify the configured client's TLS separately.
  [Neon security](https://neon.com/security).

Record provider operation IDs, source/target lineage, timestamps, effective
settings and sanitized results privately. The application does not acquire a
Neon administrator API token or implement its own backup scheduler.

## Reuse and verification boundary

The verifier reuses #260's canonical artifact parser, all 26 bookkeeping
collections, relationship/accounting validators and PostgreSQL REPEATABLE READ
read-only export. The existing runtime owns safe SQL errors; #258's endpoint
fingerprint binds the declared source/target. New logic only compares a validated
expected-point export with restored content and optionally a distinct later-state
control. There is no parallel accounting, restore, retry or authority state machine.

The expected export must have been independently retained from the source while
writes were paused at the intended recovery point. It is a private comparison
oracle, not the backup being restored. Capture every expected entity, including
a representative populated entity and a second entity with overlapping local IDs.
Inventory all databases, entities and control-plane/schema objects privately.
Run the verifier for every expected bookkeeping entity; investigate missing or
unexpected entities. Each invocation checks only its explicitly selected entity.
An entity match cannot prove complete database inventory, provider lineage,
recovery objectives, restored roles/grants, triggers/functions, authority records,
identity/job/audit schemas or external document bytes. The current audit/job
tables and activation watermark require #342's separate recovery validation;
see [jobs and audit recovery boundaries](OPERATIONS_JOBS_AUDIT.md#inspection-immutability-retention-and-recovery).

Use the application release and immutable Alembic chain appropriate to the
requested point. Do not upgrade, stamp or downgrade the restored target before
checking it: that changes the state being verified. The current verifier accepts
only #260's supported revisions (`0004_mileage_order` through `0013_accounting_controls`)
and requires the exact expected revision. Older/unknown points stop explicitly;
use their retained release/tooling in an isolated environment and record the gap.
Never extend ordinary startup with historical format conversion.

### Read-only commands

Install the pinned database dependencies and use the repository development
environment. Inject `TABULA_RASA_RECOVERY_DATABASE_URL` explicitly from the
approved secret store for this process. The tool never falls back to
`TABULA_RASA_DATABASE_URL`, `.env.local`, a profile or a test endpoint. Do not put
the connection string in a command line or committed evidence.

```powershell
# First inspect the approved source, then the isolated target, using separate
# explicit secret injection for each process. Retain both opaque fingerprints.
python scripts/verify_postgres_recovery.py inspect

# Now use only the isolated target's recovery secret.
python scripts/verify_postgres_recovery.py verify --entity entity-alpha --expected <private-expected.json> --source-database-sha256 <source-fingerprint> --target-database-sha256 <target-fingerprint>

# Requested-point PITR additionally requires a distinct later committed state.
python scripts/verify_postgres_recovery.py verify --entity entity-alpha --expected <private-at-point.json> --later <private-after-point.json> --source-database-sha256 <source-fingerprint> --target-database-sha256 <target-fingerprint>
```

`inspect` reports connectivity, revision and the opaque endpoint identity. It
does not attest production provisioning or schema readiness. `verify` returns
`status=matched`, `scope=entity_bookkeeping`, revision, content digest and
diagnostic count only
when every canonical record/relationship exactly matches. Snapshot capture time
can differ; schema and content must match. Unknown schema, corrupt exports,
cross-entity input, unchanged PITR controls, unexpected
content and endpoint mismatch return nonzero with a fixed safe code. No private
values or record differences are printed. Use authorized private inspection to
investigate failures, retain the isolated target and stop acceptance.

Supported diagnostics already present in the expected export (such as a
historical mapping to a deleted record) are preserved by an exact content match.
They do not automatically make recovery fail or disappear. Review/disposition
every expected diagnostic privately before operational acceptance; a match is
not a declaration that existing bookkeeping problems are resolved.

Fingerprints exclude credentials and transport options. They detect declaring
the same endpoint or an unexpected URL; DNS/pooler aliases can refer to the same
database. The operator must verify actual Neon project/branch lineage and target
isolation through the console. The hashes cannot prove that distinction.

## Milestone A: restore a real managed backup

1. Complete the current Free-plan manual checkpoint and authorize the drill.
   Declare it and record its start, release/revision, source identity and exact isolated target.
   Pause all source writers/jobs/document operations for the controlled capture;
   use representative non-sensitive canary bookkeeping on the actual production
   environment before customer activation. Never insert canaries into a customer
   ledger or reset a production database as part of this procedure.
2. Capture private #260 exports for every expected entity while the source is
   frozen, and record the complete private inventory. Create/identify a real
   managed snapshot of that unchanged source; retain its ID, capture point,
   successful provider status and expiration. Resume only the authorized canary
   workload after capture. This manual snapshot is the source for the current
   restore milestone; its creation alone does not prove recovery or automation. Scheduled snapshot production belongs to the
   future commercial protection gate, not this Free-plan rehearsal.
3. Restore that snapshot into the approved new isolated recovery environment
   through Neon's multi-step/new-branch path. Do not finalize onto production or
   move its compute. Record provider completion and connect using the restricted
   recovery secret. A live clone at head, #260 export import, local dump or UAT
   restore does not prove this milestone.
4. Inspect the target and its revision; run `verify` without `--later` for each
   expected entity. Check the entire database inventory, named constraints,
   entity-qualified FKs, functions/triggers, authority records and effective
   roles/grants against the retained schema/release and private source inventory.
   Matching revision text alone does not verify these objects.
5. Check the release's read-only accounting/report behavior in the authorized
   isolated environment. Verify isolation and preserved accounting invariants:
   transfers outside income/expenses, mileage separate, signed opening balances,
   journal balance and `Assets = Liabilities + Equity`. Verify expected document
   metadata against #223's byte-recovery procedure. Record database-ready time,
   actual snapshot age/data loss and any capacity/measurement gaps. Compare
   against approved objectives only if such an agreement exists; otherwise
   label objective compliance unassessed and retain proposals separately. Record
   full-service smoke/readiness separately under #223/#258;
   retain database failures as #259 blockers and service/document gaps with
   their owner. Do not use the pre-cutover migration smoke command against
   a divergent restored ledger: it compares to the now-stale Sheets source.

## Milestone B: requested-point PITR

1. Use the actual production root's protected history, independently of the
   snapshot milestone. Confirm the requested recovery point T remains within
   the effective six-hour/1 GB history boundary and approve a dedicated new
   recovery branch; never choose
   production or retained UAT as a restore target. Neon supports creating a
   branch from an explicit parent's historical timestamp/LSN. This new-branch recovery path
   reads the original production root's history without rewinding production.
   [Create branch API](https://api-docs.neon.tech/reference/createprojectbranch).
2. Commit a known canary change A through supported entity-scoped services.
   Pause writers and capture the expected exports. Select a UTC requested point
   T strictly after A's confirmed commit and before any later changes. Record
   the server-observed point and provider time/LSN semantics, not a transaction
   start timestamp as a commit timestamp. Keep writers paused across capture/T;
   choose a clear time margin and use provider history inspection if uncertain.
3. Commit a distinguishable canary change B after T, capture the later export,
   and confirm A and B were acknowledged. Retain the before/after evidence and
   point privately. A timestamp-only metadata difference or an unchanged export
   cannot demonstrate exclusion of later state.
4. Create the isolated recovery branch from the explicit production root
   `parent_id` and `parent_timestamp=T` (or `parent_lsn`, mutually exclusive).
   Inspect the exact parent, requested point and new target before execution;
   await provider completion and obtain its restricted endpoint. Do not omit
   the parent/point, clone head, replay B, finalize onto production or use the
   snapshot-restored branch as history source. If using the separate instant
   restore API instead, both approved source and target must satisfy its root
   rules; stop if the isolated topology does not support that operation.
5. Run `verify --expected <at-T> --later <after-T>` for the changed entity and
   ordinary expected-point verification for every other inventoried entity.
   Exact content equality includes A and excludes B's changed state; retain
   separate known-commit checks from the provider history/authorized private
   view to prove ordering. Repeat schema/control-plane, isolation, service,
   financial/export and document checks from milestone A. Record observed RPO,
   intentional rollback interval, database-ready time and history/capacity gaps.
   Assess objective compliance only against an explicit approved agreement;
   otherwise record it as unassessed. Report full-service readiness separately
   under #223/#258.

An isolated environment may be reused only after recording milestone A
and verifying that its topology supports milestone B; a fresh historical branch
is the default above. Both milestones need
separate operation IDs, expected points, results and measurements.

## Authority, document recovery and return to service

An isolated restored database remains offline from ordinary requests/jobs.
#258 binds active authority to an endpoint fingerprint. A clone on another
endpoint can therefore pass bookkeeping verification while ordinary PostgreSQL
composition correctly refuses it. Do not rerun Sheets migration, call `activate`
to bypass that binding, clear `divergent`, disable triggers or automatically
rewrite control-plane evidence. Production promotion requires an explicit
reviewed #223 operator procedure and authorization for the exact target. A
provider restore finalized under the original endpoint can preserve the
fingerprint, but the recovered authority state must still be checked (a
pre-activation point cannot authorize writes). Moving to a different endpoint
additionally needs an explicitly reviewed rebind procedure; the verifier adds
no such write operation. Until that service-restoration path and smoke checks
pass, report database recovery evidence with the service-readiness gap, not
full production recovery.

The database restores document metadata and ordered links; DocumentStore owns
bytes, versions, permissions and profile/entity-specific provider grants. #223
must verify referenced versions/checksums, recover missing bytes from the agreed
store/NAS boundary, preserve unreferenced receipts and inspect uncertain links.
Do not delete newer/unreferenced bytes to simulate rollback or reuse another
profile's grant/folder. Recovery can create a detectable partial result; keep it
restricted until repaired. Unlinking does not delete the provider file.

Retain the restored environment, source, snapshots, exports and evidence for
sign-off. #223 owns any later explicitly approved cleanup/retention; #224 owns
customer deletion/export lifecycle. After divergent PostgreSQL writes, the
pre-cutover Sheets ledger stays historical. Any supported Sheets recovery uses
only the frozen format-13 contract and a new blank workbook, never an older
converter or live fallback. [Existing Sheets/document recovery](BACKUP_RECOVERY.md).

## Evidence and #258 handoff

Keep one private record with separate sections for the current drill scope,
future commercial agreement, inspected production settings and each milestone.
The record must contain:

- Operator/alternate, approval and drill dates, plan/effective settings, source
  and target identities/lineage, TLS/access verification, release/revision and
  exact provider operation/snapshot/history references.
- Requested and observed recovery points, confirmed A/B ordering for PITR,
  complete database/entity inventory coverage, canonical verifier reports,
  schema/control-plane/isolation, accounting/service/export and document results.
- Declaration, provider-ready, database-verified and full-service-ready UTC
  times; observed RPO/RTO, measurement limitations, approved objective revisions,
  gaps, responsible owner and explicit pass/fail for each milestone.

Credentials, connection strings, private bookkeeping, document bytes and full
exports stay outside Git, CI logs, exception text and published evidence.
Publish only reviewed sanitized status or an opaque digest/reference to the
private record. A checksum establishes content integrity, not operator approval.
An alternate operator should follow the runbook and confirm access/usability;
record this handoff before acceptance.

Record the two real Free-plan milestones independently after their required
schema/inventory/integrity/content checks pass, with observed measurements and
any limitations. Do not mark them complete from setup reports or synthetic tests.
For #258 commercial activation, completed `backup_restore` and
`point_in_time_recovery` evidence additionally requires the formally agreed
commercial protection/objectives, effective settings and objective compliance.
Its `production_setup` record needs inspected settings and distinct
staging/production environments; the current shared-project branch arrangement
must receive the commercial isolation review described above. #253/#280
commercial caller verification remains an independent gate. Ticket existence, these docs,
a verifier match or synthetic tests cannot substitute for completed evidence.
