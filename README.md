# Project Tabula Rasa

Project Tabula Rasa is a private, Google Sheets-backed bookkeeping application for one
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

4. Follow [Setup](docs/SETUP.md) to create
   the first Google Sheets-backed profile.
5. If receipts or cloud backups are needed, complete
   [Google Drive setup](docs/GOOGLE_DRIVE.md).
6. Start the application:

   ```powershell
   streamlit run tabula_rasa/app.py
   ```

The active datastore is Google Sheets. The application does not use a local
SQLite database for ledger storage.

## Documentation

The documentation index is this section of the root README. Go directly to:

| Goal | Guide |
| --- | --- |
| Understand the system and data boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Configure the application and business profiles | [Setup](docs/SETUP.md) |
| Configure Drive, Picker, receipts, and cloud backups | [Google Drive](docs/GOOGLE_DRIVE.md) |
| Use ledgers, receipts, mileage, reports, and imports | [Using Tabula Rasa](docs/USING_TABULA_RASA.md) |
| Back up, validate, restore, and recover receipts | [Backup and recovery](docs/BACKUP_RECOVERY.md) |
| Run development checks and tests | [Development](docs/DEVELOPMENT.md) |

## Repository layout

- `tabula_rasa/` contains the Streamlit entry point and application modules.
- `scripts/` contains setup, validation, backup, and recovery utilities.
- `tests/` contains the automated test suite and UI workflow scenarios.
- `docs/` contains the six canonical architecture, setup, Drive, user,
  recovery, and development guides.

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

See the [development guide](docs/DEVELOPMENT.md) for test isolation
and live validation commands.

## Authors

- Roklion
