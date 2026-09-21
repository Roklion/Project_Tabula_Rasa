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

Run these commands from the repository root before initially publishing a
coding branch or creating/marking its pull request Ready for Review, and run
them again before declaring the completed review loop fully terminal:

```powershell
ruff check .
python -m pytest
git diff --check
```

For implementation commits and review-remediation rounds between those two
gates, run `git diff --check` plus linting and tests scoped to the affected
files and behavior. Intermediate commits do not require a full-suite rerun when
their affected checks pass.

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

## Pull requests and review

Complete [.github/pull_request_template.md](../.github/pull_request_template.md)
with concise statements of intent, expected success and failure behavior,
invariants that must not change, validation evidence, and known limitations.
The description is review context, not proof of correctness. Check the
implementation against the current code, tests, canonical documentation,
callers, storage paths, retries, and state transitions.

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
