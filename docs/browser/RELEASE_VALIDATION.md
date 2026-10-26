# Release validation and Streamlit transition

Trusted operators exercise synthetic data on the selected Render browser/API
service and retained Neon staging database. Application services own bookkeeping,
PostgreSQL owns ledger authority and DocumentStore owns bytes. Alpha workflows
must not redirect to Streamlit or use its session/rerun state.

Technical alpha, lasting owner use and external release are separate milestones.
Owner use follows [controlled cutover](../accounting/CUTOVER.md); named-user
deployment follows [hosted rollout](../identity/HOSTED_ROLLOUT.md). The matrix below
defines the bounded alpha scope, rather than every available application route.
Synthetic alpha requires neither paid provider features nor NAS automation;
owner cutover and external release retain their separate evidence requirements.

## Exact default workflow matrix

| Required workflow | New-stack surface and owner | Release evidence |
| --- | --- | --- |
| Resolve business/reference setup | Server-scoped entity context; Accounts, Categories, Payees, Tags (entity and reference workflows) | Fixed hosted Alpha context and rejected foreign entity; create two bank accounts, expense/income categories, payee and tag. Local/native two-business switching and isolation remain in browser testing. |
| Ordinary transaction lifecycle | Transactions (core bookkeeping workflows and protected browser mutations) | Expense/income/transfer create, loaded edit, fresh confirmed delete; reference/tag selections; transfer excluded from income/expenses. |
| Journal lifecycle | Add journal/Journals (core bookkeeping workflows and protected browser mutations) | Unbalanced save disabled; balanced posting create, edit, grouped ledger read and confirmed delete. |
| Protected mutations | Existing loaded-baseline forms (protected browser mutations) | Two independently loaded browsers; stale edit and delete rejected, draft preserved, missing edit/delete baseline rejected, explicit latest-record reload. The broader reference/merge matrix remains in browser testing CI. |
| Ledger/core reports | Transactions, Dashboard/Reports (core bookkeeping workflows) | Four complete entries visible; report deltas include journal expense and exclude transfer; Assets = Liabilities + Equity; mobile ledger fits its scroll region. |
| Essential document flow | Saved transaction receipts (receipt workflows) | Real configured staging DocumentStore: upload/attach, exact-byte download, reference-only unlink, retained-file relink and final unlink. browser testing CI retains controlled partial-link/uncertain-upload/failure tests. |
| Runtime/release | Version, readiness, deployment (deployment) | Exact release SHA, anonymous restrictions, routing, real DB-backed account read; ordered schema step and compatible application rollback evidence. |
| Browser quality | Bounded browser testing suite plus staging journey | Chromium/Firefox/WebKit, 1440x1000 and 390x844; current-candidate CI, staging results and manual device record. |

Mileage (mileage workflows) is available as an additional manual log, but is not
promoted into the default alpha gate. Recurring/mixed-use (recurring and mixed-use
workflows) and assets/depreciation (asset workflows) remain outside that gate. If a
release or live owner cutover owner matrix needs them, name the additional workflows and
require the corresponding completed slice and evidence.

## Repeatable retained-staging gate

This gate requires explicit `TABULA_RASA_ACCESS_MODE=restricted_alpha` in the
GitHub staging environment and runner; it refuses named staging before release
checkout. After
the approved transition, use [authenticated rollout](../identity/HOSTED_ROLLOUT.md)
to overlay named identity checks on the existing matrix. Keep this gate and
its synthetic context separate; do not restore Basic access to run it on a
named owner/external deployment.

