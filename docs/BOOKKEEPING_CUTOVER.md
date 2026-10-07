# Whole-profile acceptance and controlled bookkeeping cutover

This guide owns #257/#258 under [EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It extends the [migration framework and domain loaders](SHEETS_POSTGRES_MIGRATION.md),
[frozen format-13 source](SHEETS_SOURCE_CONTRACT.md) and
[complete canonical entity export](BOOKKEEPING_EXPORT.md). Streamlit remains the
internal Sheets edition; this work supplies the service composition boundary
for the commercial runtime rather than a new Streamlit backend picker.

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
record. A repository test alone does not establish those operational milestones.
The setup record must identify the provisioned, reachable intended production
database, its approved secret configuration, schema decision/revision chain,
managed backup/PITR effective settings, agreed/observed RPO/RTO, isolated restore
strategy and separate staging database. Stop before preparation/activation and
request operator setup if any prerequisite is absent. Staging/internal rehearsal
can use `rehearsal` mode before #259; it cannot satisfy the production gates or
be composed as `commercial_production`.

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

## Implementation evidence and remaining operational acceptance

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
