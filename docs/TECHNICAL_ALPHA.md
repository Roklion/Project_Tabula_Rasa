# Technical-alpha release and Streamlit transition (#288)

This is the integration/release contract for [#288](https://github.com/Roklion/Project_Tabula_Rasa/issues/288),
under [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Trusted operators exercise synthetic data on the selected Render browser/API
service and retained Neon PostgreSQL staging endpoint. The application services
own bookkeeping, PostgreSQL owns ledger authority, and DocumentStore owns bytes.
No alpha workflow may redirect to Streamlit or use its session/rerun state.

Technical alpha, lasting owner use and external release are separate milestones.
#303 owns actual owner migration using completed #299; its private execution is
not required to accept synthetic alpha. #222 owns identity/memberships, #223
operations and #224/#298 external-beta/commercial acceptance. Alpha does not
require paid provider features, completion of those epics or #294 NAS automation.
It does require truthful access, capacity and recovery limits for the selected stage.

## Exact default workflow matrix

| Required workflow | New-stack surface and owner | Release evidence |
| --- | --- | --- |
| Resolve business/reference setup | Server-scoped entity context; Accounts, Categories, Payees, Tags (#281) | Fixed hosted Alpha context and rejected foreign entity; create two bank accounts, expense/income categories, payee and tag. Local/native two-business switching and isolation remain in #287. |
| Ordinary transaction lifecycle | Transactions (#282/#280) | Expense/income/transfer create, loaded edit, fresh confirmed delete; reference/tag selections; transfer excluded from income/expenses. |
| Journal lifecycle | Add journal/Journals (#282/#280) | Unbalanced save disabled; balanced posting create, edit, grouped ledger read and confirmed delete. |
| Protected mutations | Existing loaded-baseline forms (#280) | Two independently loaded browsers; stale edit and delete rejected, draft preserved, missing edit/delete baseline rejected, explicit latest-record reload. The broader reference/merge matrix remains in #287 CI. |
| Ledger/core reports | Transactions, Dashboard/Reports (#282) | Four complete entries visible; report deltas include journal expense and exclude transfer; Assets = Liabilities + Equity; mobile ledger fits its scroll region. |
| Essential document flow | Saved transaction receipts (#283) | Real configured staging DocumentStore: upload/attach, exact-byte download, reference-only unlink, retained-file relink and final unlink. #287 CI retains controlled partial-link/uncertain-upload/failure tests. |
| Runtime/release | Version, readiness, deployment (#279) | Exact release SHA, anonymous restrictions, routing, real DB-backed account read; ordered schema step and compatible application rollback evidence. |
| Browser quality | Bounded #287 suite plus staging journey | Chromium/Firefox/WebKit, 1440x1000 and 390x844; current-candidate CI, staging results and manual device record. |

Mileage (#286) is available as an additional manual log, but is not promoted into
the default alpha gate. Recurring/mixed-use (#284) and assets/depreciation (#285)
remain outside that gate. If a release or #303 owner matrix needs them, name the
additional workflows and require the corresponding completed slice and evidence.

## Repeatable retained-staging gate

This gate requires explicit `TABULA_RASA_ACCESS_MODE=restricted_alpha` in the
GitHub staging environment and runner; it refuses named staging before release
checkout. After
the approved transition, use [authenticated rollout](AUTHENTICATED_ROLLOUT.md)
to overlay named identity checks on the existing matrix. Keep this gate and
its synthetic context separate; do not restore Basic access to run it on a
named owner/external deployment.

Reuse [#279 deployment](COMMERCIAL_DEPLOYMENT.md) for target binding, explicit
migration, immutable-image integrity, ingress and temporary alpha credentials.
The read-only deployment smoke proves connectivity; it is not the complete alpha
journey. `.github/workflows/commercial-alpha.yml` adds an explicitly dispatched
**Technical alpha staging gate**. It shares `commercial-deploy-staging` with
promotion, has read-only GitHub permissions and receives only staging origin and
alpha gate credentials. It has no database, migration or Render admin credential.
It does not deploy, migrate or run ordinary pytest against retained staging.
After validating the selected main release's CI, the workflow checks out that
exact SHA and verifies `HEAD` before importing or running its alpha journey.
Newer `main` journey code cannot establish evidence for an older deployed release.

Before dispatch:

1. Promote the selected current-CI-approved immutable main image through #279.
   Record image index/runtime-manifest digests, exact release SHA, schema revision,
   migration/promotion run and private target-binding reference.
2. Configure the default runtime's durable Google Drive binding using
   [Hosted synthetic receipt storage](ALPHA_DOCUMENT_STORAGE.md). It loads only
   the explicitly supplied `TABULA_RASA_ALPHA_DOCUMENTS_FILE`, validates the exact
   environment/origin/entity and independent synthetic profile/folders, and
   composes the existing #233/#251/#283 services. Without that file, receipts
   remain unavailable; the availability screen cannot satisfy this gate. Do not
   inject production grants or substitute an in-memory provider. Run the same
   binding's read-only preflight and retain private setup evidence. Document-byte
   recovery/versioning remains #223, with customer retention/lifecycle under #224.
3. Confirm this is restricted synthetic staging, pause manual promotions/writers,
   record accepted provider limits and authorize the bounded creates/removals.
   Dispatch on `main` with the exact deployed SHA and `allow_synthetic_writes=true`.

For an authorized manual invocation, privately export the same staging origin,
username/password and `TABULA_RASA_ENVIRONMENT=staging`, then run from the root
of a clean checkout at that exact release SHA. Verify `git rev-parse HEAD` matches
the selected release; the checkout must include this alpha gate:

```powershell
python -m pip install playwright==1.62.0
python -m playwright install chromium firefox webkit
python -m tabula_rasa.deployment.alpha --release EXACT_40_CHARACTER_MAIN_SHA --allow-synthetic-writes
```

The runner reuses #279's gate/routing/version/connectivity smoke before and after
the six engine/viewport journeys. Each journey checks fixed writable synthetic
context and receipt availability before any create. It uses unique `Alpha-<run>`
names and the browser's stable create identities; it never retries a failed write.
Successful journeys remove only their own financial entries through fresh loaded
forms. They retain reference records and an unlinked synthetic receipt in
Unreferenced receipts. A failed journey may retain its own financial entries;
inspect that run before another attempt. There is no broad cleanup, database
reset, byte deletion, simulated rollback or private-data capture. #223 owns
disposition of retained synthetic artifacts.

Output contains only random run marker, release, engine, viewport, fixed operation
label and status. A failed case records its engine, width/height and operation
(for example, `receipt_download`, `receipt_bytes`, `receipt_unlink` or
`receipt_relink`). Configuration and shared smoke failures have no journey
engine/viewport and use their own operation labels. Receipt completion assertions
and download initiation wait at most 30 seconds, matching the browser action
budget rather than the five-second default assertion budget. A timeout still
stops the gate without retrying; inspect the retained run before another attempt.
Browser/provider exceptions are suppressed into bounded guidance. No screenshots,
traces, response bodies, credentials, ledger data or receipts enter Actions
artifacts/logs. A failed case fails the gate. `alpha_browser_passed` establishes
the bounded staging suite only; it is not complete #288 acceptance.

The exact same journey runs in `tests/postgres/test_browser_alpha.py` against
disposable real PostgreSQL through the compiled browser and actual HTTP/services,
with a synthetic byte adapter and a second entity. CI requires it alongside #287's
failure/accessibility/concurrency suites. This local/CI evidence cannot establish
real provider integration, retained staging, rollback rehearsal or real devices.

## Compatible application rollback rehearsal

Reuse #279's [promotion/failure/rollback procedure](COMMERCIAL_DEPLOYMENT.md#promotion-failure-and-rollback).
Select a verified retained prior digest with the same schema head and passing
main CI, and authorize a controlled staging maintenance window. Record current
and prior digests/release IDs, then dispatch the normal staging promotion to the
prior compatible digest. Its ordered migration check, registry/Render integrity,
readiness and browser smoke must pass. Promote the selected alpha candidate
again, verify the same evidence, and run its complete alpha gate. Retain both
workflow links and operator observations proving the retained DB/receipt data
survived. A real rollback deployment is required; mocks or a repeated current-image
promotion do not rehearse rollback.

Do not introduce a bad bookkeeping write or destructive schema failure just to
test rollback. Do not automatically downgrade/stamp/restore the DB. Incompatible
schemas require the #220 reviewed bridge/maintenance/forward-repair policy;
database/document disaster recovery remains #223/#298. An uncertain deploy stops
for inspection under existing #279 rules.

## Feature routing and authority during transition

| Workflow | Browser/API availability | Remaining internal/reference path and tracker |
| --- | --- | --- |
| Accounts/categories/payees/tags, ordinary transactions/journals, ledger/core reports | Implemented new-stack routes; no redirect to legacy UI | Streamlit remains a behavioral reference for unmigrated Sheets profiles. #281/#282 are complete. |
| Ordinary transaction receipts | Implemented; default hosted runtime accepts the explicit Drive binding above | Operator grant/folder installation and real-provider verification remain required. Asset acquisition receipts stay on the ordinary acquisition transaction. |
| Mixed-use source receipts | Browser/API implementation under #361; source-owned upload/link/download/unlink/recovery with protected source baselines | Outside the default alpha; selected grant/folder and hosted verification remain operator work. Generic projections stay read-only and recurring templates do not own receipts. See [workflow ports](COMMERCIAL_WORKFLOW_PORTS.md). |
| Recurring schedules and mixed-use sources/projections | Implemented under #284: create/edit, schedule state changes, explicit reconciliation and source/projection management | Outside the default alpha. Independent copy/conversion is available under #362. Durable generation independent of page loads remains #223. See [secondary workflows](COMMERCIAL_SECONDARY_WORKFLOWS.md). |
| Fixed assets and depreciation | Implemented under #285: register/detail/edit, schedules, explicit due posting, overrides and retirement | Outside the default alpha. Acquisition transaction owns receipts; generated depreciation has no independent receipt/copy/import action. Additional mixed-use asset behavior remains #121. See [secondary workflows](COMMERCIAL_SECONDARY_WORKFLOWS.md). |
| Mileage log/filter/CSV/detail and Maps lookup/routing | Manual workflow under #286; optional browser/API Maps integration under #363, with explicit review and manual fallback | #133 key restrictions and controlled provider validation remain operator prerequisites; QuickBooks mileage import is available under #364. Existing #158 owns proposed mileage bulk workflows. See [workflow ports](COMMERCIAL_WORKFLOW_PORTS.md). |
| Selected-ledger, transactions and journal-postings financial CSV downloads | Implemented under #359; selected complete entries on Transactions and two full financial downloads on `/data` | Outside the default alpha; these existing CSVs do not replace #260's complete recovery export or #345's customer portability. See [workflow ports](COMMERCIAL_WORKFLOW_PORTS.md). |
| Transaction CSV/QuickBooks imports; ordinary copy/bulk | Implemented under #357 and #358, with read-only previews and explicit protected commands | Outside the default alpha; consume the delivering revision’s evidence before #303 cutover. |
| Category-template import and standalone report downloads | Excluded by the owner's October 11 scope correction | #360 is not planned; these are unimplemented feature ideas, not migration prerequisites. Existing category management and on-screen reports remain supported. |
| Sheets workbook/backup administration and restore | `/data` exposes financial CSVs; no Sheets administration or live-ledger fallback | #220/#261 preserve frozen format-13 internal recovery; #223 owns operational backup/recovery; #260 supplies complete PostgreSQL operator export and #224 owns customer delivery. |
| Google/profile/local credential administration | Not a commercial browser workflow | #222 owns native onboarding/authorization; #303 consumes authorized owner bindings. Do not port deployment-password/all-profile access as commercial identity. |

The October 11 #288 acceptance handoff published the seven remaining ports as
#357–#359 and #361–#364 under #221/#124. The owner's #303 scope requires the
applicable existing workflows before live cutover. The
[workflow-port guide](COMMERCIAL_WORKFLOW_PORTS.md) records the delivered
behavior; [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221)
retains implementation ownership and approved exclusions. Local implementation and synthetic checks do not establish
deployment, real-provider verification or live-cutover approval.

Choose one authoritative backend per entity through the existing cutover contract.
An unmigrated Sheets entity keeps its authorized internal runtime. A PostgreSQL
entity uses supported new-stack surfaces; unavailable workflows remain unavailable
until migrated. Do not send it to stale Sheets to finish an action, dual-write,
or re-enable Sheets after PostgreSQL divergence. #303 owns private live execution;
synthetic alpha performs no authority activation.

## Streamlit retirement criterion

The commercial image already installs the API/PostgreSQL dependencies without
Streamlit; CI verifies HTTP import/schema construction in that image. Retiring
commercial dependence requires every workflow in the selected release/owner
matrix to have a supported browser/API/service path, tested failures/isolation,
configured durable dependencies and documented routing. Unknown required gaps
must stop that release, while explicitly excluded long-tail slices may continue
independently. No hidden session-state or page-load scheduling may remain.

Before disabling an entity's old writers, consume the supported migration,
acceptance/export, authentication and recovery boundaries for its release stage.
Before repository-wide removal of Streamlit, separately inventory all remaining
internal users/workflows, migrate or explicitly retire each, preserve source and
recovery artifacts, and update operator/user documentation and tests. #288 does
not authorize package removal, source deletion or a big-bang cutover.
The [retirement inventory in issue #377](https://github.com/Roklion/Project_Tabula_Rasa/issues/377)
records active callers, owners, eligible cleanup, retained regression
contracts and concrete conditions for deferred removals. It consumes this routing
matrix without adding a release or owner-cutover prerequisite.

### Restricted-alpha cleanup disposition (#221/#321, D2)

[#321's accepted closure](https://github.com/Roklion/Project_Tabula_Rasa/issues/321#issuecomment-6293694820)
completed a narrowed synthetic-staging handoff. Provider recovery and wider
security/operational acceptance remain with #320/#348/#332/#342/#353/#298.
The following source paths retain independent callers; named staging alone does
not make them obsolete:

| Capability | Current caller / reason to retain | Owner and later removal condition |
| --- | --- | --- |
| `http/alpha.py`, `alpha_documents.py` | `http/app.py` gates explicitly restricted hosted requests; `http/composition.py` loads the synthetic document binding. Focused HTTP and native document tests protect these boundaries. | #221 with #321/#288: retire only after affected environment transitions and remaining synthetic/document consumers have an explicit replacement or retirement decision. |
| `TrustedDevelopmentContext` | `http/composition.py` supports loopback development and gated hosted synthetic scope; native API/browser fixtures reuse it. | #221/#288: retain local development and isolation tests until their own supported replacement or explicit retirement. |
| `deployment/alpha.py`, `commercial-alpha.yml` and focused fixtures/tests | The explicit restricted-alpha journey remains the repeatable #288 contract; the workflow refuses named staging before checkout. | #221/#288: retain independently useful synthetic journeys; do not switch a named deployment back to Basic access to run them. |

The executed single-use schema bridge is removed separately; see the
[retired bridge and preserved migration coverage](COMMERCIAL_DEPLOYMENT.md#retired-staging-bridge-0012-to-0014-321).
This disposition does not require completion of an entire EPIC or add a live
cutover prerequisite. #303 still owns actual three-profile authority and legacy
writer retirement evidence.

## Acceptance record and outstanding evidence

Use this template for each newly selected candidate; it is not a status board.
The accepted technical-alpha result and approved exclusions are recorded in
[issue #288](https://github.com/Roklion/Project_Tabula_Rasa/issues/288#issuecomment-6117319756).
Do not carry those results forward as acceptance of a different release or stage.

| Evidence field | Required record for the selected candidate |
| --- | --- |
| Candidate | Reviewed release SHA, current required CI/reviews, immutable image/index/runtime digests and forward schema revision |
| Deployment | Exact approved environment/binding reference, promotion/smoke links and observed version/readiness |
| Drive custody | Independent staging grant and managed folders, protected installation and preflight; private bindings stay private |
| Receipt journey | Authorized upload/attach, exact-byte download, reference-only unlink, retained-file relink and restart persistence |
| Six-case suite | Exact deployed checkout, explicit synthetic-write consent, retained marker, workflow URL and every engine/viewport result |
| Compatible rollback | Prior/candidate compatible image/schema, maintenance window, both smoke links, retained-data observations and candidate suite rerun |
| Manual quality | Tester/date, actual browser/device versions, touch/keyboard, zoom/reflow, focus and the accepted accessibility scope; record exclusions explicitly rather than inventing observations |
| Provider/recovery limits | Actual plan/region/capacity/quota/access, DB/byte protection, observed limitations, accepted gaps and responsible owner |
| Routing | Every required workflow has a verified implementation/selected-runtime path or an explicit approved exclusion with an issue owner |
| Owner handoff | Applicable #303 workflow/auth/recovery scope, operator authorization and evidence references; alpha is not live migration |

Outstanding selected-release work belongs in [#303](https://github.com/Roklion/Project_Tabula_Rasa/issues/303)
for live owner use, [#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321)
for hosted identity, [#342](https://github.com/Roklion/Project_Tabula_Rasa/issues/342)
for operational evidence and [#348](https://github.com/Roklion/Project_Tabula_Rasa/issues/348)
for external-beta acceptance. [#377](https://github.com/Roklion/Project_Tabula_Rasa/issues/377)
owns the retirement inventory. Publication, deployment, provider writes, live
cutover and customer admission retain their separate authorization boundaries.
