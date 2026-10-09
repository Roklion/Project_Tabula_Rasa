# Commercial browser quality gate (#287)

This bounded gate supports the core technical-alpha work in [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221)
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It consumes #278's shell, #280's protected mutation path and #281/#282's core
workflows. This slice consumes active [PR #301](https://github.com/Roklion/Project_Tabula_Rasa/pull/301)
through `0cc7d3d38bfc9018090b251e8e2b704d373547fa`, including failed-switch draft
preservation. That dependency's merge/review
status remains separate from this quality slice.

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
python -m pytest tests/postgres/test_browser_baselines.py tests/postgres/test_browser_workflows.py tests/postgres/test_browser_quality.py --junitxml=browser-results.xml
```

The test endpoint must support creation/removal of disposable databases. Tests
never infer it from the application database, profiles or credentials. Each
native scenario creates a random test database, applies the current migrations,
seeds deterministic Alpha/Beta data and starts an isolated loopback HTTP server.
Fixture teardown stops the server, closes pools and drops that test database,
including after assertion failures. Missing database configuration, compiled
assets or required browser engines fails the required gate; ordinary Python runs
may still skip native browser tests when their environment is not installed.

Repository CI's **Browser and generated API contract** job installs all three
engines and runs this gate after building the SPA. **Full test suite** requires
that job to succeed on the current head/merge candidate. Failed runs retain
Playwright traces/screenshots and native JUnit results as CI artifacts. The
commercial release-image workflow consumes successful Repository CI on `main`.
No external customer data, ledger files or customer credentials are required.

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

#288 must consume the current-candidate CI results and rehearse its core workflow
matrix on the selected persistent staging deployment. These disposable-database
tests do not seed, mutate or certify a deployed staging service. The explicit
operator checkpoint and stage-specific secrets remain in
[Technical deployment](COMMERCIAL_DEPLOYMENT.md).

Receipt/document upload, attachment, read, unlink and recoverable partial results
remain gated by [#283](https://github.com/Roklion/Project_Tabula_Rasa/issues/283).
That browser path is absent at this starting dependency revision: extend the
same fixture/gate when it lands; do not replace it with a mocked successful
attachment or mark #287/#288 complete without that core-alpha journey.
Recurring/mixed-use, assets and mileage expansions remain #284–#286 and do not
block the default first alpha.

For alpha acceptance, record tested versions of the latest two stable Chrome,
Edge, Firefox and Safari releases plus current/previous iOS Safari and Android
Chrome. Real-device touch/keyboard, zoom/reflow, visible focus, and screen-reader
announcements require a recorded manual pass. Managed engine/emulated viewport
tests do not establish real-device or complete WCAG conformance. Keep any
material manual finding in a linked issue before accepting the gate; do not hide
violations by weakening axe rules. #223 owns production telemetry; #222/#224 and
#298 retain identity, external-beta and commercial acceptance boundaries.

Reuse map: inspected the existing native browser/server/database fixtures,
protected/create editors, shared fields/states, shell, design and canonical
workflow guides. Extended those tests and components. New code owns a small
confirmation presentation component, field-error association and accessibility
assertions; it introduces no parallel accounting, persistence, retry or fixture
seed workflow.
