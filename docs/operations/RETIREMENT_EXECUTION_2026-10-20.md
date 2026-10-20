# Operator-executed synthetic branch retirement — October 20, 2026

Exact-target execution under #339 / #223 / #124, with #377 D7 owner release.
This records one approved set, not completion of the whole resource inventory
or authorization for any other cleanup. PR #406 remains unmerged.

## Authority and exact scope

The human operator approved the displayed exact set with **"ok to delete"**
after the branch, database, compute, five branch-local roles and irreversible
historical-state loss were identified. That confirmation also answered the
explicit request to release any remaining consumer/recovery obligation. Computer
Use stopped before Codex clicked Delete. The operator then chose to execute
manually and reported **"deleted"**. Codex performed read-only postchecks; it
did not submit the provider deletion.

| Resource | Exact scope |
| --- | --- |
| Neon project | `weathered-term-80366172` (Project Tabula Rasa - test) |
| Deleted branch | `development-backup-20261017` / `br-bold-cherry-b51x0et0` |
| Contained database | `neondb`, scoped to that branch |
| Contained primary compute | `ep-round-glade-b5jwtro3` |
| Contained roles | `cloud_admin`, `neon_service`, `neon_superuser`, `neondb_owner`, `tabula_dev_runtime`, scoped to that branch; no global account grant deletion |

Neon branch deletion removes its contained databases/roles/compute. Independent
absence checks of each internal object are not possible after the branch is
removed; the observed provider branch result and documented cascade establish
that scope. [Provider deletion semantics](https://neon.com/docs/manage/branches#delete-a-branch).

The old branch was schema `0005_bookkeeping_cutover`. A read-only boolean query
confirmed all business entities were the known `alpha-synthetic` fixture, without
printing business rows. No source/production/UAT/receipt/NAS resource, secret,
deployment binding or deployed migration was selected for deletion.

## Reviewed plan and preservation decision

- Initially reviewed blocked-plan SHA-256:
  `66f8b3e519a5525762637e10f37124872b697fbaedb6e740de6d11060838c948`.
- Approved scoped inventory SHA-256:
  `bcbaf2c8977b1629b8dda9a4e1f1e1f22fe8db67fec94657b4920523ecaa8805`.
- Refreshed pre-execution plan SHA-256:
  `5e7a3f2ca0cbb9fa71885240ff405021d495d039f3935a2b82cd8a348c1c2ef4`.
- Preflight observation: `2026-10-20T15:24:11.340244Z` / 11:24 AM Eastern.
- The [candidate inventory](retirement-candidate-2026-10-20.json) and
  [preview](retirement-preview-2026-10-20.json) are retained historical
  **pre-execution** artifacts. `applied: false` describes the read-only tool;
  manual execution is recorded here, not by changing the CLI's output semantics.

Operator verification applies to this exact set and its retained dependencies,
using live provider metadata, tracked/local reference checks and the owner's
manual-consumer/recovery release. It does not claim an independent inspection of
every Render/GitHub secret or a complete provider-wide inventory.

The retained parent `development` (`br-cold-cell-b5ph2jz2`) and newer
`development-pre0015-20261020` (`br-sweet-cherry-b5winx0t`) remain. The operator
accepted disposal of the old point: the newer checkpoint is **not** an identical
copy of October 17 state, and no exact historical restore/undelete is promised.
If synthetic development must be rebuilt, reuse the retained source and current
supported migration/fixture procedure in `tabula_rasa/deployment/database.py`;
do not invent an old-schema runtime fallback. This is fixture recreation, not a
verified restoration of the discarded historical point.

## Observed postchecks

Postcheck capture: `2026-10-20T15:26:33.578190Z` / 11:26 AM Eastern. The exact
manual-click time was not captured; it occurred between approval/preflight and
the operator's report/provider-list readback.

| Check | Observed result |
| --- | --- |
| Provider branch result | Test-project list now contains six branches, down from seven. `development-backup-20261017` is absent |
| Retained test-project resources | Default `test`, `development`, `development-pre0015-20261020`, audit source, audit PITR and unfinalized snapshot restore remain in the provider list |
| Retained development database | Exact endpoint `ep-withered-morning-b5y67x0k` connected; schema remains `0015_support_controls` |
| Retained database contents | All 54 public-table hashes exactly match the pre-deletion repeatable-read baseline; zero changed tables |
| Aggregate table-inventory SHA-256, before and after | `7547c226acfc687a27a99a39d2f57f41b93c1eae7c93fa8a5aeee5115820a033` |
| Development `/version` and `/health/ready` | Both HTTP 200; parsed response hashes match the baseline |
| Staging `/version` and `/health/ready` | Both HTTP 200; parsed response hashes match the baseline |
| Forward migration history | No PR diff under `tabula_rasa/infrastructure/postgres/migrations` against refreshed `origin/main`; no deployed migrations/squashes were executed |

Only hashes/schema/health were emitted or retained by these checks; no ledger
rows, receipt bytes, connection URLs, passwords or tokens were printed or placed
in Git. Read-only SQL may wake compute and incur ordinary provider usage.

## Limits and remaining ownership

This demonstrates provider removal of the approved branch and unchanged retained
development contents plus bounded development/staging service health. It is not
a full content/security/receipt-byte comparison of every other provider resource,
a recovery drill or a commercial acceptance result. No Production/UAT database,
Sheets source, NAS generation, Drive receipt, external grant or other checkpoint
was deleted or written by this workflow. Their wider inventory/retention evidence
remains with #339/#223/#342 and the applicable #224/#298 owners.

Retain every other target pending its own disposition and exact approval. #261
format rejection and #294 indefinite NAS retention are unchanged. No unrelated
deletion, issue closure, authority activation or PR merge follows from this set.
