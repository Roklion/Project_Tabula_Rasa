# Commercial UI follow-up #401

This is post-acceptance work following completed [EPIC #323](https://github.com/Roklion/Project_Tabula_Rasa/issues/323)
and [#331](https://github.com/Roklion/Project_Tabula_Rasa/issues/331), under
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It preserves their accepted visual foundation and bookkeeping contracts.
It does not reopen their acceptance, authorize deployment/live writes, or satisfy
external-beta gates #224/#348, identity EPIC #222, or owner cutover #303.

## Scope and dependency inventory

Base application: `5693ebb` (October 19, 2026). At this revision, #385–#388 are
open and their business-first replacement is absent from main. This change can
deliver shared fixes and the generic table-filter enhancement now. **Issue #401
must remain open for verification against the final replacement UI**, current-head
hosted CI/reviews, and the staging latency investigation. Existing legacy screens
are tested as current callers, not claimed as the final business-first product.

| Finding | Implemented owner and coverage | Remaining acceptance |
| --- | --- | --- |
| UI-001 selector overflow | Shell context grid and children constrain intrinsic widths; native selector clips long labels; the complete selected business name wraps above it. Desktop/390px/320px, focus and bounds checks. No legacy selector-specific redesign. | Recheck #388's final flat My Businesses selector and names. |
| UI-002 action separation | Existing shared actions spacing around ownership grant, separate from ordinary member edits; focus and disabled styles unchanged. | Recheck #387's business-scoped member surface. |
| UI-003 confirmation feedback | Shared ConfirmationDialog live progress; MemberEditor guards submission, retains failures and blocks uncertain resubmission; MemberAdministration owns confirmed success and existing scoped invalidation. Delayed success/reauthentication/network failure tests. | Recheck #387's final flow; reproduce the reported 10–15s staging latency only through separately authorized hosted investigation. No backend/performance cause established locally. |
| UI-004 section rhythm | Shared 32px token between independent sections, including Dashboard actions/Report period and explanatory text/Add a business; measured browser gaps. | Recheck replacement onboarding sections from #386/#387. |
| UI-005 setup ending | Same shared section spacing before the invitation card, with a measured gap after Review defaults. | Recheck #386's supported business creation replacement; do not reintroduce Add business to an existing workspace. |
| UI-006 Page placeholder | Current workspace route has a contextual shell title; unknown routes use Tabula Rasa with their own Page not found heading. Other route families retain existing contextual titles. | #386–#388 must provide their final business-first route labels. |
| UI-007 table filters | One FilterPanel used by Transactions and Mileage, with keyboard toggle, expanded state/controlled content, visible scope summary, retained mounted inputs/results and scoped presentation preference. | Implemented for all currently supported above-table filter panels; future panels should reuse it. |

Route audit used `app/router.tsx` and mounted feature owners: Dashboard/Reports;
Transactions and Journals; Accounts/Categories/Payees/Tags and their create/merge
routes; Assets/Mixed-use/Recurring lists, detail/create/copy/conversion/history;
Mileage log/create/detail; ordinary and mixed-use Receipts; Data & backup/imports;
Workspace & members; and signed-out/setup/recovery routes. Only Transactions and
Mileage currently expose a filter panel directly above a record table. Report
periods also govern summaries/metrics, so they remain expanded. Export selectors,
import previews, receipt recovery, history tables and create/edit forms are not
filter panels and remain unchanged.

Reuse map: inspected Shell/EntitySelection, tokens, ConfirmationDialog,
VisualPrimitives/States, WorkspacePage/Onboarding/InvitationAcceptance,
LedgerPage/LedgerTable, MileagePage, ReportsPage, route owners, design.md and the
canonical commercial guides. Extended shared shell/layout and confirmation owners;
kept payloads, query/filter values, cache invalidation and security with their
existing owners. New FilterPanel owns presentation only. There is no parallel
filter engine, authorization model, mutation retry system or styling framework.

## Validation and evidence

- Production build/TypeScript, ESLint and 117 frontend tests pass.
- 25 scoped native PostgreSQL API/browser checks pass in disposable PostgreSQL
  18.6, with the compiled frontend, fake signed OIDC and synthetic users. Coverage
  includes invitation lifecycle, role/last-owner/stale/recent-auth controls,
  two-user/workspace switching, CSRF and isolated cache/session behavior.
- `ui-followup.spec.ts` checks four representative routes at 1440px/390px/320px,
  no page-wide overflow, selector focus/width, section gaps and axe checks;
  filter keyboard/collapse/result/reset/navigation behavior; delayed membership
  success, reauthentication rejection and uncertain network response without retry.
- Existing core-surface checks cover sorting/search, complete journals, financial
  statements, dirty cancellation, keyboard/table navigation and read-only behavior.
  The final affected desktop browser run passed 27 tests across ui-followup,
  core-surfaces, shell and forms-secondary, including narrow viewport sweeps.
- Baseline capture uses unchanged application `5693ebb` in an isolated checkout
  with only the new capture test overlaid. `TABULA_RASA_UI_401_BEFORE=1` skips new
  visual assertions for this baseline capture only; behavioral tests remain active.
  Current application captures run without that flag.
- Retained local package: `web/test-results/issue-401-evidence/{before,after}`.
  Each capture manifest identifies revision, public-source changes/hash, browser
  version, route, viewport and PNG checksum. Baseline and implementation are kept
  separately. This ignored package contains synthetic transport data only, without
  real emails, provider credentials, receipt bytes or ledger data.
- Agent visual inspection includes long-label workspace at 320px, expanded ledger
  at desktop and pending membership confirmation. Automated axe/viewport/focus
  evidence is not human screen-reader, browser zoom or physical-device acceptance.

Repeat current checks from the worktree root:

```powershell
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
npm --prefix web run test:browser -- --project=desktop --workers=1 e2e/ui-followup.spec.ts e2e/core-surfaces.spec.ts e2e/shell.spec.ts e2e/forms-secondary.spec.ts
git diff --check
git diff origin/main...HEAD
```

Required Full test suite CI and independent Codex/Gemini review still apply to
the published current head. This local implementation request does not authorize
pushes, GitHub writes, deployment or closing any acceptance checklist.
