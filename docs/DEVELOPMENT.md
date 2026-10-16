# Development

This guide covers local development, validation, smoke testing, and the
human-facing pull-request workflow. Repository-wide agent and review rules
live in [AGENTS.md](../AGENTS.md); Gemini-specific reviewer behavior lives in
[.gemini/styleguide.md](../.gemini/styleguide.md).

## Environment

Use Python 3.12 or newer and install runtime and development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

The Codex-managed Windows environment intentionally requires Python 3.12 so
worktrees use one interpreter series. Its environment setup fails clearly when
that interpreter is unavailable.

The optional PostgreSQL development runtime, migration policy, environment
variables, and real-database test setup are documented in
[PostgreSQL development and operations](POSTGRESQL.md). Development dependencies
include the database tools; the Sheets runtime does not require them or a DB URL.

## Commercial web/API development

[ADR 0002](adr/0002-commercial-web-runtime.md) selects the commercial browser,
HTTP and deployment stack under #276/#221/#124. Follow
[Commercial web development and deployment](COMMERCIAL_WEB.md) for the
`tabula_rasa/http/` and `web/` package contract, Python 3.12/Node 24 tooling,
local Vite -> API -> PostgreSQL topology, OpenAPI/client generation, environment
separation and #279's provider/secret/persistent-staging checkpoint. #277/#278
now supply runnable local foundations; [Foundation conventions](COMMERCIAL_FOUNDATION.md)
covers transport/context contracts, cache/form ownership and focused validation.
The #279 image/workflows/gate are implemented; [Technical deployment](COMMERCIAL_DEPLOYMENT.md)
owns the exact provider/secret checkpoint, ordered migration, smoke and rollback
procedure. #279 records hosted acceptance; [Technical alpha](TECHNICAL_ALPHA.md)
owns #288's staged core workflow matrix, browser release gate, rollback rehearsal,
remaining hosted/manual prerequisites and Streamlit retirement boundary.

[Identity ADR 0003](adr/0003-commercial-identity-and-tenancy.md) and
[Commercial identity](COMMERCIAL_IDENTITY.md) freeze #310's provider, session,
role and tenant-context contract for #311–#321. They are implementation/setup
contracts; named identity and hosted tenant acceptance are not delivered by
that documentation change.

The HTTP runtime reuses application services and PostgreSQL adapters. Preserve
the server-side #222 membership/context seam, #280 loaded-baseline form contract,
and #223 health/request/job seams. Keep ordinary development and tests synthetic;
the current Streamlit/Sheets setup and validation gates continue to apply.

[Existing workflow ports](COMMERCIAL_WORKFLOW_PORTS.md) documents
#357/#358/#362/#364's transaction/mileage imports, ordinary copy/bulk and
mixed-use copy/Expense conversion, their service reuse and scoped validation.

[Secondary workflows](COMMERCIAL_SECONDARY_WORKFLOWS.md) covers #284 recurring/
mixed-use and #285 assets/depreciation. Their native browser/API coverage extends
the existing compiled-app/disposable-PostgreSQL fixture. Generation and posting
are explicit commands; page loads remain read-only and #223 retains durable jobs.

The existing-functionality ports #359/#361/#363 are documented in
[Commercial workflow ports](COMMERCIAL_WORKFLOW_PORTS.md): financial CSVs,
source-owned mixed-use receipts and optional Maps mileage. Native regression
tests exercise the compiled application with disposable PostgreSQL and synthetic
providers; hosted dependency checks remain separate #133/#303 operator evidence.

## Local main-branch push guard

The tracked .githooks/pre-push hook blocks pushes that would update remote
main. Git does not activate tracked hooks automatically. After a clone:

```powershell
git config --local core.hooksPath .githooks
git config --local --get core.hooksPath
```

The second command should print .githooks. The guard applies only to the
configured clone and is not a substitute for server-side branch protection.

## Required validation

Run affected tests and applicable fast lint/type/style checks from the repository
root in the active development environment during implementation, after fixes,
and before committing or publishing. Choose coverage by changed behavior,
callers, shared dependencies and relevant failure paths, rather than test-file
names alone. Add regression coverage when behavior changes. For example, a CI
workflow change affects `tests/tooling`; a service change also needs its callers
and adapter/isolation coverage. Run `git diff --check` and check the branch diff
against `origin/main` before publishing. Resolve affected failures before
committing that round.

