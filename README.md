# Tabula Rosa

Tabula Rosa is a private, Google Sheets-backed bookkeeping application for one
person or a small group of businesses. Each business profile has an isolated
ledger workbook and Google credential set while sharing one Streamlit
deployment.

The application supports:

- accounts, categories, transactions, transfers, and mileage;
- balance-sheet, income-and-expense, and account reporting;
- receipt storage in a business-specific Google Drive folder;
- validated, versioned local and Google Drive backups;
- optional Synology recovery copies; and
- QuickBooks Online transaction and mileage imports.

## Quick start

1. Install Python 3.12 or newer.
2. Create the virtual environment and install the application dependencies:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Create the ignored local secrets file and set the application password:

   ```powershell
   New-Item -ItemType Directory -Force .streamlit | Out-Null
   New-Item -ItemType File -Force .streamlit\secrets.toml | Out-Null
   python scripts\set_app_password.py
   ```

   The script stores only a password hash. Application-wide secrets live in
   `.streamlit/secrets.toml`; business settings and per-profile credentials
   live in `.streamlit/business_profiles.json`.

4. Follow [Business profile setup](docs/setup/BUSINESS_PROFILES.md) to create
   the first Google Sheets-backed profile.
5. If receipts or cloud backups are needed, complete
   [Google Drive OAuth and per-business access](docs/architecture/GOOGLE_DRIVE_OAUTH.md).
6. Start the application:

   ```powershell
   streamlit run tabula_rasa/app.py
   ```

The active datastore is Google Sheets. The application does not use a local
SQLite database for ledger storage.

## Documentation

Start with the [documentation index](docs/README.md), or go directly to:

| Goal | Guide |
| --- | --- |
| Understand the system and data boundaries | [Architecture overview](docs/architecture/OVERVIEW.md) |
| Add or replace a business | [Business profile setup](docs/setup/BUSINESS_PROFILES.md) |
| Configure Drive, Picker, receipts, and cloud backups | [Google Drive OAuth](docs/architecture/GOOGLE_DRIVE_OAUTH.md) |
| Use ledgers, receipts, mileage, and reports | [Using Tabula Rosa](docs/guides/USING_TABULA_ROSA.md) |
| Back up, validate, and restore ledger data | [Backup and recovery](docs/operations/BACKUP_AND_RECOVERY.md) |
| Maintain a Synology recovery copy | [Synology recovery](docs/operations/SYNOLOGY_RECOVERY.md) |
| Import QuickBooks data | [QuickBooks import](docs/guides/QUICKBOOKS_IMPORT.md) |
| Run development checks and tests | [Development guide](docs/development/DEVELOPMENT.md) |

## Repository layout

- `tabula_rasa/` contains the Streamlit entry point and application modules.
- `scripts/` contains setup, validation, backup, and recovery utilities.
- `tests/` contains the automated test suite and UI workflow scenarios.
- `docs/` contains architecture, setup, operational, user, and development
  documentation.

## Security

Never commit `.streamlit/secrets.toml`,
`.streamlit/business_profiles.json`, service-account JSON, OAuth refresh
tokens, exported Streamlit Secrets, backups, receipts, or private ledger data.
The ignored local profile file is plaintext and must remain on a protected,
non-synchronized filesystem.

The application password currently grants access to every configured business
profile. Use separate deployments or implement profile-level authorization when
different users must be restricted to different businesses.

## Development checks

Install the development dependencies and run the required checks:

```powershell
pip install -r requirements-dev.txt
ruff check .
python -m pytest
```

See the [development guide](docs/development/DEVELOPMENT.md) for test isolation
and live validation commands.

## Authors

- Roklion [yaodongy1018@gmail.com]
