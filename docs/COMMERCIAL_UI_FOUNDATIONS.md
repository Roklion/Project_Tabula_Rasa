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
