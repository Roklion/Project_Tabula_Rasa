# Transition tracking drafts and acceptance handoff (#288)

These are reviewable GitHub payload drafts under #221/#124. No issues/comments
have been posted, no workflow has been retired, and no product exclusion has
been approved by writing this file. Local `TA-*` identifiers are not issue numbers.
After authorized publication, replace them in the [routing matrix](TECHNICAL_ALPHA.md)
with actual narrow issue links, or record the owner's explicit retirement/exclusion
decision. #288's remaining-workflows-ticketed criterion stays open until then.
None of these long-tail flows is added to the default technical-alpha matrix.

## TA-1 — Commercial web: Transaction CSV and QuickBooks import

Parent #221; consumes existing import parsing/preparation/application services and
PostgreSQL import repository. Core CRUD #282 does not expose this workflow.

Expose existing supported CSV Income/Expense and QuickBooks transaction imports
through thin API/browser adapters. Preserve read-only preview, complete diagnostics,
duplicate checks, explicit confirmed write, stable IDs, reference creation rules,
failure/partial-result guidance and selected-entity isolation. Inspect existing
import owners before extending them. Define supported source formats and exact
batch semantics in the PR; do not silently introduce journal/transfer formats.
Require affected service/adapter/API/browser success, rejection, retry/duplicate
and two-entity coverage. Preserve one authoritative backend without Sheets fallback.

## TA-2 — Commercial web: Ordinary transaction copy and bulk actions

Parent #221; consumes existing transaction services and protected baseline rules.

Expose the supported internal Copy transaction, selected tag/category/payee updates
and eligible simple-entry deletion through explicit selection and confirmation.
Preserve complete stable-ID selection checks, eligibility rules, loaded baselines,
derived-source ownership and independent copy identity/provenance. Receipts are
not copied. Journal selections allow export only; mixed-use/depreciation projections
cannot be mutated through generic bulk actions. CSV export belongs to TA-3.
Define atomic versus recoverable batch failure behavior using existing repository
owners, and test stale selection, protected records, duplicate create and two entities.

## TA-3 — Commercial web: Financial ledger CSV and report downloads

Parent #221; consumes existing ledger/reporting/export calculations and filters.

Add filtered/selected financial CSV and supported report downloads matching the
documented internal surfaces. Preserve displayed filter scope, journal grouping,
transfer exclusion, mileage separation, balance/sign conventions, escaping of
formula-leading spreadsheet text and read-only entity/capability enforcement.
Verify empty/populated scopes, accounting totals, spreadsheet-text safety and
two-entity isolation. No byte-store configuration or full recovery/export rewrite.
Complete operator export remains #260; customer delivery remains #224.

## TA-4 — Commercial web: Category template import

Parent #221; consumes existing category template parser/domain validation and
category hierarchy/reference repositories.

Expose preview and explicit apply for the supported template format, preserving
normalization, hierarchy/cycle rules, duplicate checks and existing-category
behavior. Define fresh mutation-boundary checks and failure outcome before writing.
Test invalid templates, unchanged existing references, successful hierarchy setup
and two-entity isolation. Do not add a second category-rule implementation.

## TA-5 — Commercial web: Mixed-use source receipt management

Parent #221; follows completed #284 and consumes #283/#233/#251.

Add source-owned upload/link/download/unlink/recovery for mixed-use source records,
reusing ReceiptService, the existing receipt-context owner, DocumentStore and source
mutation rules. Preserve source/projection consistency, protected loaded source
baselines, stable portable IDs, bounded upload uncertainty, reference-only unlink
and two-entity grant/folder isolation. Generic derived ledger rows remain read-only.
Recurring templates do not own receipts; generated sources own their own receipts.
Asset acquisition receipts already belong to the ordinary acquisition transaction;
generated depreciation does not acquire a parallel receipt workflow.

## TA-6 — Commercial web: Mixed-use copy and Expense-to-recurring conversion

Parent #221; follows completed #284 and extends existing copy/conversion owners.

Expose independent mixed-use-source copy and supported conversion of an existing
ordinary Expense to recurring. Reuse current preparation, provenance, source/
projection mapping, schedule and reference rules. Preserve no copied receipts,
new stable identities, fresh conversion baseline, linked-history guards and
confirmed cancellation/uncertain-create behavior. Test changed original versus
independent copy, invalid/protected conversion, success and two-entity isolation.
Existing #159 separately owns proposed mixed-use bulk source editing; it is not
an implemented internal workflow or a prerequisite to this migration slice.

## TA-7 — Commercial web: Maps address lookup and mileage route calculation

Parent #221; consumes existing Maps integration and #286 manual mileage workflow.
Coordinate #133's deployable Routes API key restrictions.

