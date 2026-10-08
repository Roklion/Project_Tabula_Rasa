# Whole-profile acceptance and controlled bookkeeping cutover

This guide owns #257/#258 under [EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It also owns [#299](https://github.com/Roklion/Project_Tabula_Rasa/issues/299)'s
lasting owner-operated contract and shared-runtime integration procedure.
It extends the [migration framework and domain loaders](SHEETS_POSTGRES_MIGRATION.md),
[frozen format-13 source](SHEETS_SOURCE_CONTRACT.md) and
[complete canonical entity export](BOOKKEEPING_EXPORT.md). Streamlit remains the
internal Sheets edition; this work supplies the service composition boundary
for the shared web/API runtime rather than a new Streamlit backend picker.

## Reuse and ownership

- Existing extraction/shared validators own the source boundary. The core and
  secondary loaders own deterministic complete units, mappings and restart.
- Existing repository projections and reporting calculations own accounting
  meaning; acceptance extends their reconciliation rather than creating another
  calculation engine. The export adapter can read that same target snapshot.
- New logic records whole-profile acceptance, operator gate references, one
  entity's authority, and its first committed PostgreSQL bookkeeping mutation.
- The only new document adapter translates entity IDs to existing profile keys;
  the selected profile's provider grant/folder, retries and byte handling retain
  their existing owner. No byte migration or parallel write engine is added.

## Whole-profile acceptance

Pause source edits, recurring/depreciation jobs, imports and receipt operations.
Drain all request/worker processes capable of writing that profile. Preserve the
source and keep this maintenance window in effect through final smoke checks.
Sheets has no cross-worksheet snapshot isolation: operator-enforced source
freezing is part of the procedure, not a capability inferred from an API read.

After dry-run and a complete final load, run one acceptance command:

```powershell
python scripts/migrate_sheets_to_postgres.py --profile alpha --entity entity-alpha --accept
python scripts/migrate_sheets_to_postgres.py --profile alpha --entity entity-alpha --accept --format text
```

JSON is the default machine-readable report; `text` groups human-readable
differences by domain and opaque stable record key. Either command returns
nonzero on any difference. `--load --accept` explicitly combines complete load
with acceptance. `--accept` alone is read-only and does not activate a backend
or change migration run status. A successful source extraction goes through
#254's actual read-only shared format-13 header and domain validators. Earlier,
additional or otherwise unsupported populated source formats fail before any
source/target writes; there is no historical conversion path.

The report records #261/PR #263 and its delivered commit as source-contract
evidence. It verifies every supported source-owned unit and loaded checkpoint,
stable/mapped identities and original update provenance; reference hierarchies
and opening balances; exact Decimal postings; complete journals; recurring and
mixed-use owners/occurrences/projections; assets, overrides and posted history;
mileage/tags; referenced and unreferenced document metadata and exact links;
and existing financial reports for all activity and each activity month.
Complete canonical export generation and independent format/relationship
validation occur on the same coherent read-only REPEATABLE READ target snapshot.
All 26 supported bookkeeping collections must be representable. Valid additional
target records/relationships are differences even if the export itself is valid.
Incomplete checkpoints or matching core totals cannot produce final acceptance.

Every difference blocks acceptance; this version has no implicit tolerances or
waivers. Explicit normalization is limited to existing domain Decimal rules,
UTC creation instants, tag sets, existing ordered receipt/line relationships,
target-owned mutation timestamps (original instants are retained in mappings),
the documented epoch for unavailable creation instants, deterministic namespace
collision/document mappings, and unavailable historical import attribution.
No generated ledger history or absent facts are invented. Document bytes stay
in the existing DocumentStore. See the migration guide for their exact mapping.

Reports contain counts, fixed check/field names, versions and opaque digests,
never private financial values, descriptions, names, provider locators, source
record IDs or credentials. Keep the actual full export private and outside Git:
use `scripts/export_postgres_entity.py --output <private-path> --entity entity-alpha`
and its offline `--validate` mode. An in-memory export verification is included
in acceptance; the operator retains the delivered artifact for sign-off.

## Backend configuration and maintenance