Reuse [deployment](../operations/DEPLOYMENT.md) for target binding, explicit migration,
immutable-image integrity, ingress and temporary alpha credentials. The read-only
deployment smoke proves connectivity; it is not the complete alpha journey.
`.github/workflows/commercial-alpha.yml` adds an explicitly dispatched **Technical alpha
staging gate**. It shares `commercial-deploy-staging` with promotion, has read-only
GitHub permissions and receives only staging origin and alpha gate credentials. It has
no database, migration or Render admin credential. It does not deploy, migrate or run
ordinary pytest against retained staging. After validating the selected main release's
CI, the workflow checks out that exact SHA and verifies `HEAD` before importing or
running its alpha journey. Newer `main` journey code cannot establish evidence for an
older deployed release.

Before dispatch:

1. Promote the selected current-CI-approved immutable main image through deployment.
   Record image index/runtime-manifest digests, exact release SHA, schema revision,
   migration/promotion run and private target-binding reference.
2. Configure the default runtime's durable Google Drive binding using
   [Hosted synthetic receipt storage](../storage/STAGING_RECEIPTS.md). It loads only
   the explicitly supplied `TABULA_RASA_ALPHA_DOCUMENTS_FILE`, validates the exact
   environment/origin/entity and independent synthetic profile/folders, and
   composes the existing document storage, document metadata repository and receipt workflows services. Without that file, receipts
   remain unavailable; the availability screen cannot satisfy this gate. Do not
   inject production grants or substitute an in-memory provider. Run the same
   binding's read-only preflight and retain private setup evidence. Document-byte
   recovery/versioning remains platform operations, with customer retention/lifecycle under external release and customer lifecycle.
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

The runner reuses deployment's gate/routing/version/connectivity smoke before and after
the six engine/viewport journeys. Each journey checks fixed writable synthetic context
and receipt availability before any create. It uses unique `Alpha-<run>` names and the
browser's stable create identities; it never retries a failed write. Successful journeys
remove only their own financial entries through fresh loaded forms. They retain
reference records and an unlinked synthetic receipt in Unreferenced receipts. A failed
journey may retain its own financial entries; inspect that run before another attempt.
There is no broad cleanup, database reset, byte deletion, simulated rollback or
private-data capture. platform operations owns disposition of retained synthetic
artifacts.

Output contains only random run marker, release, engine, viewport, fixed operation label
and status. A failed case records its engine, width/height and operation (for example,
`receipt_download`, `receipt_bytes`, `receipt_unlink` or `receipt_relink`).
Configuration and shared smoke failures have no journey engine/viewport and use their
own operation labels. Receipt completion assertions and download initiation wait at most
30 seconds, matching the browser action budget rather than the five-second default
assertion budget. A timeout still stops the gate without retrying; inspect the retained
run before another attempt. Browser/provider exceptions are suppressed into bounded
guidance. No screenshots, traces, response bodies, credentials, ledger data or receipts
enter Actions artifacts/logs. A failed case fails the gate. `alpha_browser_passed`
establishes the bounded staging suite only; it is not complete technical-alpha
validation acceptance.

The exact same journey runs in `tests/postgres/test_browser_alpha.py` against disposable
real PostgreSQL through the compiled browser and actual HTTP/services, with a synthetic
byte adapter and a second entity. CI requires it alongside browser testing's
failure/accessibility/concurrency suites. This local/CI evidence cannot establish real
provider integration, retained staging, rollback rehearsal or real devices.

## Compatible application rollback rehearsal