Publish after those local checks and begin Codex/Gemini reviews while full-suite
CI runs independently. Continue processing feedback during pending CI. A review
fix gets affected local checks and a fresh CI run for the new revision. Full
local runs are exceptional diagnostics for CI failures, global fixtures/test
infrastructure or especially broad changes that affected checks cannot cover;
they are not mandatory before PR creation or at review completion.

### Authoritative CI and required check

[Repository CI](../.github/workflows/ci.yml) consolidates the former PostgreSQL
and commercial-foundation workflows. Its stable merge-gate check name is
**`Full test suite`**. It requires success from all required partitions (six runner jobs):

- **Python suite (Linux + PostgreSQL)** installs `requirements-dev.txt` with
  Python 3.12, runs `ruff check .` and `python -m pytest -ra` over every test
  discovered by `pytest.ini`, and supplies disposable PostgreSQL 18.6 through
  `TABULA_RASA_TEST_DATABASE_URL`. Missing/inaccessible PostgreSQL must not be
  used to make this gate green. There are no marker filters or deselections.
- **Windows environment setup** runs the Windows-only
  `tests/tooling/test_codex_environment_setup.py` on Windows with PowerShell and
  Python 3.12. Those tests' existing platform skips on Linux are covered here,
  including the real Python 3.12 setup harness. The remaining suite runs once
  on Linux; no second full Python run is added on Windows.
- **Frontend, contracts and runtime image** owns Node 24/npm OpenAPI/client
  generation and drift checking, TypeScript/build, ESLint, Vitest, browser-independent
  HTTP/Git preview contracts and the commercial Docker image build/import inspection.
  The preview contracts run once without installing or launching browser engines.
- **Browser UI (shard 1/2 and 2/2)** partitions all Playwright UI/accessibility
  cases with Playwright's fully-parallel test sharding, two workers per runner and
  all four existing browser/device projects. Both shards are required; fail-fast
  is disabled to retain diagnostics from both. No browser/viewport or assertion
  is removed. Each shard uploads a uniquely named JUnit/trace/screenshot artifact.
- **Native browser (HTTP + PostgreSQL)** independently builds the SPA and runs
  every `tests/postgres/test*browser*.py` module against its own disposable
  PostgreSQL service with all three engines and required-browser mode. The CI
  policy test verifies the explicit file inventory so a newly added module cannot
  be silently omitted. The complete Python suite still discovers every test;
  native scenarios skip there because that isolated checkout has no SPA build.
  Native tests execute in this required job rather than twice. Python lint and
  non-browser integration contracts remain owned by the Python job.

The explicitly invoked Streamlit viewport scripts below remain optional developer
checks; supported legacy unit/integration coverage remains required in Python CI.
See [CI execution evidence and suite selection](CI_TEST_SUITES.md) for the cost
baseline, coverage rationale, bounded budgets, focused commands and comparison
procedure. No path-based or scheduled-only selection is introduced.

The suite needs no production credentials, Google OAuth grants or live ledgers.
It uses read-only repository permissions, pip/npm dependency caches, bounded job
timeouts and PR-scoped cancellation of superseded runs. Python jobs print
failure/skip details and retain JUnit results as Actions artifacts. A failing,
cancelled, skipped or missing component cannot make the aggregate check pass.

PRs targeting `main` run on `opened`, `synchronize`, `reopened` and
`ready_for_review`, including drafts. Feature-branch pushes do not launch a
second push workflow. Ready/reopened events intentionally refresh the candidate;
concurrency cancels unfinished superseded runs for the same PR. Pushes to `main`
also run CI after merges. `merge_group: checks_requested` supports a future
merge queue. Checkout uses GitHub's current PR merge candidate (the default
`pull_request` checkout), or the merge-group SHA. Match the run to the current
PR head and candidate; a previous head's green result cannot establish readiness.

#### Optional GitHub enforcement (good to have)

