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
2. Supply an explicitly authorized, durable, staging-scoped DocumentStore via
   the existing `create_app` runtime/service-composition seam. Preserve portable
   IDs and store/entity scope. The default `open_runtime` has **no byte store**;
   its availability screen cannot satisfy the required receipt workflow. Do not
   inject production profile grants, substitute an in-memory provider or silently
   omit receipts. #233/#251/#283 already implement the layer, metadata and UI/API;
   a new provider or hosted binding needs a narrow tracked implementation before
   this prerequisite can be marked complete. Document-byte recovery/versioning
   remains #223, with customer retention/lifecycle under #224.
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

Output contains only random run marker, release, engine, viewport and status.
Browser/provider errors are suppressed into bounded guidance. No screenshots,
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
| Ordinary transaction receipts | Implemented, available only with configured DocumentStore | Hosted provider binding above remains an explicit #288 prerequisite; source-owned receipt flows remain internal. |
| Recurring schedules and mixed-use sources/projections | Implemented under #284: create/edit, schedule state changes, explicit reconciliation and source/projection management | Outside the default alpha. Internal copy/conversion and source receipts remain internal; durable generation independent of page loads is #223. See [secondary workflows](COMMERCIAL_SECONDARY_WORKFLOWS.md). |
| Fixed assets and depreciation | Implemented under #285: register/detail/edit, schedules, explicit due posting, overrides and retirement | Outside the default alpha. Source receipts remain internal; additional mixed-use asset behavior remains #121. See [secondary workflows](COMMERCIAL_SECONDARY_WORKFLOWS.md). |
| Manual mileage log/filter/CSV/detail | Implemented under #286 | Maps/routing and QuickBooks import remain internal; record them as explicit #221 follow-up scope before their migration or retirement. |
| Transaction CSV/QuickBooks imports, bulk actions, filtered financial CSV/report download, category template import | Not exposed by current browser routes | Explicit #221 follow-up scope is needed; #282's core CRUD/read completion does not establish these paths. |
| Sheets workbook/backup administration and restore | `/data` is an availability page; no live-ledger fallback | #220/#261 preserve frozen format-13 internal recovery; #223 owns operational backup/recovery; #260 supplies complete PostgreSQL operator export and #224 owns customer delivery. |
| Google/profile/local credential administration | Not a commercial browser workflow | #222 owns native onboarding/authorization; #303 consumes authorized owner bindings. Do not port deployment-password/all-profile access as commercial identity. |

Unticketed narrow gaps above are an explicit remaining tracker task, not a claim
that broad parent issues have already implemented them. Creating GitHub issues
requires GitHub-write authorization. #288 must link the resulting narrow tickets
or an explicit owner-approved retirement decision before acceptance.

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

## Acceptance record and outstanding evidence

Use one sanitized record for the exact candidate; refresh affected evidence after
changes. Reference private records without publishing their contents.

| Evidence field | Current state / required record |
| --- | --- |
| #279 hosted prerequisites | Closed issue #279 records independently configured Render dev/staging, retained Neon UAT and successful staging promotion [37951248477](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/37951248477). Reverify the selected alpha candidate. |
| Release / schema / image / binding | Record exact SHA, both digest forms, forward schema revision and private environment binding reference. |
| Current required CI / reviews | Link the candidate's successful Full test suite and satisfied review conditions; earlier green heads do not qualify. |
| Essential staging DocumentStore | Pending hosted binding and real-provider verification; default runtime is unconfigured. |
| Staging six-case alpha suite | Pending authorized execution; retain run marker, workflow URL and all case results. |
| Application rollback rehearsal | Pending compatible prior/candidate staging deployments and smoke links. |
| Manual browser/device pass | Pending named tester/date, actual browser versions/devices, touch/keyboard, zoom/reflow, visible focus and screen-reader observations per #287. Track material findings before acceptance. |
| Provider/recovery limits | Record actual selected plan/region, shared project capacity/access, connections, idle/cold starts, quotas, available DB/byte recovery, accepted recovery gaps and owner. Do not invent numbers or treat planned NAS/PITR protection as verified. |
| Streamlit gaps and routing | Matrix above; narrow follow-up tickets/approved exclusions still required for uncovered paths. |
| #303 handoff | Link accepted alpha evidence and separately enumerate owner workflows/auth/recovery needs; live migration remains #303. |

No hosted alpha execution, real-provider receipt acceptance, rollback rehearsal,
manual device acceptance, live owner migration, external beta or commercial
activation is claimed by this implementation.

Reuse map: inspected #279 smoke/promotion/migration and HttpSettings/open_runtime,
#287 native browser fixtures and journey/failure suites, #281/#282 forms/report
contracts, #283 ReceiptService/DocumentStore composition, design and canonical
guides. Reused smoke, main-CI validation, deployment serialization, browser fields,
loaded-baseline/service contracts and disposable fixtures. New logic is one
bounded hosted journey plus release evidence/routing documentation; no parallel
domain, storage provider, authority mode, scheduler or retry workflow is introduced.
