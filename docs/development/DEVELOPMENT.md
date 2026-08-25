# Development

## Environment

Install Python 3.12 or newer, create a virtual environment, and install both
runtime and development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Local main-branch push guard

The tracked `.githooks/pre-push` hook blocks pushes that would update the
remote `main` branch. Push changes to a feature branch and merge them through a
pull request instead.

Git does not activate tracked hooks automatically. After every new clone, run
this command from the repository root:

```powershell
git config --local core.hooksPath .githooks
```

Confirm the clone is configured:

```powershell
git config --local --get core.hooksPath
```

The command should print `.githooks`. The guard applies only to the configured
local clone, can be bypassed intentionally with `git push --no-verify`, and is
not a substitute for server-side branch protection. GitHub pull-request merges
are unaffected.

## Required completion checks

Run both commands from the repository root before treating a coding change as
complete or ready to commit:

```powershell
ruff check .
python -m pytest
```

The automated UI tests use an in-memory Google workbook and a test-only
password hash. They do not read the live ledger, application password, Google
service-account credential, or OAuth token.

## Opt-in browser smoke check

The reusable `.smoke_local` fixture starts the real Streamlit entrypoint with a
deterministic fake profile, fake credentials, and in-memory workbook. Run the
Transactions viewport smoke check explicitly from the repository root:

```powershell
python scripts\smoke_transactions.py
```

It uses Playwright-managed Chromium to sign in and inspect the Transactions >
Add transaction renderer at 1440x1000, 1200x900, 900x900, and 390x844. The
check asserts the key controls, including `Receipt (optional)`, and compares
the document scroll width with the viewport to catch unintended page-level
horizontal overflow. It is a developer smoke check rather than a CI gate; it
does not create a transaction or duplicate receipt-recovery coverage. To keep
failure screenshots for diagnosis, pass `--screenshots-dir`.

Install the browser binary once after installing `requirements-dev.txt`:

```powershell
python -m playwright install chromium
```

## Pull requests and code review

A change does not need a formal issue, but its pull request must provide enough
independent context to review the implementation. Complete the repository pull
request template with:

- **Intent:** the user-visible or operational change;
- **Expected behavior:** the important success and failure cases;
- **Must not change:** existing behavior, data boundaries, or interfaces that
  remain invariant; and
- **Evidence:** automated tests, manual checks, and known limitations.

For a small change, one sentence per section is enough. The author should
personally verify at least the intent and the behavior that must not change,
even when a coding agent drafts the description. This prevents the
implementation from becoming its own specification.

Repository-specific review guidance lives under `# Code Review Rules` in the
root `AGENTS.md`. The reviewer first checks the PR description for sufficient
context. If necessary information is missing, unclear, or inconsistent, the
reviewer requests a specific description update instead of silently assuming
the implementation is intended. The reviewer then checks the description
against the documentation, unchanged callers, existing tests, and surrounding
code. The [pull-request review guide](PULL_REQUEST_REVIEW.md) defines the shared
baseline, separate Codex, Gemini, and maintainer roles, Gemini review commands,
finding disposition, and controlled validation procedure.

## Live read-only validation

After the automated suite passes, the configured Google deployment can be
checked without changing ledger data:

```powershell
python scripts\validate_app_google.py
```

This runs read-only end-to-end dashboard checks in both supported secrets
modes:

- split local app secrets plus `.streamlit/business_profiles.json`; and
- the combined hosted Streamlit Secrets representation.

The combined representation is intentionally a hosted-runtime projection, not
a whole-profile copy. Export tests must keep Sheets and hosted Drive fields while
excluding local filesystem and Synology operational metadata. Adding a new
local-only profile field must not change the generated hosted profile table.

Validate one configured workbook and its required headers with:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY
```

Add `--write-test` only when a reversible Google permission test is intended:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --write-test
```

The permission test creates, reads, updates, and deletes a disposable worksheet.
It does not modify ledger rows.

## Test layout

- `tests/test_app_*.py` covers authentication, storage-failure behavior, and
  application workflows.
- `tests/test_google_sheets_storage.py` covers Sheets persistence, backup
  validation, migration, and restore behavior.
- `tests/test_google_drive.py` covers OAuth, tokens, receipt operations, cloud
  backups, and retention.
- `tests/test_local_profile_*.py` covers loopback-only administration and
  credential persistence.
- `tests/test_backup_scripts.py` covers the backup command-line workflows.
- `tests/test_receipt_backfill.py` covers backup-time receipt preparation,
  idempotency, and profile isolation.
- `tests/test_receipt_recovery.py` covers Synology byte verification, Drive
  conflicts, retry/idempotency, and reference remapping.
- `tests/test_quickbooks_*.py` covers supported import formats.
- `tests/_app_*_scenario.py` contains executable UI test scenarios.

## Documentation changes

The [documentation index](../README.md) is the navigation source of truth.
Keep each topic in one canonical guide, use relative links, and retain Mermaid
source directly in Markdown. When behavior changes, update its guide in the
same change and re-run the required completion checks.