The maintainer has chosen to retain the current GitHub plan. A plan upgrade,
GitHub-enforced branch protection/rulesets and their associated protections,
configuration readback, and a probe proving that GitHub blocks a failing merge
are optional future improvements. They do not block closing issue #295.
Current-revision CI success and satisfied review conditions remain required by
repository/agent policy; enforcement is procedural while GitHub's hard block
is unavailable. Do not describe optional enforcement as configured or verified.

Repository files cannot enable GitHub's required-check enforcement. If the
maintainer elects to enable it later, an administrator can use this optional setup:

1. Ensure the private repository's plan supports branch protection/rulesets.
   On 2026-10-07, read-only queries of both `main` protection and rulesets
   returned HTTP 403 with GitHub's "Upgrade to GitHub Pro or make this repository
   public" response. Enforcement remains **unverified and unavailable on that
   plan**; do not describe this implementation as enforced protection. Keep the
   repository private. Arrange an eligible plan only if the owner elects to
   pursue this optional improvement.
2. In **Settings > Branches > Add branch protection rule**, target exactly
   `main`. Enable **Require a pull request before merging**, **Require status
   checks to pass before merging**, and **Require branches to be up to date
   before merging**. Add **`Full test suite`**, selecting **GitHub Actions** as
   the expected source, and prevent admin/role bypass of the rule. Preserve any
   existing required reviews/checks and other protections. A ruleset equivalent
   must be active, target `main`, require the same check/source and strict update
   policy, and have no bypass that defeats the gate. Replace obsolete
   `integration`/`foundation` checks only after the aggregate check is available.
3. Read the saved protection/ruleset back. For classic protection, use
   `gh api repos/Roklion/Project_Tabula_Rasa/branches/main/protection` and confirm
   `required_status_checks.strict` is true and the required check context is
   `Full test suite` with the GitHub Actions app identity. For a ruleset, use
   `gh api repos/Roklion/Project_Tabula_Rasa/rulesets`, inspect the active rule's
   detail and confirm its `main` target, status-check source, strict policy and
   bypass list. Do not treat HTTP 403 or absent checks as verification.
4. On a controlled synthetic PR, confirm CI and advisory review start without a
   full local run; handle feedback while CI is pending. Commit a deliberately
   failing test and verify the current candidate's gate fails and merging is
   blocked. Fix it with affected tests and a new commit; verify the older green
   result is insufficient while the new run is pending, and completion becomes
   eligible only after that run passes and review conditions are satisfied.
   Do not merge the probe or use production data. The server-enforcement probe
   is optional, requires separate authorization and does not block issue #295
   closure. Normal hosted CI/review behavior verification remains required.

### CI failures and review completion

