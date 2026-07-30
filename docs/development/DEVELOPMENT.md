# Development

## Environment

Install Python 3.11 or newer, create a virtual environment, and install both
runtime and development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

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
- `tests/test_quickbooks_*.py` covers supported import formats.
- `tests/_app_*_scenario.py` contains executable UI test scenarios.

## Documentation changes

The [documentation index](../README.md) is the navigation source of truth.
Keep each topic in one canonical guide, use relative links, and retain Mermaid
source directly in Markdown. When behavior changes, update its guide in the
same change and re-run the required completion checks.