Trusted server configuration uses an independent `bookkeeping_backends` table
keyed by the existing configuration profile. This is preserved when local JSON
profiles are merged into app secrets. Do not put authority settings into the
editable local profile store or accept them from a browser request. Example:

```toml
[bookkeeping_backends.alpha]
backend = "maintenance"

[bookkeeping_backends.beta]
backend = "sheets"
```

`create_application(profile_key, secrets, database=...)` requires an explicit
entry and composes exactly one backend. `maintenance` refuses composition;
`sheets` reuses existing Sheets composition. `postgres` requires the activated
entity, environment, database identity and accepted document-folder binding:

```toml
[bookkeeping_backends.alpha]
backend = "postgres"
entity_id = "entity-alpha"
mode = "rehearsal"
```

The caller supplies the pool from approved server database settings and owns its
lifecycle. Merely configuring a database URL never activates PostgreSQL. No
ordinary request loads data, changes authority, migrates schema or dual-writes.
There is no fallback to Sheets when PostgreSQL is unavailable. Service context
uses the canonical entity ID; the document adapter continues using the original
profile key for Google OAuth, receipt appProperties, inventory and provider
caches. Existing files are not retagged or moved.

The legacy `create_sheets_application` still defaults to Sheets for existing
internal profiles without an authority entry, and refuses a configured
maintenance/PostgreSQL profile before workbook initialization. Existing cached
Sheets graphs do not consult PostgreSQL on each Google write: stop/drain those
processes and jobs before final extraction and restart them with the new trusted
configuration. Backend selection is an operational composition decision, not
tenant authentication or membership. #222 owns commercial authorization.

## Activation evidence and operator decision points

For every migrated entity, retain:

| Gate | Required evidence |
| --- | --- |
| #261 | PR #263 source freeze/retirement, recorded automatically in acceptance. |
| #254 | Shared-validator source preflight and the preserved baseline decision in PR #271; actual target uses its validated forward chain. |
| #257 | Fresh whole-profile acceptance of the exact source/entity/run, every unit and relationship, with no differences. |
| #260 | Verified complete target export, its content digest and privately delivered artifact. |
| Maintenance | Source edit/jobs pause, drained old writers, preserved source/folder, intended target and rollback decision recorded by the operator. |

Commercial production additionally requires **completed #253 commercial caller
baseline/transaction/integrity verification**, successful **#259 actual managed
backup restore and requested-point PITR**, and the operator's production setup
record. The [managed recovery runbook](POSTGRESQL_RECOVERY.md) owns #259's
objectives, effective-settings inspection, both real recovery milestones and
the private evidence handoff. A repository test alone does not establish those
operational milestones.
The setup record must identify the provisioned, reachable intended production
database, its approved secret configuration, schema decision/revision chain,
managed backup/PITR effective settings, agreed/observed RPO/RTO, isolated restore
strategy and separate staging database. Stop before preparation/activation and
request operator setup if any prerequisite is absent. Staging rehearsal and
lasting owner operation use the non-commercial `rehearsal` evidence policy;
neither satisfies the commercial gates or can be composed as
`commercial_production`. See the owner-operated production procedure below.

Prepare an evidence JSON outside Git. Values are reviewed repository issue/PR
links (optionally with a comment anchor) or `sha256:<64 lowercase hex>` references
to retained private operator evidence. They are attestations by the authorized
operator, not automatic verification of a GitHub issue's status. Arbitrary free
text, credentials and private data are rejected from this record. Rehearsal
requires exactly `source_freeze` and `schema_baseline`. Production requires those
plus `production_setup`, `transaction_integrity`, `backup_restore` and
`point_in_time_recovery`. Each reference must point to completed evidence,
including the prerequisites above; do not substitute a ticket's existence.

Apply forward revision `0005_bookkeeping_cutover` explicitly with the normal
PostgreSQL operator tool. The retained `0001_initial`/`0004_mileage_order`
revisions remain unchanged. The new table stores control-plane authority and
gate references, outside the 26-collection portable bookkeeping format v1.

```powershell
python scripts/cutover_bookkeeping.py inspect --profile alpha --entity entity-alpha
python scripts/cutover_bookkeeping.py prepare --profile alpha --entity entity-alpha --mode rehearsal --evidence <private-evidence.json>
python scripts/cutover_bookkeeping.py activate --profile alpha --entity entity-alpha
```

