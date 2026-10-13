# Commercial UI foundations (#325)

This is the shared-foundation slice of [epic #323](https://github.com/Roklion/Project_Tabula_Rasa/issues/323)
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
[design.md](../design.md) owns intended appearance and interaction;
[core workflows](COMMERCIAL_WORKFLOWS.md) and [concurrency](COMMERCIAL_CONCURRENCY.md)
own the commercial behavior. This slice keeps the existing React application
runnable without changing accounting, persistence, authorization or mutation policy.

## Requirement / implementation audit

Audit baseline: `808fb84` on current `origin/main`. The following discrepancies
were identified before choosing behavior. General visual rules apply to React;
Streamlit-specific interaction rules do not override its explicit commercial contract.

| Design requirement | Existing owner / observed gap | #325 disposition |
| --- | --- | --- |
| Visual tokens: colors, type roles, 4px spacing grid | `web/src/styles/tokens.css` had only seven color aliases, literal geometry and no type roles | Extend this owner with the full palette, role sizes/weights, spacing and geometry; preserve aliases for existing consumers |
| 16px primary surface padding; modest borders/radii | `.surface` used 24px | Use shared 16px padding; no extra card wrappers |
| Blue primary, neutral secondary, red destructive actions | Native buttons shared the same blue-text style; create submit matched its alternative | `VisualPrimitives.tsx` supplies `ActionButton` tones; create submit is primary, back/keep is secondary, confirmed permanent delete is destructive |
| Visible focus; legible disabled/pending states; errors near controls | Focus used only a light outline; disabled buttons faded; field errors already had associations | Dark primary outline plus focus-token halo; neutral disabled styling; pending action retains its name and adds `aria-busy`; preserve `Fields.tsx` / `fieldErrors.ts` ownership |
| Input/select/date/textarea/checkbox consistency | Textarea had no styling; multiple select used single-control rules | Shared 44px minimum single controls, 128px minimum native listboxes, 112px minimum vertically resizable textareas; visible checkbox accent; no custom selection model |
| Page/section headers; actions near relevant content | Page-local heading/action markup | `PageHeader` in Accounts; `SectionHeader` in existing `CreateEditor`; both retain native headings |
| Ordinary table-body weight; compact rows; subtle separators | `<th scope="row">` inherited browser bold; cells used larger padding | Explicit 400 body / 600 column-heading weight; 40px minimum row geometry, 13px type, shared separators/hover/selection hooks |
| Comparable amounts right-aligned, tabular figures | Existing `.amount` hook; Accounts heading was left-aligned | Extend `.amount` / `.numeric`; align Accounts opening-balance heading and values; preserve decimal strings |
| Wide tables scroll locally; long labels usable at 320px | Existing focusable regions; Accounts repeated long names in action text | `TableRegion` retains named keyboard-scrolling regions; `.tableText` wraps name/parent cells; visible Edit keeps the full account name in its accessible label |
| Major metrics 26–32px, quiet labels and semantic states | `.metrics dd` used 22px; label inherited bold `dt` | Shared 28px value / ordinary label roles, tabular numerals, wrapping and optional state/context hooks; report layout remains #327 |
| Status uses text plus semantic roles | `States.tsx` already owns safe status/alert messages | Tokenize success/error/warning; loading uses neutral notice styling; no spinner-only state or new recovery workflow |
| Management table native row selection in generic/internal contract | Commercial tables expose per-record Edit with stable IDs | Preserve the documented commercial action model; introducing row selection is outside #325 |
| Tabs in generic/internal workflow guidance | Commercial workflow divisions are distinct router destinations | Preserve semantic links and dirty-navigation guards; selected navigation/action migration belongs to #326 |
| Native Streamlit controls and Google response confirmation | Commercial uses native HTML, React forms and service-confirmed HTTP mutations | Retain commercial transport/state owners, original baselines and no automatic retries; no Streamlit plumbing or new Google path |

No **Proposed behavior** section was activated. Sidebar geometry/navigation,
financial grouping, ledger/filter layout and full form migration remain #326–#330;
integrated visual acceptance remains #331. #222 retains identity/onboarding and
#288 retains hosted alpha/receipt/rollback/device acceptance. Local visual checks
do not satisfy those separate release gates.

## Shared ownership and consumer contract

`tokens.css` is the sole shared stylesheet/token owner. Existing short aliases
(`--surface`, `--secondary`, `--border`, `--hover`, `--selected`, `--primary`,
`--focus`) remain available. Use descriptive tokens for new code; avoid copying
palette/type/spacing values into page styles. `--text-muted` is palette metadata,
not an instruction to use low-contrast text for essential descriptions.

`ActionButton` forwards native button attributes/events, defaults to
`type="button"`, and permits an explicit submit type. `pending` disables the
button and marks it busy without changing its accessible name. It does not own
confirmation, retry, mutation or draft state. Navigation stays a real link;
`.button` is the existing primary-link hook, with `.action-secondary` available
for a secondary styled link. Do not use `aria-disabled` alone to prevent navigation.

`PageHeader`, `SectionHeader` and `TableRegion` only own semantic markup and
layout. Field labeling/error association stays with `States.Field`, shared
`Fields.tsx` adapters and `fieldErrors.ts`. Form validation, loaded metadata,
baseline capture, context/cache isolation and successful reset remain with
`CreateEditor`, `ProtectedEditor`, `useLoadedForm` and `ScopeBoundary`.
`ConfirmationDialog` keeps its focus, Escape and pending-operation behavior;
callers select a destructive tone only for an actually destructive operation.

Table consumers keep their native table/caption/header semantics and stable IDs.
Use `.tableText` for deliberate wrapping, `.amount`/`.numeric` for comparable
columns and `aria-selected` only when a workflow implements selection. The 40px
row size is a minimum; wrapping and accessible action targets may increase it.
Metrics use `.metrics`, optional `.metric-context` and `.metric-positive`,
`.metric-negative`, `.metric-warning`, `.metric-loading`, `.metric-unavailable`.
Always explain state in text; unavailable is an em dash, never invented zero.

Reuse map: inspected router-mounted shell, fields/states/confirmation,
reference creators/editors, create/protected form owners, Accounts, ledger,
reports and secondary/document/mileage callers. Extended their existing styles
and presentation seams. New logic is limited to small native presentation
wrappers and synthetic browser checks; no parallel domain/form/state implementation.

## Reproducible visual evidence

From the worktree root, after `npm --prefix web ci`:

```powershell
$env:TABULA_RASA_SMOKE_PORT = '5185' # any unused loopback port
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
npm --prefix web run test:e2e -- --output=test-results/issue-325-after
git diff --check
git diff origin/main --stat
```

`web/e2e/foundations.spec.ts` intercepts every API call with synthetic data.
It retains Accounts/account-create PNGs at 1440x1000, 390x844 and 320x844,
route-family PNGs at desktop/320px, plus `revision.json` identifying the tested
Git revision and any uncommitted files. Only a clean revision represents that
exact commit. Retain a baseline in a separate output directory; the runner
replaces only the selected output directory. Local evidence stays in ignored
`web/test-results/`; attach sanitized before/after evidence when publishing.
Do not commit generated validation output or private data.

The checks include zero axe violations on representative surfaces, bounded
table scrolling, ordinary row-header weight, native listbox keyboard selection,
visible keyboard focus, preserved field-error associations/drafts, disabled
pending actions, confirmed-success reset and confirmation focus/Escape behavior.
Route-family checks cover Dashboard/Reports, reference data, transactions/journals,
assets, mixed-use, recurring, mileage, receipts and the current Data & backup
availability surface. Inspect retained screenshots as well as test results;
automated success alone is not visual sign-off. Managed engines do not establish
real-device or full accessibility certification.


## Wave 1: navigation, reports and ledger (#326–#328)

This slice of #323 under #124 consumes the merged #325 foundation. It keeps the
commercial summary catalog and real route navigation; Streamlit tabs, monthly
charts, recent-activity widgets, bulk selection and separate as-of controls are
not implicitly migrated. Identity/session/onboarding remain #314/#317; #329/#330
own remaining form/secondary presentation and #331 owns integrated acceptance.
Hosted alpha, provider/rollback/device and external-beta gates remain independent.

| Design requirement | Shared implementation / preserved owner |
| --- | --- |
| Visible current route; semantic navigation; narrow wrapping | `navigation.ts` route inventory; `WorkflowNav` link list; `Shell` main-route marker and existing menu/focus ownership |
| One dominant action and grouped alternatives | Existing `PageHeader`, primary `.button`, neutral `.action-secondary`; Dashboard View ledger / Set up accounts and Transactions Add transaction / Add journal |
| Clear financial scopes and hierarchy | Actual router-mounted `ReportsPage`; `DateRangeFields` shared with ledger; `SectionHeader`, `.reportSections` and `.reportMetrics` |
| Exact values; non-color-only states | Server decimal strings remain intact; sign-based net/earnings styling; textual equation/difference/unavailable states; explicit empty groups |
| Compact readable financial tables | `TableRegion`, `.tableText`, `.amount`, normal body weight; journal group boundary and subordinate postings; stable logical entry IDs and source owner links |
| Aligned accessible filters; return to default scope | Shared fields with `.ledgerFilterGrid`, multiline equal-height native listboxes, selection guidance and full selected-label summaries; existing query/search/sort/reset handlers |
| No page overflow at desktop/390px/320px | Wrapping controls/navigation/labels and named keyboard-scrolling table regions; all accounting columns retained |

Reuse map: inspected Shell/router/navigation, shared primitives/fields/tokens,
router-mounted ReportsPage/LedgerPage, the unused foundation Dashboard,
RecordList, reference/bookkeeping editors, mixed-use/recurring and mileage routes,
loaded forms, scope boundary and guarded navigation. Reused their original
state/query/mutation owners; extended shared headers/table hooks and styling.
New logic is limited to route-group selection, a native date-control adapter,
and report/ledger presentation. No parallel accounting, persistence, form,
identity, retry or navigation-blocking state machine was introduced.

`web/e2e/core-surfaces.spec.ts` retains synthetic dashboard/report/ledger PNGs at
1440x1000, 390x844 and 320x844 plus report loading/zero/unavailable/error and menu
surfaces. `revision.json` records HEAD, uncommitted status, browser project and
viewport; a clean status identifies the exact tested revision. Before screenshots
were captured from #325's merge `e29605d` before source edits. Local outputs remain
ignored in `web/test-results/326-328-before` and `web/test-results/326-328-final`;
retain both and attach sanitized evidence when publishing. Do not commit generated
validation output. Native listbox wrapping varies across engines; full selection
summaries make long selected labels readable in every engine.

Reproduce from the worktree root (unused loopback port required):

```powershell
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
$env:TABULA_RASA_SMOKE_PORT = '5186'
npm --prefix web run test:e2e -- --workers=2 --output=test-results/326-328-final
git diff --check
git diff origin/main --stat
```

Checks cover keyboard scrolling, WCAG axe checks on representative core surfaces,
normal ordinary row weight, exact large/negative/zero decimals, current links,
menu closing/focus restoration, dirty cancellation, read-only affordances,
whole-journal search/grouping, source ownership, transport filters and reset,
report scope/equation/error/loading behavior. Read-failure notices offer Reload without implying an editable draft; write
failures retain their existing draft-preservation guidance. The existing foundation sweep
continues to cover every route family. Inspect the PNGs as well as the assertions;
local managed-browser evidence does not certify real devices, hosted acceptance,
CI/reviewer completion or the entire design initiative.

## Wave 2: forms and secondary routes (#329/#330)

This independently runnable presentation slice completes the remaining existing
route families under #323 within #124. It preserves bookkeeping services,
selected-entity/session boundaries, loaded baselines and recovery ownership.
The generic Streamlit tab/row-selection/receipt-provider requirements do not
replace the documented commercial route links, explicit record actions and
portable document inspection. No Proposed behavior or absent workflow is added.

| Design requirement | Reused owner / extension |
| --- | --- |
| Visible labels, related desktop fields, narrow stacking | Existing `Fields`/`States.Field`; shared `FormSection` adds headings and at most two related desktop columns, stacking at 760px |
| Long notes and validation; deliberate native multiple selection | Shared textarea/input-mode adapters, combined hint/error association and full selected-label summaries; existing error mapping and inactive-reference choices |
| Action hierarchy, confirmation and dirty drafts | `CreateEditor`/`ProtectedEditor` and `ConfirmationDialog`; primary Save, neutral Back/commands, destructive permanent Delete; existing token and draft lifecycle |
| Readable journals with stable rows and visible totals | Existing `JournalFields`, posting IDs and journal-draft totals/validation; grouped target/side/amount/details and shared totals surface |
| Reference tables and merge lists | Existing `RecordList`, `TableRegion`, field/checkbox owners; wrapping/numeric column hooks and explicit merge guidance without a new selection model |
| Secondary source ownership and immutable history | Existing secondary field/command owners; shared detail summaries and scrollable depreciation/occurrence history; service allocation and command confirmations preserved |
| Mileage details, totals, filters and export | Existing mileage fields/form/CSV owners; grouped fields, wrapped table text, aligned distance heading, selected-tag guidance |
| Receipt progress, partial results and retained files | Existing receipt sequencing/recovery, native metadata disclosure and confirmation; section/action treatment plus visible read-only/unavailable/unlink guidance |
| Truthful availability | Existing Data & backup route shows unavailable browser controls, without inventing import/backup or promising completion |

The base control rule uses low specificity so multiline sizing, error borders
and disabled states can take effect. Native single selects use control-level
paint containment for WebKit's long-option overflow; the selected option,
keyboard behavior and dropdown retain their native owner. Page containers do
not hide overflow, and table regions retain intentional horizontal scrolling.

Reuse map: inspected the router, current core/secondary/mileage/document forms,
shared fields/visual primitives, draft/baseline/confirmation owners and canonical
guides. Extended these presentation seams and shared stylesheet. New logic is
limited to presentation adapters and synthetic browser fixtures; no parallel
accounting, reference validation, persistence, retry or mutation state owner.

### Complete current-route inventory

Original visual baseline: `6f0977579c23fcb8a60a9be2a680a27c9d30660f`.
Integration re-audit: `origin/main` at `2d4aea2`, including #311/#312 named-user
sessions, their receipt-abort guards and context-boundary availability screens.
The router and shell were checked together; list-mounted protected editors are
included even when they have no independent URL.

| Existing route or surface | Completed slice / explicit boundary |
| --- | --- |
| `/`, `/reports` | #327 summary/report body; #326 navigation/actions |
| `/transactions` including inline edit and source links | #328 ledger/filter/table; #329 shared protected transaction fields |
| `/transactions/new`, `/journals/new`, `/journals` including protected journal edit | #329 grouped shared fields, postings/totals and actions; #326 route navigation |
| `/accounts`, `/categories`, `/payees`, `/tags` and their `/new` routes, list-mounted editors | #325 Accounts foundation; #329 consistent reference fields/tables/edits and inactive states |
| `/payees/merge`, `/tags/merge` | #329 merge labels, sources, guidance and action hierarchy |
| `/assets`, `/assets/new`, `/assets/:recordId` | #330 register/create/detail, depreciation history, protected posting/override/retirement controls |
| `/mixed-use`, `/mixed-use/new`, `/mixed-use/:recordId` | #330 source/projection ownership, allocation and protected source fields |
| `/recurring`, `/recurring/new`, `/recurring/:recordId` | #330 future-only edits, occurrence history and confirmed generation/transitions |
| `/mileage`, `/mileage/new`, `/mileage/:recordId` | #330 manual log/create/protected or read-only detail, filters/totals/CSV; #326 workflow navigation |
| `/transactions/:recordId/receipts` | #330 linked/attach/recovery, read-only, unavailable and partial-failure surfaces; source-owned receipts remain with their functional owners |
| `/data` | #357/#364 provide three authorized import workflows; browser backups remain outside this slice |
| Unknown route / route-error fallback | #329 shared headers and recovery/navigation treatment |
| Shell/menu/entity selector/Terms/Privacy links | #326 shell; static legal documents keep their existing server owner and content; no legal or authorization change |
| Signed-out (`/signed-out` or unauthorized route), session-unavailable and setup-required states | #312 `ContextBoundary` retains identity/session ownership; #330 applies shared headers, surfaces and native Sign in/Sign out controls, preserving private-view unmount and receipt-abort guards |
| Complete authorized workspace/entity switching and first-use onboarding screens | #314/#317 remain open at the integration baseline; unfinished journeys are excluded, and their functional owners must consume the shared primitives when delivered. External OIDC-provider pages retain their provider owner |
| Maps, internal administration/provider secrets, remaining internal-only report catalogs and source receipt workflows | Unsupported commercial workflows retain their initiative owners; #357/#358/#362/#364 now provide the documented import/copy/bulk/conversion ports, and this visual slice does not retire the internal edition |

### Evidence and affected checks

`web/e2e/forms-secondary.spec.ts` intercepts synthetic transport for long-label
core forms, journal posting/error layouts, populated secondary detail/history,
mileage, receipt recovery/availability, read-only controls and integrated identity
availability screens. Screenshots cover
1440x1000, 390x844 and 320x844 with revision, worktree-change and viewport
metadata. The same fixtures capture the untouched baseline and changed revision
in separate ignored output directories. Inspect the PNGs alongside axe, keyboard
and overflow assertions; automated pass status alone is not visual sign-off.

From the worktree root:

```powershell
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
$env:TABULA_RASA_SMOKE_PORT = '5189'
npm --prefix web run test:e2e -- e2e/forms-secondary.spec.ts --project=desktop --workers=2 --output=test-results/329-330-after
git diff --check
git diff origin/main --stat
```

Retain baseline evidence in `web/test-results/329-330-before` and final evidence
in `web/test-results/329-330-after`; the output runner clears only its chosen
directory. Native compiled-browser tests additionally exercise actual HTTP and
disposable PostgreSQL success/failure, stale-baseline confirmations, partial
receipt recovery and two-entity isolation. Use the affected commands in the
commercial guides; current-head hosted CI/reviews remain required on publication.
This local work does not certify #331 integrated acceptance, #288 hosted/provider/
rollback/manual devices, #222 identity or #224 external-beta readiness.