Open the PR's **Checks > Full test suite > Details** or **Actions > Repository
CI**. Inspect the failed component's named step and download its JUnit artifact
when present. CLI equivalents are `gh pr checks <PR>`,
`gh run view <RUN_ID> --log-failed` and `gh run download <RUN_ID>`.
Reproduce the affected failure locally and fix it with scoped checks; a new
commit triggers fresh CI. Rerun only a diagnosed transient failure with
`gh run rerun <RUN_ID> --failed` (or Actions' **Re-run failed jobs**), on the
current candidate. If the aggregate job ran during the failure, ensure it is
also rerun after its dependencies succeed; use **Re-run all jobs** once if the
failed-jobs rerun does not recompute the aggregate. Do not loop on an unchanged
code failure or use reruns as evidence for a newer head.

Monitor CI and reviewer states independently. Review may finish before CI or
vice versa. Pending CI continues monitoring; failed/timed-out/cancelled/missing
CI is an actionable incomplete or blocked state, never success. Report the
current head, run/check name and failing job/logs, distinguishing code defects
from infrastructure or account limitations. Missing checks require inspecting
event/base-branch routing, Actions permissions/approval and required-check setup;
do not weaken the gate. Successful review-loop completion and merge readiness
require satisfied review conditions, current-revision required checks passing
and a conflict-free/current candidate. Human approval and merge authority remain
unchanged.

Tests use fake or in-memory services and must not read live ledger data,
application credentials, service-account keys, or OAuth tokens.

## Browser smoke test

The checked-in .smoke_local fixture runs the real Streamlit entry point with a
fake profile, fake credentials, and fake workbook. It is an explicitly
invoked developer check rather than a CI gate:

```powershell
python scripts\smoke_transactions.py
```

The journal browser check uses the same synthetic fixture and four viewports.
It checks unsaved entry-mode switching, explicit line controls, and grouped
ledger header behavior:

```powershell
python scripts\smoke_journals.py
```

It signs in and checks the Transactions > Add transaction renderer at
1440x1000, 1200x900, 900x900, and 390x844, including the optional receipt
control and page-level horizontal overflow. The requested loopback port must
be unused. Optional diagnostic screenshots can be retained with:

```powershell
python scripts\smoke_transactions.py --screenshots-dir .smoke_local\artifacts
```

Install its dependencies and managed Chromium once:

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

The fixture's credential-shaped values and password are synthetic,
test-only, intentionally public, and must never be replaced with real values
or reused for deployment access. See [.smoke_local/README.md](../.smoke_local/README.md).

## Live read-only validation

After the automated suite passes, validate the configured Google deployment
without changing ledger data:

```powershell
python scripts\validate_app_google.py
```

This checks both split local secrets plus business_profiles.json and the
combined hosted Secrets projection. Validate one workbook, its required headers,
and its managed Payees records with:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY
```

Add --write-test only for an intentional reversible permission check. It
creates, reads, updates, and deletes a disposable worksheet, not ledger rows:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --write-test
```

## Test architecture

Tests are organized by responsibility rather than by a permanent inventory of
every module:

- normal pytest unit and integration tests cover domain logic, storage,
  authentication, imports, recovery, and page behavior;
- executable Streamlit AppTest scenarios cover end-to-end UI workflows;
- tests/app_support.py provides shared AppTest authentication, profile and
  storage bootstrap, semantic UI interactions, and lookup/navigation helpers;
- tests/conftest.py provides reusable pytest fixtures for shared concepts;
- tests/drive_fixtures.py provides reusable semantic Google Drive builders;
- tests/_app_*_scenario.py contains executable scenario layers used by the UI
  tests;
- tests/tooling/ contains repository-policy, environment-bootstrap, and Git-hook
  checks; these remain part of the full suite and can be run with
  `python -m pytest tests/tooling`;
- Drive, receipt, backup, storage, and profile tests exercise their respective
  failure, retry, and isolation boundaries; and
- scripts/smoke_transactions.py provides the browser-level viewport check.

Do not duplicate shared scenario setup in individual test documentation.
Behavior-sensitive changes need success and relevant failure coverage, and
profile-sensitive changes need a two-profile isolation check.

`tests/test_application_boundaries.py` enforces the service boundary: ordinary
page contexts require services, and UI/application modules cannot import the
Sheets facade or infrastructure adapters. Provider-specific exceptions and
remaining migration boundaries are listed in [Architecture](ARCHITECTURE.md).
Add a new service/repository capability for bookkeeping behavior rather than
passing workbook administration into a normal page.

## Pull requests and review

Codex-authored PRs should use the PR body template in the
`gh-publish-review-loop` skill. Contributors without that skill should include
the same information directly: intent, expected success and failure behavior,
invariants that must not change, validation evidence, and known limitations.
Concise statements are sufficient. The description is review context, not
proof of correctness. Check the implementation against the current code,
tests, canonical documentation, callers, storage paths, retries, and state
transitions.

Codex is the primary repository/remediation reviewer and Gemini is an
independent complementary advisory reviewer. The human maintainer retains
requirements, approval, and merge authority. Follow AGENTS.md for
repository-wide rules and .gemini/styleguide.md for Gemini's specialized
adversarial review focus.

## Documentation maintenance

The root README is the documentation index. Keep one canonical home for each
durable fact and link to it rather than copying the full content elsewhere.
Update the relevant guide when externally visible behavior, configuration,
recovery procedures, or security boundaries change. Keep Mermaid source in
Markdown, use repository-relative links, and never commit credentials, tokens,
private ledger data, receipts, backups, or validation output.

## Commercial browser quality

The [bounded technical-alpha browser gate](COMMERCIAL_BROWSER_QUALITY.md) adds
axe scans, desktop/mobile journeys and keyboard/failure checks to the existing
Playwright baseline. Repository CI runs it in the required native-browser job after
compiling the SPA; the guide owns local setup and outstanding release evidence.