`prepare` reruns whole-profile acceptance against fresh extracted source data,
marks its matching run `validated`, verifies the complete export again after
that metadata change, and atomically records `prepared` with the accepted export
digest. A prepared target rejects bookkeeping mutations. A matching preparation
can be repeated; another source/run/profile cannot take over its evidence.
Failure before preparation leaves Sheets authoritative and changes no target
authority/status. `activate` requires that prepared export remain unchanged.

For production use `--mode commercial_production` during preparation. Inspect
both intended production and separate staging endpoints through their approved
configuration, then supply `--production-database-sha256` and
`--staging-database-sha256` to activation. The production identity must match
the actual supplied pool and differ from the staging identity; both identities
are recorded. Fingerprints exclude usernames, passwords and connection options.
This checks the declared target binding; the operator still owns the truthful
environment/setup attestation. `inspect` reports current authority and rollback
availability, allowing a safe read after an uncertain command response.

After activation, deploy the PostgreSQL backend entry, restart into the new
composition, and run:

```powershell
python scripts/cutover_bookkeeping.py smoke --profile alpha --entity entity-alpha
```

Keep all writes/jobs paused for this check. It exercises actual application
reference, ledger, journal, asset, recurring, mixed-use, mileage, receipt and
reporting reads, then repeats whole-profile accounting and complete export
verification. Retain its safe report and private export. Only after passing
smoke checks release maintenance for the selected environment. Mark/archive
the prior workbook as the preserved pre-cutover source, restrict its editing
and keep its jobs disabled; retain the workbook, receipt folder and backups.
This tooling never deletes or rewrites the source, moves receipt bytes, changes
sharing or starts a scheduler. The operator performs that archival control.

## Rollback and subsequent recovery

Before any committed PostgreSQL bookkeeping mutation, re-extract the preserved
format-13 source and explicitly roll back:

```powershell
python scripts/cutover_bookkeeping.py rollback --profile alpha --entity entity-alpha
```

The source must match the accepted snapshot/run, and the complete target export
must still match its accepted digest. Stop/drain PostgreSQL processes, change
trusted configuration back to `sheets`, restart the Sheets edition and resume
source jobs only after this command records `sheets`. The PostgreSQL target is
retained for inspection and its cached services cannot commit bookkeeping
writes. A prepared target can use the same rollback procedure if activation is
abandoned. No reverse migration or deletion occurs.

Native entity-scoped triggers guard every canonical bookkeeping table. Their
authority lock serializes mutations with preparation/activation/rollback. The
first **committed** insert/update/delete while active marks `divergent` in the
same transaction; a rolled-back mutation does not. Secondary/document/reference
writes count even if P&L totals are unchanged. The marker stays set even if an
edit is later reversed. Other entities do not affect this profile's marker.
Once set, Sheets rollback is refused: recover PostgreSQL through #259/#223's
tested backup/PITR procedure and coordinated DocumentStore recovery. An old
Sheets source is then a historical recovery artifact, never a live fallback.
Database administrator operations, trigger disabling and direct manual source
edits remain outside ordinary application guarantees and this cutover procedure.

## Owner-operated production procedure (#299)

Use the same production browser/API application, PostgreSQL repositories,
accounting services, authorization and deployment process. Only the activation
evidence/recovery agreement is non-commercial. The database branch name
`production` and HTTP `environment="production"` do not select commercial
cutover evidence. Keep the trusted backend entry's **stored** `mode="rehearsal"`:
this existing value has no timeout, automatic reset, read-only restriction or
requirement that the database be disposable. Its `postgres` authority is durable
and continues after committed bookkeeping writes and process/pool restart.
This procedure gives that existing non-commercial behavior a named lasting-use
contract without altering deployed revision `0005_bookkeeping_cutover`.

Rehearsal means a controlled practice execution; owner-operated production means
the owner's lasting live ledger with explicitly accepted recovery limitations.
External beta adds #222/#224's user/tenant and stage protection requirements.
Commercial activation additionally uses `commercial_production` and #298's
completed evidence. An owner acceptance is never commercial certification.