Expose existing supported location autocomplete and route-distance selection using
the established deployment-wide Maps credentials and separate quota identity.
Keep Google human Drive grants separate. Preserve manual fallback, explicit user
confirmation and storage of only confirmed locations/distance. Test provider/quota
failure, route confirmation, round-trip independent distance and profile isolation.
Review browser/server key restrictions before exposing an integration; do not
assume broad credential changes are authorized by this issue.

## TA-8 — Commercial web: QuickBooks mileage import

Parent #221; consumes the existing QuickBooks mileage parser and mileage services.

Add read-only scoped preview, diagnostics, duplicate detection and explicit import
using stable identities and fresh reference checks. Preserve one-decimal distance
normalization, supported source fields and mileage's separation from accounting.
Test invalid/duplicate sources, success, uncertain/failed create guidance and
two-entity isolation. #158 owns proposed mileage bulk edits/deletion/export scope;
the existing commercial manual filtered CSV is already delivered by #286.

## Existing owners and non-migration work

- #121: additional mixed-use asset depreciation, beyond delivered #285.
- #158/#159: proposed mileage/mixed-use bulk functionality, beyond supported
  internal behavior; record their commercial adapter requirements when implemented.
- #222/#13: native membership/onboarding/authorization; local Google/profile/admin
  controls stay operator-only. Do not copy deployment-password/all-profile access.
- #17 and #294: scheduled backup/NAS work; #223 owns byte recovery, durable jobs,
  retained artifact disposition and operations. These are not implemented by alpha.
- #260: complete PostgreSQL operator export; #224 owns customer export delivery.
- #220/#261: frozen format-13 Sheets-only workbook administration/recovery. `/data`
  does not send a PostgreSQL entity to Sheets. Separate internal tooling remains
  available only for its authorized unmigrated sources/recovery targets.
- #303: live owner execution; its required matrix may add long-tail workflows.
- #298/#224: commercial activation and recovery agreement; alpha has no authority
  to claim customer readiness or retire internal workflows.

## Draft #288 status update

The remaining runtime implementation is prepared: default hosted synthetic HTTP
composition loads an explicit environment/origin/entity-bound Drive secret file,
validates the selected grant/managed folders and reuses PostgreSQL metadata,
ReceiptService and GoogleDriveDocumentStore. The API image includes its requests
dependency and Render secret-file group; the read-only preflight and exact operator
runbook are in `docs/ALPHA_DOCUMENT_STORAGE.md`. Scope/failure/restart/isolation
tests use synthetic providers and disposable PostgreSQL, not retained staging.

Record the published reviewed commit/PR and its actual validation here after
publication. Keep the implementation prerequisite unchecked until the reviewed
change lands. Do not check provider configuration, staging suite, rollback,
manual acceptance or final handoff from local tests. Publish/link TA-1 through
TA-8 or record explicit approved exclusions; these drafts do not complete the
ticketing criterion. Parent #221 and initiative #124 remain open.

## Exact-candidate operator acceptance record template

Retain one sanitized record and private evidence references, refreshing evidence
after candidate changes. Leave each pending field pending until observed:

| Field | Required evidence (currently pending) |
| --- | --- |
| Candidate | Reviewed merged release SHA, main-push Full test suite URL/result, immutable image index/runtime digests and schema revision |
| Deployment | Exact staging target binding reference, promotion/smoke URL, observed `/version`/readiness |
| Drive custody | Independent staging profile/grant/root/Receipts references, protected file installation and preflight status; keep values private |
| Real-provider receipts | Authorized upload/attach, checksum/exact-byte download, unlink retaining bytes, retained-file relink and restart persistence |
| Six-case suite | Exact deployed checkout, explicit write consent, random marker, staging workflow URL, all six case results and `alpha_browser_passed` |
| Compatible rollback | Prior/candidate digest/schema, controlled window, prior and re-promotion smoke links, retained-data observations and candidate suite rerun |
| Manual quality | Tester/date, actual device/browser versions, touch/keyboard, zoom/reflow, visible focus and screen-reader observations; material findings resolved/tracked |
| Provider/recovery limits | Inspected Render/Neon/Google plans/regions/capacity/connections/idle behavior/quotas, DB/byte recovery actually available, accepted gaps and owner |
| Routing | Published narrow tracker links or explicit owner-approved exclusions for every TA draft and additional selected owner workflow |
| #303 handoff | Accepted alpha evidence link, owner-required workflow/auth/recovery matrix and concrete remaining prerequisites; live execution remains separate |

Publication, provider configuration, deployment, hosted writes, rollback, device
acceptance, issue closure and owner live migration require their applicable
authorization; this template supplies none of their evidence.
