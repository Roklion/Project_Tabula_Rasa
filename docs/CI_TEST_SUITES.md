# CI suite ownership and evidence (#376)

Execution organization under [EPIC #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124), following
#295. Current-candidate `Full test suite` and independent Codex/Gemini review remain
mandatory. No new launch gate or external-beta readiness is implied. #221/#287/#331
own browser acceptance; #222/#320 own security acceptance. #377 owns supported-capability
retirement, and #339 owns environment/data cleanup. No supported workflow is retired.

## Required execution owners

| Family | Owner and isolation | Budget |
| --- | --- | --- |
| Python unit/application, supported Sheets/Streamlit/OAuth/profile/backup/recovery contracts, tooling and Python lint | `python-suite`: complete discovery without filters; synthetic providers/temporary files | 30 min |
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

The complete Python job has no compiled SPA: native browser scenarios retain
their prerequisite skips there and execute in the required native job with
`TABULA_RASA_REQUIRE_BROWSER_TESTS=1`. Its explicit invocation is checked against
every `tests/postgres/test*browser*.py` file. Inventory found four omitted modules:
transaction imports, mileage imports, transaction bulk/copy and recurring
conversion/copy. They add ten native cases to the previous 115-case invocation,
for 125 at the implementation baseline. Accounting, security/isolation, migration
and recovery remain required on each PR.

## Demonstrated repetition and independent contracts

Five visual-preview checks inspect synthetic HTTP responses or Git/source
digests without requesting a browser fixture. Their invariants are exact
server routing/read-only rejection and reproducible public-source provenance;
none depends on browser engine, viewport, layout, DOM or input behavior. Their
assertions move unchanged to `web/contracts/visual-review.spec.ts`, running once
through `playwright.contracts.config.ts` without engine installation or the SPA
web server. The two page-using preview tests retain all four projects, including
the mixed-use test that combines HTTP preparation and page behavior. A small
shared preview-server helper preserves their configuration.

Controlled-transport Node UI tests and native real-storage journeys protect
different boundaries; similar cases remain independent. All visual/responsive
permutations stay required. No schedule change is justified by these measurements.

Reuse map: inspected CI/policy tests, Playwright projects/visual evidence and
preview fixtures, native database/server fixtures, development/browser guides.
Extended those owners; extracted only preview-server startup. New logic owns
offline timing summaries and execution policy. Existing native fixture imports
need no restructuring for this partition. No parallel business rules, persistence,
retry/recovery or generic fixture framework is introduced.

## Sanitized baseline and cost rationale

[Run 38843378193](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38843378193),
attempt 1, tested candidate `0709c3ce9f061118614142e0df0a27b8c577909b`, is the
issue's timeout example. Retained [job/step metadata](evidence/ci-376/baseline-jobs.json)
contains no test stdout, ledger contents or credentials. API timestamps give:

| Cost | Observed seconds |
| --- | ---: |
| Earliest job start to aggregate completion | 1,227 |
| Sum of occupied runner intervals, including aggregate | 1,907 |
| Python job / pytest step / pip installation | 564 / 503 / 31 |
| Windows job / tests / pip installation | 118 / 30 / 66 |
| Combined browser job, cancelled | 1,222 |
| Browser pip / npm / Node engine installation | 32 / 5 / 47 |
| Contract export + generation / SPA build / lint / Vitest | 3 / 7 / 6 / 15 |
| Node Playwright step, 160 cases per issue evidence | 705 |
| Runtime image build + inspection | 37 |
| Python engine installation, already warm in combined job | 3 |
| Native step before cancellation, incomplete lower bound | 336 |
| Browser / Python / Windows artifact upload | 7 / 1 / 1 |
| Python / browser PostgreSQL container initialization | 21 / 10 |

These are step costs, not fixture attribution. Pytest now prints the slowest 20
setup/call/teardown phases and retains JUnit (default total testcase time);
Playwright retains per-partition JUnit. Concurrent case time must not be summed
as elapsed time. Installation/build/artifact work is separate from test work.

One hosted attempt is not a reliability distribution. Cancellation provides no
complete native runtime or success evidence; the aggregate correctly failed.
Queue time, cache warmth, runner capacity and attempt/retry history must be
recorded separately. Occupied runner seconds are not billed minutes (platform
multipliers, rounding and plans differ). No retry-based speedup is claimed.

The dominant known cost is serial UI then native work. Those now have independent
budgets; UI is additionally sharded. Repeating the 7-second build in frontend/native
jobs avoids shared-build upload/download/version coupling. Engine installs now
occur on three browser runners rather than sharing one warm installation; extra
checkouts/installations can increase runner cost. Existing pip/npm download caches
remain. Dedicated 20-minute browser/native budgets are provisional, not a claim
of measured complete hosted native duration; diagnose phases before adjusting.

## Before/after evidence and completion boundary

[Sanitized local validation](evidence/ci-376/local-validation.json) records the
contract comparison, disjoint inventory and successful 140 UI / 125 native cases,
including zero skips/failures. The native run passed in 420.34 seconds against
a task-created PostgreSQL 18.6 container; all UI cases passed in 4.5 minutes with
two workers. All 20 reported slowest native phases were test calls (3.95 to
13.24 seconds); no individual setup/teardown phase exceeded 3.95 seconds in
this sample. This bounds each fixture phase, not total fixture cost. These local
durations are not directly comparable to hosted Linux.
The affected tooling suite (171 cases), final focused policy/timing tests (44),
frontend unit tests (92), lint, TypeScript/build and OpenAPI/client drift checks
passed. Existing deprecated-httpx and bundle-size warnings remain informational.

Implementation starts from clean `origin/main` at `d5530d9`. The hosted timeout
candidate contains different security changes; it is diagnostic context, not an
equivalent-revision speed comparison. A controlled Windows 11/Node 24.19.0 sample
used the original five unchanged contract bodies/setup from this main revision
across the four original projects (two CI workers), then the new single-worker
configuration: 20 passed in 3.1 s versus five passed in 1.2 s. This demonstrates
removed repetition on identical inputs; one local sample does not predict hosted
end-to-end performance or reliability. Collection confirms 140 retained UI cases
split 70/70 with no overlap/omission, plus five run-once cases (previously 160
executions). Native collection is 125 including the ten restored cases.

Publication integrates main `ae9d9c5` (guided onboarding, PR #372), including its
native identity/workspace additions. The earlier measurements above remain
identified with their original inputs, not relabeled as validation of onboarding.
Main's 30-minute headroom applied to the old combined browser job; the split
UI/native partitions retain dedicated 20-minute budgets. Final integration
validation and current-candidate hosted results are recorded in the PR.

Hosted after measurements and current-candidate required CI remain pending
publication. Do not mark #376's hosted acceptance complete from local evidence.
Compare equivalent source/test inputs on the same hosted OS/runner class and
attempt, retaining the baseline workflow externally as needed. Disclose the ten
restored native cases. Include failures/cancellations and collect several runs
before claiming improved reliability. Record aggregate elapsed time, occupied
runner time, phase costs, retries, JUnit counts/skips/failures and shard imbalance.
No overall speedup or cost reduction is claimed. Adjust partitions from evidence;
broader visual scheduling requires an explicit coverage/fallback policy.

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
Native commands/prerequisites are in [Browser quality](COMMERCIAL_BROWSER_QUALITY.md#repeatable-local-and-ci-gate).
They use explicitly configured disposable databases, never application credentials.
Normal local validation stays scoped to affected behavior; CI is the full gate.

Download metadata using read-only GitHub CLI access:

```powershell
gh api repos/Roklion/Project_Tabula_Rasa/actions/runs/RUN_ID/jobs?per_page=100 > jobs.json
python scripts/summarize_ci_timings.py --jobs jobs.json --junit native-browser-results.xml
python scripts/summarize_ci_timings.py --jobs docs/evidence/ci-376/baseline-jobs.json
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