Reuse deployment's [promotion/failure/rollback
procedure](../operations/DEPLOYMENT.md#promotion-failure-and-rollback). Select a
verified retained prior digest with the same schema head and passing main CI, and
authorize a controlled staging maintenance window. Record current and prior
digests/release IDs, then dispatch the normal staging promotion to the prior compatible
digest. Its ordered migration check, registry/Render integrity, readiness and browser
smoke must pass. Promote the selected alpha candidate again, verify the same evidence,
and run its complete alpha gate. Retain both workflow links and operator observations
proving the retained DB/receipt data survived. A real rollback deployment is required;
mocks or a repeated current-image promotion do not rehearse rollback.

Do not introduce a bad bookkeeping write or destructive schema failure just to test
rollback. Do not automatically downgrade/stamp/restore the DB. Incompatible schemas
require the PostgreSQL persistence reviewed bridge/maintenance/forward-repair policy;
database/document disaster recovery remains platform operations and commercial recovery
agreement. An uncertain deploy stops for inspection under existing deployment rules.

## Feature routing and authority during transition

| Workflow | Browser/API availability | Remaining internal/reference path and tracker |
| --- | --- | --- |
| Accounts/categories/payees/tags, ordinary transactions/journals, ledger/core reports | Implemented new-stack routes; no redirect to legacy UI | The Streamlit bookkeeping pages and writers are retired; local operator administration remains.  |
| Ordinary transaction receipts | Implemented; default hosted runtime accepts the explicit Drive binding above | Operator grant/folder installation and real-provider verification remain required. Asset acquisition receipts stay on the ordinary acquisition transaction. |
| Mixed-use source receipts | Implemented source-owned browser/API workflow; source-owned upload/link/download/unlink/recovery with protected source baselines | Outside the default alpha; selected grant/folder and hosted verification remain operator work. Generic projections stay read-only and recurring templates do not own receipts. See [workflow ports](IMPORTS_EXPORTS_AND_INTEGRATIONS.md). |
| Recurring schedules and mixed-use sources/projections | Supported operations: create/edit, schedule state changes, explicit reconciliation and source/projection management | Outside the default alpha. Independent copy/conversion is available under recurring conversion and source copying. Durable generation independent of page loads remains platform operations. See [secondary workflows](RECURRING_AND_ASSETS.md). |
| Fixed assets and depreciation | Supported operations: register/detail/edit, schedules, explicit due posting, overrides and retirement | Outside the default alpha. Acquisition transaction owns receipts; generated depreciation has no independent receipt/copy/import action. Additional mixed-use asset behavior is outside this scope. See [secondary workflows](RECURRING_AND_ASSETS.md). |
| Mileage log/filter/CSV/detail and Maps lookup/routing | Manual trip workflow and optional browser/API Maps integration, with explicit review and manual fallback | Configured Maps key restrictions and controlled provider validation remain operator prerequisites; QuickBooks mileage import is available under mileage imports. Mileage bulk actions remain proposed. See [workflow ports](IMPORTS_EXPORTS_AND_INTEGRATIONS.md). |
| Selected-ledger, transactions and journal-postings financial CSV downloads | Implemented; selected complete entries on Transactions and two full financial downloads on `/data` | Outside the default alpha; these existing CSVs do not replace the complete recovery export or an authorized customer portability artifact. See [workflow ports](IMPORTS_EXPORTS_AND_INTEGRATIONS.md). |
| Transaction CSV/QuickBooks imports; ordinary copy/bulk | Implemented, with read-only previews and explicit protected commands | Outside the default alpha; consume the delivering revision’s evidence before live cutover. |
| Category-template import and standalone report downloads | Excluded by the owner's October 11 scope correction | These routes are not planned; these are unimplemented feature ideas, not migration prerequisites. Existing category management and on-screen reports remain supported. |
| Sheets workbook/backup administration and restore | `/data` exposes financial CSVs; no Sheets administration or live-ledger fallback | PostgreSQL persistence and frozen Sheets source contract preserve frozen format-13 internal recovery; platform operations owns operational backup/recovery; complete entity export supplies complete PostgreSQL operator export and external release and customer lifecycle owns customer delivery. |
| Google/profile/local credential administration | Not a commercial browser workflow | identity and tenancy owns native onboarding/authorization; live owner cutover consumes authorized owner bindings. Do not port deployment-password/all-profile access as commercial identity. |

Existing workflow integration includes financial imports/exports, source-owned receipts,
recurring conversion, Maps and mileage imports. The selected owner-use scope requires
the applicable existing workflows before live cutover. The [workflow-port
guide](IMPORTS_EXPORTS_AND_INTEGRATIONS.md) records the delivered behavior; [browser and
API workflows](RUNTIME.md) retains implementation ownership and approved exclusions.
Local implementation and synthetic checks do not establish deployment, real-provider
verification or live-cutover approval.

Choose one authoritative backend per entity through the existing cutover contract. An
unmigrated Sheets entity keeps its authorized internal runtime. A PostgreSQL entity uses
supported new-stack surfaces; unavailable workflows remain unavailable until migrated.
Do not send it to stale Sheets to finish an action, dual-write, or re-enable Sheets
after PostgreSQL divergence. live owner cutover owns private live execution; synthetic
alpha performs no authority activation.

## Streamlit retirement criterion

**Current source boundary:** Streamlit bookkeeping pages, startup/page recurring
generation and obsolete preparation converters are retired. Retained local operator
administration still requires the flag, loopback bind, application password and
reauthentication. Format-13 migration/archive recovery, current PostgreSQL recovery,
Google grants/folders and forward schema history remain supported. This source change
establishes no merge/deployment or commercial release acceptance.


The commercial image already installs the API/PostgreSQL dependencies without
Streamlit; CI verifies HTTP import/schema construction in that image. Retiring
commercial dependence requires every workflow in the selected release/owner
matrix to have a supported browser/API/service path, tested failures/isolation,
configured durable dependencies and documented routing. Unknown required gaps
must stop that release, while explicitly excluded long-tail slices may continue
independently. No hidden session-state or page-load scheduling may remain.

Before disabling an entity's old writers, consume the supported migration,
acceptance/export, authentication and recovery boundaries for its release stage. Before
repository-wide removal of Streamlit, separately inventory all remaining internal
users/workflows, migrate or explicitly retire each, preserve source and recovery
artifacts, and update operator/user documentation and tests. technical-alpha validation
does not authorize package removal, source deletion or a big-bang cutover. The
[capability retirement
evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/377) records active
callers, owners, eligible cleanup, retained regression contracts and concrete conditions
for deferred removals. It consumes this routing matrix without adding a release or
owner-cutover prerequisite.

## Restricted-alpha support and retirement

Named staging acceptance does not retire independently supported synthetic paths.
Provider recovery and wider security/operational acceptance remain separate.

| Capability | Current callers and retention condition |
| --- | --- |
| `http/alpha.py`, `alpha_documents.py` | `http/app.py` gates restricted hosted requests; `http/composition.py` loads the synthetic document binding. Retain focused HTTP/native document tests until the affected environments and document consumers have an explicit replacement or retirement decision. |
| `TrustedDevelopmentContext` | Composition supports loopback development and gated hosted synthetic scope; native API/browser fixtures reuse it. Retain development and isolation coverage until a supported replacement or explicit retirement. |
| `deployment/alpha.py`, `commercial-alpha.yml` and focused fixtures/tests | The restricted-alpha journey remains repeatable and refuses named staging before checkout. Retain useful synthetic journeys; never switch named staging back to Basic access to run them. |

The [single-use staging schema bridge](../operations/DEPLOYMENT.md#retired-staging-bridge-0012-to-0014)
has retired separately. Actual multi-profile authority and legacy writer retirement
still require controlled cutover evidence; synthetic handoff supplies no live authority.

## Acceptance record and outstanding evidence

Use this template for each newly selected candidate; it is not a status board. The
accepted technical-alpha result and approved exclusions are recorded in [technical-alpha
validation
evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/288#issuecomment-6117319756).
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
| Owner handoff | Applicable live owner cutover workflow/auth/recovery scope, operator authorization and evidence references; alpha is not live migration |

For each selected release, collect live-owner, hosted-identity, operational and
External-admission evidence separately. Keep results and pending decisions in the owning
release discussion, including accepted exclusions. Publication, deployment, provider
writes, live cutover and customer admission each retain their explicit authorization
boundary.
