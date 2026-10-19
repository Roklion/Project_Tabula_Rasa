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
results do not automatically pass this integrated candidate. Newly delivered identity/onboarding/business-access routes need their functional
owner's selected-release visual review before external beta; track that evidence
in #388/#348 rather than treating an older inventory exclusion as current status.

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
SHA-256. Schema 2 manifests record actual Git HEAD, public-source worktree
changes, platform, test
result/retry and a hash of public application/harness sources. It never substitutes
an operator-supplied revision for the observed HEAD. Public-source status uses
the same allowlist as hashing and excludes unrelated receipt/import filenames.
Its explicit scope does not attest repository-wide cleanliness; older schema 1
status was repository-wide. A dirty source worktree is explicitly
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

Repository CI uploads per-shard UI evidence in **browser-ui-1** and
**browser-ui-2**, and native evidence in **native-browser-results**, even on
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
real API proxy and terminates all API requests. Only the exact non-mutating mixed-use copy-draft and allocation POSTs are
admitted alongside supported reads. Writes are rejected, and file/auth
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

## Initiative handoff and independent gates

Completed visual, keyboard/focus/contrast/reflow and maintainer-reported physical
phone/zoom acceptance, with exact observations and limitations, are recorded in
[#331](https://github.com/Roklion/Project_Tabula_Rasa/issues/331) and
[PR #371](https://github.com/Roklion/Project_Tabula_Rasa/pull/371).
The current presentation contract is in `design.md` and
[UI foundations](COMMERCIAL_UI_FOUNDATIONS.md); this guide supplies the repeatable
capture/manual-review process, not a branch progress log. Keep evidence manifests
and real observations; do not invent missing device/browser metadata or treat
emulated width as physical touch/zoom evidence.

For later delivered identity/onboarding/business-access surfaces, record the
selected candidate's visual/manual evidence with
[#388](https://github.com/Roklion/Project_Tabula_Rasa/issues/388) and
[#348](https://github.com/Roklion/Project_Tabula_Rasa/issues/348).
[#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321) retains hosted
identity acceptance and [#342](https://github.com/Roklion/Project_Tabula_Rasa/issues/342)
retains operational evidence. Passing the earlier #331 scope or a new automated
capture does not admit customers or establish comprehensive accessibility.
[#288](https://github.com/Roklion/Project_Tabula_Rasa/issues/288)'s technical-alpha
screen-reader exclusion remains limited to its accepted scope. #224/#298 retain
external/commercial decisions; screenshots authorize no provider or live-data
operation.
