# CI execution and suite ownership

The current revision's **Full test suite** is the authoritative merge gate.
Component jobs run independently and the aggregate requires every dependency to
succeed. Browser checks, native PostgreSQL journeys and security tests keep their
own boundaries. This guide owns execution topology, local commands and timing
methodology; dated measurements and review progress belong in GitHub discussions.

## Required execution owners

| Family | Owner and isolation | Budget |
| --- | --- | --- |
| Python unit/application, supported Sheets/Streamlit/OAuth/profile/backup/recovery contracts, NAS client/TLS/encryption/isolated-restore smoke, tooling and Python lint | `python-suite`: complete discovery without filters; synthetic providers/temporary files | 30 min |
| PostgreSQL accounting/repository/API, authorization/session/entity isolation, concurrency/idempotency and migration contracts | Same Python job; disposable PostgreSQL 18.6 and per-test databases | Included above |
| Windows environment bootstrap | `windows-tooling`: PowerShell/Python 3.12 | 15 min |
| Frontend unit/fast checks, OpenAPI/client drift, TypeScript/build, HTTP/Git preview contracts and deployment-image inspection | `frontend-contract`: Node 24/Python 3.12; no database/browser installation | 15 min |
| UI, responsive behavior, accessibility and visual evidence with controlled transport | `browser`: two disjoint Playwright shards, all four desktop/mobile/Firefox/WebKit projects, two workers per runner | 20 min each |
| Critical browser journeys through compiled React, real HTTP/services/PostgreSQL, identity/workspace lifecycle and isolation | `native-browser`: its own build, three engines, disposable PostgreSQL and isolated loopback servers | 20 min |
| Current-revision aggregate | `full-suite`: always requires every dependency to succeed | 5 min |

Six component runners execute independently, followed by one aggregate. Matrix
fail-fast is disabled to retain both shards' diagnostics. No path filters,
optional components, blanket retries or scheduled-only suites are introduced.
CI policy tests execute the actual Bash gate with unsuccessful results for every
dependency: missing, pending, skipped, cancelled, timed-out and failed results
cannot satisfy it. Current-head triggers, PR cancellation, permissions and
release-image consumers are preserved.

The controlled-transport UI shards run in the official Playwright Noble image,
with its version matched to the lockfile's `@playwright/test`. Browsers and OS
libraries are preinstalled, avoiding per-shard apt downloads from regional Ubuntu
mirrors. Node 24 and npm dependencies still use the existing setup steps.
Update the image tag together with Playwright; CI policy rejects version drift.
The container uses an init process and host IPC for browser process cleanup and
Chromium shared memory. Native PostgreSQL/browser coverage retains its separate
runner and installation path. Both UI shards, all projects, worker limits,
artifacts, time budgets and the aggregate success requirement remain unchanged.

The Python job has no compiled SPA. Native browser scenarios retain prerequisite
skips there and run in the required native job with
`TABULA_RASA_REQUIRE_BROWSER_TESTS=1`. CI policy checks the explicit invocation
against every `tests/postgres/test*browser*.py` module. Accounting, isolation,
migration and recovery remain required on each PR.

## Contract and browser ownership

HTTP response and source-provenance checks run once in
`web/contracts/visual-review.spec.ts` through `playwright.contracts.config.ts`,
without browser engines or the SPA server. Page interactions retain all four
browser/device projects. Both use the shared preview fixture.

Controlled-transport UI checks and native real-storage journeys protect different
boundaries. Visual/responsive permutations remain required; overlapping scenarios
do not justify removing either boundary's coverage.

## Measuring CI changes

Keep measurement history in the owning issue or PR. The [CI partitioning measurements](https://github.com/Roklion/Project_Tabula_Rasa/issues/376) retain original failures, paired attempts and cost limitations;
they do not prove a later revision passed. Compare the same source/test inputs and
runner class, include failed/cancelled attempts, and record phase costs, counts/skips,
retries and shard imbalance. Occupied runner time is not billed usage or elapsed time.

## Visual-preview optimizer isolation

The shared `startVisualPreview` fixture gives every live test preview a unique Vite
optimizer cache under `web/node_modules/.vite-visual-*` and removes it on fixture
`close()` or startup failure. The fixture drains pending optimization before
shutdown/removal and retains lifetime ownership across Vite restarts. A worker
identifier alone is insufficient because preview lifetimes can overlap within one
worker. This prevents the normal dev server or another preview from deleting/replacing a
preview's optimized files. The run-once HTTP/Git suite includes a deterministic
dependency-URL regression; all four browser/device projects retain their existing
preview assertions. [Diagnosis and validation
boundaries](https://github.com/Roklion/Project_Tabula_Rasa/issues/384#issuecomment-6303989208)
preserve the original failed sample, explain the reproduced lifecycle and distinguish
local fix validation from CI execution policy's unchanged-source measurement pairs.

## Focused local commands and reporting

From the repository root with Python 3.12/Node 24 and pinned dependencies:

```powershell
python -m pytest tests/tooling -q
ruff check .
npm --prefix web ci
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
npm --prefix web run test:contracts
npm --prefix web exec -- playwright install chromium firefox webkit
npm --prefix web run test:browser -- --shard=1/2
npm --prefix web run test:browser -- --shard=2/2
```

Use `test:browser -- e2e/visual-review.spec.ts` for a specific surface. `test:e2e`
runs contracts then all UI projects; extra arguments select only the UI portion.
Native commands/prerequisites are in [Browser quality](../browser/TESTING.md#repeatable-local-and-ci-gate).
They use explicitly configured disposable databases, never application credentials.
Normal local validation stays scoped to affected behavior; CI is the full gate.

Download metadata using read-only GitHub CLI access:

```powershell
gh api repos/Roklion/Project_Tabula_Rasa/actions/runs/RUN_ID/jobs?per_page=100 > jobs.json
python scripts/summarize_ci_timings.py --jobs jobs.json --junit native-browser-results.xml
```

Use all pages of one completed attempt (currently fewer than 100 jobs). For a
rerun use `/actions/runs/RUN_ID/attempts/ATTEMPT/jobs`; never mix attempts. The
offline summary retains revision/conclusions and named phase costs. Completed
jobs with unavailable timestamps retain their conclusions and null durations;
`timing_complete: false` and null aggregate elapsed/runner costs prevent treating
unknown intervals as measured zeroes. Still-running jobs are rejected. JUnit
summaries retain aggregate counts/times only, never testcase names, properties,
failure messages or stdout/stderr. Review evidence before retention. Raw synthetic
CI JUnit/traces/screenshots have unique artifact names: `browser-ui-1`,
`browser-ui-2`, `frontend-contract-results`, `native-browser-results`,
`python-results` and `windows-results`.
