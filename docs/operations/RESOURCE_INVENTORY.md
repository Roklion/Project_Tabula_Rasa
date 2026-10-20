# Resource disposition desk inventory — October 19, 2026 Eastern

Issue [#339](https://github.com/Roklion/Project_Tabula_Rasa/issues/339), parent
[#223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223), initiative
[#124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Follow the [retirement runbook](../RESOURCE_RETIREMENT.md) before changing any
resource. This table and [JSON](resource-inventory.json) contain safe identifiers
from repository/issue evidence only. No credentials, connection strings, receipt
contents or financial records are included. **No blanket deletion is approved.**
The [first exact synthetic development checkpoint set](RETIREMENT_EXECUTION_2026-10-20.md)
was separately approved and manually deleted by the owner, with bounded
postchecks. [#339's later owner-directed closure](https://github.com/Roklion/Project_Tabula_Rasa/issues/339#issuecomment-6300537453)
records additional owner-reported removals without a complete target-by-target
audit. This dated desk inventory is not a current existence attestation; its
unverified families remain retained/deferred until refreshed evidence and owner
disposition exist. Do not treat historical entries as fresh deletion candidates.

The recorded evidence review checkpoint is `2026-10-20T03:00:00Z` (October 19,
11 PM Eastern); this is not an observation of live provider state. JSON coverage
is `unverified`. Current provider existence, project/endpoint IDs, effective
authority, last backup and reference completeness require authorized inspection.
Names below are historical identifiers, not proof of current identity or absence.
Rows describing families must be expanded into exact provider-scoped resources;
the table does not claim a complete hosted enumeration.

[October 20 live Neon inspection](NEON_INVENTORY_2026-10-20.md) supplements
these historical facts with observed project/branch IDs, current branch lists
and a concrete first candidate. Other families and private/hosted consumer
checks remain unverified; no exact-set deletion is approved.

Owner: **Roklion** is the recorded human operator for the known recovery evidence.
This assigns the follow-up for the desk inventory, not new access or approval.
Confirm an environment owner/retention decision for every actual resource.

| Resource / JSON ID | Known safe identifier or scope | Disposition and reason | Consumers / D4 or D7 evidence; re-review condition |
| --- | --- | --- | --- |
| `production-root` | Neon production root; exact project/branch/endpoint unresolved | Active/recoverable; preserve source and live data | #259 source, #303 authority, #298 commercial; D4. Reinspect effective authority; never infer current pause from old drill |
| `retained-uat` | Retained Neon UAT; exact IDs unresolved | Active/recoverable; preserve staging/recovery target | #294/#342; D4. Reinspect effective consumers |
| `neon-development`, `neon-test` | Development/shared test project branches/endpoints unresolved | Unresolved; no disposable designation | Deployment, pytest integration and audit drills; D7. Enumerate provider hierarchy and manual/test callers |
| `local-postgres` | `compose.postgres.yml`; local instances unresolved | Unresolved; may serve active developers | Compose and pytest; D7. Confirm owner and exact database/container, never use wildcard teardown |
| `ci-fixture-databases` | `tests/postgres/conftest.py` creates/drops its own isolated fixtures | Unresolved outside normal fixture lifecycle | Required CI/test harness; D7. Leave harness-owned cleanup unchanged; identify genuinely orphaned exact fixtures first |
| `migration-rehearsals` | #258/#299/#303 rehearsal DBs/data and exports; IDs unresolved | Unresolved/recovery protected | Cutover acceptance and rollback; D4. Owner must release each rehearsal obligation |
| `recovery-259-snapshot` | `recovery-259-snapshot-20261007` | Required drill evidence; retain | #259 closure, #298; D4. Exact project/branch ID and evidence acceptance needed; unfinalized restore is not disposable |
| `recovery-259-pitr` | `recovery-259-pitr-20261007` | Required drill evidence; retain | #259 closure, #298; D4. Same exact-target release requirement |
| `snapshot-259` | Managed snapshot captured `2026-10-08T02:04:21Z`; exact ID unresolved | Required drill evidence; retain | #259 closure; D4. Inspect current existence/expiry and lineage; do not replace/delete to free snapshot capacity |
| `nas-294-restore-branch`, `nas-294-restore-database` | Branch `restore-drill-20261019`, DB `tabula_restore_20261019` | Required retained-archive recovery evidence | #294 [initial evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/294#issuecomment-6259851298); D4. DB depends on branch; retain until explicit evidence release |
| `nas-production`, `nas-uat` | Protected NAS complete-generation families | Required recovery; indefinite no-prune retention | #294 [retention audit](https://github.com/Roklion/Project_Tabula_Rasa/issues/294#issuecomment-6273553024); D4. Enumerate all current generations privately; policy change is separate |
| `nas-294-uat-generation` | `20261019T023012740769Z-6b2a00acbb1d455faa7c707fab531518` | Required successful UAT archive; indefinite | #294/#259 retained-archive drill; D4. Preserve manifest/key custody; DB metadata does not cover bytes |
| `nas-mislabeled-generation` | Older UAT-source generation in Production namespace; exact ID unresolved | Retain with provenance; not a genuine Production recovery point | #294 retention audit; D4. Do not rename/delete or count toward Production coverage |
| `nas-quarantine-drill` | `issue294-drill-20261019`; complete/incomplete/quarantined files | Required interruption/failure evidence; retain | #294 [manual recovery](https://github.com/Roklion/Project_Tabula_Rasa/issues/294#issuecomment-6269536893); D4. Enumerate exact files/generations and protected plaintext privately |
| `audit-342-source`, `audit-342-snapshot`, `audit-342-pitr` | Synthetic source, managed snapshot `2026-10-20T02:30:12Z`, restored branches; private IDs | Required audit-recovery evidence; retain | #342 [actual drills](https://github.com/Roklion/Project_Tabula_Rasa/issues/342#issuecomment-6282272542); D4. Preserve exact lineage/manifests and unfinalized snapshot restore |
| `audit-342-nas-target`, `audit-342-failed-empty-target` | Fresh successful target and earlier empty failed-ACL target; private IDs | Required success/failure evidence; retain even the empty target | Same #342 evidence; D4. Emptiness alone is not deletion consent |
| `audit-342-oracles` | Private independent manifests, sealed keys/results, downloaded ciphertext, stopped task containers | Required drill evidence; enumerate separate resources | Same #342 evidence; D4. Tmpfs plaintext cleared per evidence; do not infer other local files absent |
| `audit-342-nas-generation` | `20261020T024013208474Z-2ba2eb4aac1d48bab0573f63eb71f263` | Required physical NAS audit archive; indefinite | Same #342 evidence; D4. Drill-only `uat` namespace is not retained UAT backup; not NAS scheduler execution |
| `render-development` | `srv-db45ejjtqb8s73e536a0` | Active/recoverable deployment binding | `support_maintenance.SERVICES`, promotion/maintenance workflows; D7. Preserve service/config and inspect effective DB references |
| `render-staging` | `srv-db45q43bc2fs73aniv1g` | Active/recoverable staging; protected | Same D7 consumers, named-user staging; inspect active revision/bindings |
| `temporary-render-bindings` | Other temporary services, environment bindings and provider fixtures unresolved | Unresolved; no deletion candidates inferred | #279/#321/#338; D7. Enumerate temporary vs active/rollback bindings, including GitHub environments and secret names |
| `drive-338-fixtures` | Synthetic receipt folders/files, archive generations and `receipt-recovery-drill` binding; private IDs | Required byte/link recovery evidence | #342 [hosted results](https://github.com/Roklion/Project_Tabula_Rasa/issues/342#issuecomment-6267386081); D4. Preserve originals and encrypted archives; enumerate earlier local/provider attempts too |
| `sheets-frozen-sources` | Frozen source profiles/workbooks; exact IDs private/unresolved | Retained source/last verified legacy snapshot | #261/#303/#319 and #377 D4. Per-profile source freeze/complete export/checksum preservation remains required |
| `sheets-drive-backups` | Final-format Sheets/Drive backup families | Retained source/recovery | Backup/recovery guide, #261; D4. Identify final verified snapshot and private custodian; format rejection is not consent |
| `historical-format-artifacts` | Existing earlier-format files/backups | Retained source; historical support retired independently | #261 and #377 D4. Explicit policy decision before exact-target disposal |
| `receipt-originals-and-archives` | Source Drive receipts, byte archives/manifests and any NAS copies | Retained source/document bytes | #338/#303; D4. Verify bytes independently of DB metadata; no implicit unlink/delete |
| `cutover-exports-checksums` | Complete canonical exports, checksums, acceptance evidence | Retained source/recovery | #258/#260/#303; D4. Preserve per-profile/entity scope and rollback boundary |
| `forward-alembic-history` | `tabula_rasa/infrastructure/postgres/migrations/versions/` | Retained deployed schema history | #254, every deployed DB; D7. Forward migrations only; no reconsolidation/squash |

## Remaining exact-resource handoff

The table covers all issue scope families; **live inventory completeness is still
unverified**. The operator must enumerate exact endpoints/branches, snapshot IDs,
local/CI orphans, rehearsal records, all NAS generations/quarantine, temporary
Render/GitHub bindings, Drive/Sheets IDs, local archives and historical files.
Record existence or verified absence, owner, current authority, last verified
backup, active/retained consumers, collateral effects and separate D4/D7
evidence for each. Keep all unresolved items retained and re-review when the
owner has provider access and #303/#321/#222/#342 replacement evidence applies.

One exact disposable target set has been approved and manually removed; the
linked execution record distinguishes actual provider/postcheck observations
from synthetic tests. No additional cleanup, policy change, customer deletion
or issue closure is claimed. A synthetic passing preview alone proves only the
implemented decision path.
Record any later execution through the exact approval and pre/post-check protocol
in the runbook; do not turn this desk inventory into blanket deletion consent.
