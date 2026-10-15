# Integrated commercial UI acceptance (#331)

This record assembles [#323](https://github.com/Roklion/Project_Tabula_Rasa/issues/323)
under [#124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It consumes the [current route inventory and design decisions](COMMERCIAL_UI_FOUNDATIONS.md)
and [browser quality gate](COMMERCIAL_BROWSER_QUALITY.md). Functional success,
visual review, manual accessibility and release approval are separate results.

## Workstream traceability

| Workstream | Implementation and evidence | Integrated coverage |
| --- | --- | --- |
| #325 shared foundation | [#325](https://github.com/Roklion/Project_Tabula_Rasa/issues/325), merge `e29605d`; foundation audit/evidence in the guide above | `foundations.spec.ts`: controls, table weight, keyboard, pending/error/success, complete route-family sweep |
| #326 navigation | [PR #365](https://github.com/Roklion/Project_Tabula_Rasa/pull/365), merge `316a17d` | `core-surfaces.spec.ts`: selected links, menu, dirty cancellation and focus; reference-management grouping under #331 |
| #327 dashboard/reports | [PR #365](https://github.com/Roklion/Project_Tabula_Rasa/pull/365), [CI/evidence](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38200879198) | Populated/negative/zero/empty/unavailable/loading/error summaries, long names and exact decimal strings |
| #328 ledger/filters | Same PR #365 and CI above | Complete grouped entries, filters/reset, source ownership, ordinary weight, right-aligned numbers and keyboard table scrolling |
| #329 core forms | [PR #369](https://github.com/Roklion/Project_Tabula_Rasa/pull/369), merge `3b73a96f`, [CI/evidence](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38409645626) | `forms-secondary.spec.ts`: transaction/journal/reference fields, protected draft/baseline and validation/confirmation |
| #330 secondary/receipts | Same PR #369 and CI above | Assets, recurring, mixed-use, mileage and receipt/recovery/read-only/availability surfaces; identity availability remains with #312 |
| #331 integrated acceptance | This harness and record; exact tested revisions are in retained manifests | Representative 1440px/390px/320px captures, 720px/320px effective zoom reflow, manual preview and explicit review process |

Sibling issues #325–#330 are closed with their own acceptance evidence. Their
results do not automatically pass this integrated candidate. The route inventory
identifies unsupported workflows and #314/#317 identity/onboarding exclusions;
newly implemented identity routes need their functional owner's visual review
before external beta.

Reuse map: inspected the mounted router/Shell, RecordList callers, shared fields,
mileage grids, existing synthetic browser suites and native PostgreSQL journeys.
Extracted their existing transport responses into `core-fixture.ts` and
`secondary-fixture.ts`; both automated tests and manual preview consume them.
`visual-evidence.ts` owns capture/provenance only. New logic is limited to evidence,
an opt-in synthetic preview and presentation fixes accepted during manual review.
No parallel bookkeeping, persistence, form state, retry or authorization owner.

## Repeatable evidence and retention

From the worktree root, with pinned Node 24 dependencies installed:

```powershell
npm --prefix web ci
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
$env:TABULA_RASA_SMOKE_PORT = '5191' # unused loopback port
npm --prefix web run test:e2e -- --workers=1 --output=test-results/331-final
git diff --check
git diff origin/main --stat
```

The existing Playwright projects cover Chromium desktop/mobile emulation,
Firefox and WebKit. The suites retain PNGs and `revision.json` for each test,
including failures. Each screenshot identifies its route, actual CSS viewport,
browser engine/version, device scale, capture time, reflow scenario and PNG
SHA-256. The manifest records actual Git HEAD, worktree changes, platform, test
result/retry and a hash of public application/harness sources. It never substitutes
an operator-supplied revision for the observed HEAD. A dirty worktree is explicitly
development evidence; rerun from the clean candidate for exact-commit sign-off.

720px and 320px exercise effective layout widths equivalent to 1440px at 200%
and 1280px at 400%. These are CSS reflow checks, **not actual browser zoom**.
Real zoom, physical-device touch and manual accessibility remain separate below.
Native API/PostgreSQL suites retain functional/failure/isolation ownership;
intercepted screenshots do not replace those tests.

Keep before and after outputs in different ignored directories. Capture the
untouched baseline before editing; keep its own revision metadata. The initial
#331 baseline is `3b73a96fe538a8a5105b2cc590561338f158e0d5` in
`web/test-results/331-before`, with the older suites' revision metadata. Those
older manifests lack per-image browser/route fields: do not silently relabel them
as new-format evidence. `web/test-results/331-comparable-before` additionally
retains new-format captures from a disposable checkout of that original SHA,
with only the current capture harness/fixtures overlaid. Its metadata correctly
reports the harness changes; `git diff --exit-code -- web/src` confirmed untouched
application sources. The same three representative capture scenarios ran with
Chromium at 1440px/390px/320px. New-format candidate captures supersede development
outputs; retain both when sharing the comparison. Prior workstream before/after
captures remain linked through their implementation PRs and foundation guide.

Repository CI already uploads `web/test-results/` in **browser-results** even on
failure. On publication, attach the sanitized local before/after package or link
its retained artifact alongside the current CI candidate; local ignored files
alone are not a durable hosted handoff. Keep generated validation output out of
Git. Retain the accepted evidence before Actions artifacts expire.

### Intentional screenshot change review

1. Identify baseline/candidate revisions, application/harness changes, platform,
   browser version, device scale, viewport and route. Compare matching captures;
   different engines/fonts/scale are separate observations.
2. Inspect Dashboard/Reports, ledger/selected filters, transaction/journal forms,
   mileage and receipt/recovery at desktop and both narrow widths. Review typography,
   primary/secondary actions, aligned fields and financial columns, ordinary row
   weight, long labels, empty/loading/error feedback and local table overflow.
3. Record every changed appearance as an intended design/user decision or a
   defect with scope, owner and disposition. Functional/axe success is supporting
   evidence, not visual approval. Do not use `--update-snapshots` to accept changes:
   these captures are evidence, with no blindly replaceable golden baseline.
4. Fix material defects, rerun affected checks/captures, and obtain manual
   re-review. Link accepted exclusions individually. Replaced or superseded
   evidence cannot establish current-candidate acceptance.

## Manual review preview and record

```powershell
npm --prefix web run dev -- --config vite.visual-review.config.ts --host 127.0.0.1 --port 5192 --strictPort
```

For phone review on the same trusted network, explicitly use `--host 0.0.0.0`
and the machine's LAN address. This is a local synthetic preview, not a deployed
environment. The explicit preview Vite configuration and adapter reuses existing test responses, disables the
real API proxy and terminates all API requests. Writes are rejected, and file/auth
requests never reach a provider. Draft, navigation and error interactions work;
it does not implement persistence, receipt bytes, successful saves or complete
filter-backend behavior. Restart ordinary Vite without the preview config when finished.

| Review item | Required recorded observation |
| --- | --- |
| Candidate and reviewer | Actual SHA plus dirty/source hash if applicable, tester/date, route list |
| Desktop | OS/browser/version, 100%/200%/400% browser zoom; labels/actions remain reachable, no overlap or page overflow |
| Keyboard | Tab/Shift+Tab order, visible focus, native listboxes, table scrolling, selected routes; keep/Escape/opener restoration and successful-navigation focus |
| Phone/device | Actual device/OS/browser/version, portrait/landscape, touch menus/selection/scrolling and pinch zoom; emulation is not device evidence |
| Contrast and state | Manual reading of essential/secondary/disabled/error text and focus/selected indicators alongside automated axe; state is understandable without color |
| Result | Pass, defect with owner, or explicit accepted exclusion; observations that were not made stay pending |

October 13, 2026 review: the maintainer reported “visual functionality ok” on
the synthetic preview, then identified desktop mileage-filter misalignment,
repeated Categories/Payees/Tags titles and inconsistent main-menu grouping.
The shared field grid now keeps compact controls at the top, the list owner
removes repeated visible titles while retaining accessible table names, and
Categories & contacts owns all three reference routes. Regression checks cover
desktop/narrow layouts, named tables, edit/empty/read-only states, nested create/
merge routes and dirty navigation.

Broader form/table appearance was rejected as too bland. The maintainer selected
**Soft workspace**, explicitly requested a light palette and questioned oversized
inputs. The implemented direction uses pale blue-gray canvas/forms/controls,
soft corners and restrained table surfaces, with 40px desktop controls and 44px
touch/narrow controls. Form/editor width is bounded at 960px. `design.md` records
the approved commercial palette separately from the internal Streamlit palette.
Further owner review requested stronger table presentation and clearer secondary
actions. Primary names/amounts, quiet secondary details, text status/type badges,
inline row actions and desktop action-column pinning now share existing owners.
All accounting fields remain available. Writer links to Assets/Recurring/Mixed-use
details now say Manage; read-only links say View. Route destinations, guarded
commands and loaded baselines remain unchanged.
The final spacing/badge feedback adds a 16px gap below mileage CSV download and
separate Expense / Mixed-use pills, retaining the existing combined accessible
row name and source-owned mutation boundary.
The maintainer accepted the revised visual appearance in this chat on October 13,
2026, after the final spacing and separate-pill feedback. This is retained human
visual acceptance of the synthetic preview, independently of automated success.
Post-integration acceptance also includes current main `97dc8d5` (merged PR #367):
its three import uploaders, mixed-use copy and expense-to-recurring screens reuse
the current fields/tables. Existing ledger bulk/copy selection, baseline and
uncertain-write owners were preserved through the ledger conflict resolution.
The new representative route captures cover desktop/390px/320px; native tests
remain responsible for imports/copy/bulk success, failure and isolation behavior.

**Visual appearance accepted; detailed device/accessibility and hosted CI/review
completion remain separate.**
Actual manual browser/device versions, zoom,
touch, keyboard and contrast observations have not been supplied, so that
specific acceptance is also pending. No material visual defect is declared an
accepted exclusion by automated success alone.

## Initiative handoff and independent gates

- **#323:** implementation slices are traceable above; #331 stays open until
  visual/manual results and current-publication review/CI conditions are satisfied.
- **#288:** the issue's latest acceptance record supersedes older “pending” text
  in historical guides. It closed October 11, 2026 with restricted synthetic-alpha
  provider, six-case staging, receipt persistence and compatible rollback evidence
  for release `808fb84c0a6bcba6bfaaaa55013968a73f4c6f7a`. Its owner-approved
  screen-reader exclusion applies to that alpha only. This local candidate does
  not refresh that hosted release or establish a broader accessibility pass.
- **#224 / #348:** consume accepted current-candidate visual evidence plus newly
  delivered identity/onboarding screens. Named users/tenant isolation, portability,
  legal/privacy, recovery, operations and cohort/operator approval remain their
  owners' independent external-beta requirements. #298 retains any applicable
  commercial authority/recovery sign-off; #342/#338 retain capacity/byte-recovery
  work. Screenshots authorize no deployment, provider write, live migration or
  external admission.

## PR #368 integration

The candidate also incorporates PR #368: selected/full financial CSV downloads,
mixed-use receipts and optional Maps mileage. Its extracted `LedgerTable` remains
the single owner of export/Bulk selection and grouped posting rendering; the
accepted badges, description emphasis and pinned Actions header move there.
Export and receipt surfaces reuse existing shared controls. Maps guidance and
calculation span a complete field-grid row before editable mileage.
Synthetic configured-Maps capture uses a local test widget, never the real
provider; native workflow checks own calculation, persistence, receipt recovery
and CSV semantics. Earlier clean `211eec7` evidence is historical after this
integration; retain fresh candidate manifests for current sign-off.

Additional maintainer feedback adds an 8px lookup-button gap and a shared
labeled file drop zone with a styled native chooser for all receipt/import
selectors. The picker only supplies files to existing owners; it rejects
multiple files for single-file importers, ignores disabled/text-only drops,
and preserves receipt reselection/reset behavior. Native workflow and focused
picker/drop tests cover unchanged explicit write and recovery boundaries.
