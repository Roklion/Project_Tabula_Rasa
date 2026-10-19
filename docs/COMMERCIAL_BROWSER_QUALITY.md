# Commercial browser quality gate (#287)

This bounded gate supports the core technical-alpha work in [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221)
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It consumes #278's shell, #280's protected mutation path and #281/#282's core
workflows from merged [PR #301](https://github.com/Roklion/Project_Tabula_Rasa/pull/301),
including failed-switch draft preservation. This gate builds on that reviewed
workflow baseline; release acceptance is tracked in the owning issues below.

## Repeatable local and CI gate

Keep the selected Playwright framework from [ADR 0002](adr/0002-commercial-web-runtime.md).
Node Playwright checks the shell with controlled synthetic transport responses.
Python Playwright exercises the compiled React application through the production
HTTP handlers, application services and native PostgreSQL. Both use pinned
development dependencies; axe-core checks WCAG 2.0/2.1/2.2 A/AA rules with no
violation exclusions. [Playwright's accessibility guidance](https://playwright.dev/docs/accessibility-testing)
describes the automated/manual assessment boundary.

From the repository root in the active Python 3.12 development environment,
explicitly export `TABULA_RASA_TEST_DATABASE_URL` for a disposable test
administrator endpoint, then run:

```powershell
npm --prefix web ci
npm --prefix web exec -- playwright install chromium firefox webkit
python -m playwright install chromium firefox webkit
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
npm --prefix web run test:e2e
$env:TABULA_RASA_REQUIRE_BROWSER_TESTS = '1'
$native = Get-ChildItem tests/postgres/test*browser*.py | ForEach-Object { $_.FullName }
python -m pytest @native -ra --durations=20 --junitxml=native-browser-results.xml
```

The test endpoint must support creation/removal of disposable databases. Tests
never infer it from the application database, profiles or credentials. Each
native scenario creates a random test database, applies the current migrations,
seeds deterministic Alpha/Beta data and starts an isolated loopback HTTP server.
Fixture teardown stops the server, closes pools and drops that test database,
including after assertion failures. Missing database configuration, compiled
assets or required browser engines fails the required gate; ordinary Python runs
may still skip native browser tests when their environment is not installed.

Repository CI separates **Frontend, contracts and runtime image**, two required
**Browser UI** shards, and **Native browser (HTTP + PostgreSQL)**. Node UI and
native jobs each install all three engines; native builds its own SPA and uses
its own disposable database. **Full test suite** requires every partition on the
current head/merge candidate. Failed runs retain per-shard Playwright JUnit,
traces/screenshots and native JUnit results. The commercial release-image
workflow consumes successful Repository CI on `main`. No external customer data,
ledger files or customer credentials are required.

`npm --prefix web run test:e2e` remains the complete local Node check: run-once
HTTP/Git contracts followed by all browser/device UI cases. Use `test:contracts`
for browser-independent preview/digest changes, or `test:browser -- --shard=1/2`
and `--shard=2/2` to reproduce CI UI partitions (run both for complete coverage).
[Suite ownership and timing evidence](CI_TEST_SUITES.md) explains why the HTTP/Git
contracts no longer run four times and why real API/database journeys remain
independent required coverage.

## Bounded coverage matrix

| Surface | Automated coverage |
| --- | --- |
| Shell, deep links, loading/error/empty states | Chromium, Firefox and WebKit; 1440, 1200, 900, 390 and 320 CSS-pixel widths |
| Reference setup, transaction lifecycle, balanced journal creation/edit, ledger and reports | Real HTTP/PostgreSQL journeys at 1440x1000 and 390x844 in all three engines |
| Core create forms, shell, reference/ledger/report tables | axe scans at 1440x1000, 1200x900, 900x900, 390x844 and 320x844 in Chromium |
| Keyboard confirmation, focus restoration, business/draft isolation | All three engines at desktop/mobile widths; delete, reload, business switch, local close and blocked route navigation |
| Protected stale edit/delete and missing baseline | Existing #280 real two-client browser/API/PostgreSQL path, including desktop/mobile independently loaded forms |
| Loading, field validation, unexpected server error and dropped transport | Desktop/mobile; real delayed service read, actual 422/500 handlers and controlled dropped transport; no automatic mutation retry |

Tables remain complete and scroll inside labeled keyboard-focusable regions.
Checks reject page-level horizontal overflow, require modal keyboard wrapping and
Escape cancellation, and check that explicit route changes focus the main region.
Server-declared, unambiguous top-level field errors connect `aria-invalid` and
`aria-describedby` to a generic error message; ambiguous journal-posting leaf
errors remain in the shared alert. Drafts, stable create identities and original
protected baselines remain owned by the existing form/service implementations.

## Alpha acceptance and remaining coverage

The repeatable automated gate above uses disposable databases and synthetic
providers. It does not certify a deployed service or actual-device behavior.
[Technical alpha](TECHNICAL_ALPHA.md) defines the retained-staging workflow,
receipt and rollback procedure; [#288](https://github.com/Roklion/Project_Tabula_Rasa/issues/288)
records its completed bounded acceptance and approved screen-reader exclusion.
Recurring/mixed-use, assets and mileage have their own supported workflow guides;
existing-workflow ports are documented in [Workflow ports](COMMERCIAL_WORKFLOW_PORTS.md).

For each new release's accepted scope, record actual browser/device versions,
touch/keyboard, zoom/reflow, focus and accessibility observations or explicit
approved exclusions. Managed engines/emulation do not prove physical-device
behavior or comprehensive WCAG conformance. Keep material findings in a linked
issue; do not weaken axe rules to hide them.

Current work and decisions belong to [#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321)
(hosted identity), [#320](https://github.com/Roklion/Project_Tabula_Rasa/issues/320)
(security), [#348](https://github.com/Roklion/Project_Tabula_Rasa/issues/348)
(external-beta acceptance) and [#303](https://github.com/Roklion/Project_Tabula_Rasa/issues/303)
(live owner use). [#331](https://github.com/Roklion/Project_Tabula_Rasa/issues/331)
retains completed visual/device acceptance evidence; its old local candidate
status is not an outstanding-work list for later releases.

## Integrated visual acceptance

[#331 acceptance](COMMERCIAL_UI_ACCEPTANCE.md) extends these same browser suites
with per-image revision/browser/route metadata, representative effective-width
reflow, a shared-fixture manual preview and explicit intentional-change review.
The owning issues retain candidate-specific results and approved exclusions. Visual/manual sign-off and #224 external-beta gates
remain distinct from passing automated checks.