Before an actual live execution, the authorized operator must:

1. Retain a private owner decision identifying the exact profile, source
   workbook, target entity, intended database fingerprint, document grant/folder,
   runtime release, authorized access, recovery owner and accepted limitations.
   Inspect the intended endpoint using `inspect` through approved configuration;
   do not infer it from a branch name or use UAT as the live target. The existing
   activation records the actual endpoint fingerprint and composition checks it
   on every new service graph. Verify schema/connectivity/TLS with the existing
   PostgreSQL operator tools; keep credentials and evidence contents private.
2. State which recovery protections are actually available now, their measured
   limits and document-byte recovery ownership. NAS protection planned in
   [#294](https://github.com/Roklion/Project_Tabula_Rasa/issues/294) stays marked
   pending until scheduling, archive protection/health and isolated restore pass.
   Logical archives recover captured points, not continuous PITR. If working
   NAS recovery is required before live writes, make #294 a deployment
   prerequisite. It is not a prerequisite for #299's technical completion.
   A subscription, commercial RPO/RTO agreement and alternate-operator commercial
   handoff are not conditions for this owner contract. Explicitly accept current
   limitations; do not fabricate commercial evidence to unlock use.
3. Follow the same source freeze/writer drain, supported format-13 extraction,
   complete load, fresh zero-difference whole-profile acceptance and private
   26-collection export procedure above. Preserve the source, receipt bytes and
   backups. Prepare with `--mode rehearsal` and exactly the existing
   `source_freeze`/`schema_baseline` references. Retain the broader private owner
   decision separately; the two-field evidence JSON is not a recovery guarantee.
4. Activate, deploy the explicit PostgreSQL backend configuration and restart
   the shared runtime with the approved database and authenticated resolver.
   Run the existing cutover `smoke` before releasing maintenance. A missing
   target, inactive authority, different mode, profile/source, endpoint or
   document folder must stop startup/use rather than fall back to Sheets.
5. With separate authorization for a controlled live bookkeeping operation,
   verify a legitimate committed write, restart, and verify its persisted result,
   reports and complete export. Inspect `divergent` and the rollback boundary.
   After divergence, the frozen-source acceptance/smoke comparison is expected
   to differ: use ordinary runtime health, report and export checks rather than
   reloading/reaccepting the old source. Sheets remains archived; recovery uses
   the available PostgreSQL protection and coordinated document recovery.

### Shared production runtime composition

The deployed app factory uses `create_app` and its existing `runtime_factory`
seam. Bind migrated entities using `open_migrated_runtime`:

```python
from functools import partial
from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import open_migrated_runtime

# These are supplied by normal server deployment/identity configuration.
# The resolver authenticates the request and authorizes its entity/capabilities.
def build_app(authenticated_resolver, entity_profiles, profile_secrets):
    return create_app(runtime_factory=partial(
        open_migrated_runtime,
        resolve_context=authenticated_resolver,
        entity_profiles=entity_profiles,
        profile_secrets=profile_secrets,
    ))
```

The server-only mapping explicitly associates canonical entity IDs with source
profile keys. Database settings use the existing approved loader (or an explicit
`DatabaseSettings` supplied by the deployment). Startup owns one pool, checks
all configured authority/document bindings and current schema readiness, and
closes the pool on failure/shutdown. Requests compose fresh scoped services
through `MigratedProfileServices` and `create_application`. All normal
identity, capability, entity, Host, Origin and CSRF checks remain in force.
The factory refuses the synthetic fixture option; migrated service binding also
refuses a `trusted_development` context. Setting `rehearsal` or a database URL
does not authenticate anyone. No new login, owner authorization bypass,
domain engine, source loader, scheduler or recovery state machine is introduced.

The resolver and deployment integration must be real and approved before using
private data. #222 owns normal web identity/session delivery; #279 owns hosted
deployment, and #280/#281–#286 own the remaining protected interactions and
workflow coverage. The current shared HTTP foundation exposes account reads and
creation; service/report/export verification does not claim those later browser
screens are delivered. Until the selected deployment has the resolver and
required workflows, stop before live migration and complete those shared
integration tasks. This is a setup/coverage checkpoint, not a second owner app.

### Reuse and completion evidence

Inspected/reused: `composition.py` owns authority/profile/document binding;
the cutover controller/CLI and revision 0005 own acceptance and durable authority;
native guards own divergence; `http/app.py`, `PostgresRuntime`, request context
and `MigratedProfileServices` own shared HTTP lifecycle/authorization; existing
repositories and export/report services own bookkeeping reads/writes. The new
factory extends that existing composition with startup validation. No parallel
domain logic or schema/mode extension is needed.

`tests/postgres/test_owner_operated_cutover.py` exercises the actual shared
production HTTP app and native PostgreSQL with two synthetic migrated profiles,
two pool/application lifetimes, account/financial writes, report/export reads,
document ownership, invalid target/authority and request-guard failures, and
post-divergence rollback refusal. Its resolver is an explicitly synthetic test
stand-in; this does not certify deployed authentication or a private migration.
Existing tests retain commercial evidence refusal and complete acceptance gates.
Run these affected checks against an explicit disposable test endpoint:

```powershell
python -m pytest tests/http tests/test_backend_composition.py tests/postgres/test_owner_operated_cutover.py tests/postgres/test_cutover.py tests/postgres/test_migration_acceptance.py
```

#299 closes only after its checks and documentation pass and the linked
#220/#221/#288/#298 tracking records the supported path. Report missing native
or deployed verification explicitly; do not infer it from skips or source review.
#299 completion does not claim a live authority switch or #294 completion.

Tracking handoff after verification: #220 records the supported non-commercial
authority contract and evidence; #221/#288 consume this shared runtime factory
and retain their workflow/deployment gates; #298 preserves all commercial
activation requirements and records that owner use is independent; #294 retains
NAS implementation/restore status. Updating or closing GitHub issues requires
separate repository-write authorization. No issue status changes are implied by
this guide.

## Implementation evidence and remaining operational acceptance

Local #299 implementation verification on 2026-10-08: **261 affected tests
passed across focused runs**, with no skips: 170 application/HTTP,
backend/document composition, source migration and export tests; 22 database
configuration tests; and 69 native PostgreSQL tests. The native runs covered
all nine new owner-operation cases, 29 existing cutover/whole-profile acceptance
cases and 31 HTTP/schema/export cases. The new write/restart test initially used
an inactive historical account; after correcting it to use the active account
created through the HTTP API, that case passed on rerun.

Windows Smart App Control blocked the temporary local PostgreSQL runtime;
verification instead used the operator's separate, empty Neon test project and
its `test` branch on PostgreSQL 18.6. Its direct endpoint connected with TLS and
`channel_binding=require`, and its test role could create/drop the fixture's
disposable databases. All disposable test databases were removed afterward.
The dedicated test URL was explicitly loaded into the test process from the
operator's Git-ignored `.env.local`; no credentials were printed or committed.
Scoped Ruff, working/branch whitespace and generated OpenAPI contract checks
passed. This is focused local evidence; the full-suite publication/review checks
and linked-issue tracking remain separate. No private source, live migration,
production authority switch or deployed authentication is claimed.

Synthetic native PostgreSQL tests cover complete final-format profiles, two
isolated profiles with shared source IDs, exact financial/reference/document
relationships, missing units, malformed/retired inputs before writes, service
smoke checks, missing production gates, pre-divergence rollback, failed versus
committed writes, and a write concurrent with rollback. These are implementation
evidence. No private profile migration, production setup, recovery rehearsal,
production authority switch or issue closure is performed by these tests.
Retain the actual repeated staging/final-cutover evidence separately before
claiming the remaining operational criteria of #257/#258.

Local implementation validation on 2026-10-07, based on dependency branch
`codex/issues-255-256-migration` at `77e4d7fc0153d6be66b5970525c9624de6e86fe0`:
Ruff passed; all **1,810 tests passed in 164.54 seconds**, including native
PostgreSQL with no skips; working and branch diff checks passed. The preceding
focused service/migration/export checks passed 109 tests. A separate local
review checked source ownership, service callers, export compatibility,
production gate records, receipt profile/entity aliases and the rollback boundary.
No GitHub publication, private source read or production operation was performed.
