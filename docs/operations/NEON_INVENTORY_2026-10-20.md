# Live Neon inventory and first retirement candidate — October 20, 2026

The inventory below records the **pre-deletion** observations. The operator later
approved and manually deleted only the exact old development checkpoint set;
[execution and postchecks](RETIREMENT_EXECUTION_2026-10-20.md) supersede the
initial pending status. The test-project count is now six, with retained
development data hashes and development/staging health unchanged.

Read-only inspection through the owner's existing desktop Chrome Neon session
under #339/#223/#124. No account switch, authentication change, schema/data write,
provider deletion or retention change occurred. Only safe provider identifiers
and configuration observations are recorded. This supplements the
[desk inventory](RESOURCE_INVENTORY.md); other resource families and effective
private/hosted references remain unverified.

## Observed branch inventory

The test-project list showed seven branches. The main-project list showed ten;
the organization overview earlier showed nine for that project. A newly active
staging pre-0015 checkpoint appeared during inspection. This is concurrent
operator work, not an orphan signal. Recheck before any operation.

| Project | Observed branch | Parent | Disposition |
| --- | --- | --- | --- |
| `weathered-term-80366172` (test) | `test`, ID `br-green-pond-b5qy3v5n` | None | Retain default/shared test; two databases reported |
| test | `development`, ID `br-cold-cell-b5ph2jz2` | `test` | Retain active development |
| test | `development-backup-20261017`, ID `br-bold-cherry-b51x0et0` | `development` | First candidate; deferred pending owner release and reference/recovery checks |
| test | `development-pre0015-20261020`, ID `br-sweet-cherry-b5winx0t` | `development` | Retain latest maintenance checkpoint |
| test | `audit-dr342-20261019-source` | None/schema-only | Retain #342 source/evidence |
| test | `audit-dr342-20261019-pitr` | Audit source | Retain #342 recovery evidence |
| test | `branch_from_snapshot_Oct 19, 2026 10:31 PM EDT` | None/schema-only | Retain unfinalized #342 snapshot restore |
| `dawn-union-89360840` (main) | `production`, ID `br-odd-truth-b5pi2zc3` | None | Retain production default/source |
| main | `uat`, ID `br-lingering-sky-b52tdr40` | `production` | Retain active UAT/staging |
| main | `backup-staging-paused-pre0014-20261018`, ID `br-dark-king-b5yn9rz0` | `uat` | Retain/defer; rollback checkpoint not released |
| main | `backup-staging-pre-0014-20261018`, ID `br-royal-brook-b59tli76` | `uat` | Retain/defer; rollback checkpoint not released |
| main | `backup-staging-pre-identity-20261017` | `uat` | Retain/defer; identity/recovery obligation not released |
| main | `uat-backup-20261018-0014` | `uat` | Retain/defer; schema-0014 recovery obligation not released |
| main | `staging-pre0015-20261020` | `uat` | Retain newly active checkpoint/ongoing maintenance |
| main | `recovery-259-pitr-20261007` | `production` | Retain #259 evidence |
| main | `recovery-259-snapshot-20261007` | None | Retain #259 snapshot restore/evidence |
| main | `restore-drill-20261019` | `uat` | Retain #294 archive restore/evidence |

Names without IDs were observed in the provider list and remain insufficient
exact-target deletion identities. No such row is selected. Project Equinox is
outside scope.

## Concrete first candidate

| Field | Observation or outstanding condition |
| --- | --- |
| Project | `weathered-term-80366172` |
| Branch | `development-backup-20261017` / `br-bold-cherry-b51x0et0` |
| Created / last updated | October 17 23:39:12 / October 18 06:08:12, as displayed by console |
| Children | None in the complete seven-branch list; recheck before execution |
| Database | `neondb`; one database reported and enumerated |
| Compute | `ep-round-glade-b5jwtro3`; one primary, initially suspended since October 17 23:44 console-local time; no read replica listed. Later read-only SQL inspection can wake it and consume compute; initial suspension is not a current-state guarantee |
| Branch-local roles | `cloud_admin`, `neon_service`, `neon_superuser`, `neondb_owner`, `tabula_dev_runtime`; these objects are scoped to this branch, not global Neon account grants |
| Deletion effects | Exact branch, its database, primary compute and five branch-local roles; historical state/recovery at this branch would be lost |
| Read-only metadata | Connected to the exact candidate endpoint with existing local configuration without printing credentials; revision `0005_bookkeeping_cutover`. A boolean query confirmed all business entities are the known `alpha-synthetic` fixture; no business rows/values were printed |
| Preserved parent | Active `development` / `br-cold-cell-b5ph2jz2` |
| Preserved newer checkpoint | `development-pre0015-20261020` / `br-sweet-cherry-b5winx0t`; created October 20 10:43:19 console-local time; one database/one compute reported |
| Tracked references | No match for old branch name/endpoint in tracked scripts, runtime, workflows, tests or canonical docs, excluding inventory |
| Local effective references | Both application/test database URLs parsed privately; neither points to the old endpoint, including pooler normalization. No URL/credential printed |
| Hosted/manual references | Tracked/local effective references checked; owner released remaining consumer/recovery obligations in the exact-set approval. Effective hosted secrets were not independently enumerated |
| Authority | No live authority observed; suspended compute does not prove absence of consumers |
| Latest operational evidence | [#332 approved development maintenance and successful smoke](https://github.com/Roklion/Project_Tabula_Rasa/issues/332#issuecomment-6293893668) records 0014→0015 upgrade and healthy compatible development. It does not release this old checkpoint or verify its contents |
| D4/D7 decision | Synthetic fixture scope confirmed; owner released the exact checkpoint and approved irreversible retirement |
| Recovery limitation | New checkpoint is a different point, not a copy of October 17 state. Do not promise undelete or identical historical-state recovery |
| Exact-set approval | Approved by the owner in chat; subsequently deleted manually by the owner, with observed postchecks linked above |

The [candidate inventory](retirement-candidate-2026-10-20.json) records the known
eight-resource cascade, retained parent, replacement and default branch.
The [preview](retirement-preview-2026-10-20.json) records the refreshed approved
preflight and returns `requires_manual_approval`; the tool remains read-only.
Scoped owner verification and separate exact approval are recorded in the
execution report. This does not verify every other resource family or private
hosted binding, or authorize repeating deletion of the historical candidate.

## Execution handoff

Before separately approved execution, recheck target IDs/cascade, no new child
or consumer, retained parent/checkpoint and live environment baselines. Record
the exact-set approval under the [runbook](../RESOURCE_RETIREMENT.md), execute
only that set, read back absence and retained-resource postconditions, and append
sanitized actual outcomes to this PR. The first set's actual outcomes are now
recorded in the linked execution report; later sets still require this procedure.

All other resources remain retained or unresolved: staging migration checkpoints,
#259/#294/#342 evidence, NAS generations, frozen Sheets sources, receipt bytes,
exports/checksums and deployed migration history.
