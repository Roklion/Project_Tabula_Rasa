# Project Tabula Rasa

Project Tabula Rasa is a private, Google Sheets-backed bookkeeping application for one
person or a small group of businesses. Each business profile has an isolated
ledger workbook and Google credential set while sharing one Streamlit
deployment.

The application supports:

- accounts, categories, profile-local Tags, transactions, transfers, and mileage;
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
| Implement the selected commercial browser/API/runtime stack | [Commercial web ADR](docs/adr/0002-commercial-web-runtime.md) |
| Follow commercial package, local topology and deployment conventions | [Commercial development and deployment](docs/COMMERCIAL_WEB.md) |
| Implement the commercial PostgreSQL accounting model | [Canonical schema ADR](docs/adr/0001-canonical-accounting-schema.md) |
| Start PostgreSQL, run migrations, and test database infrastructure | [PostgreSQL development and operations](docs/POSTGRESQL.md) |
| Implement PostgreSQL mutations and carry loaded-record baselines | [PostgreSQL concurrency convention](docs/POSTGRESQL_CONCURRENCY.md) |
| Dry-run and rehearse a final-format Sheets migration | [Sheets to PostgreSQL migration](docs/SHEETS_POSTGRES_MIGRATION.md) |
| Accept a whole migrated profile and control backend cutover | [Bookkeeping acceptance and cutover](docs/BOOKKEEPING_CUTOVER.md) |
| Export complete PostgreSQL bookkeeping privately | [Complete entity export](docs/BOOKKEEPING_EXPORT.md) |
| Define managed backup/PITR protection and verify recovery rehearsals | [PostgreSQL recovery](docs/POSTGRESQL_RECOVERY.md) |
| Configure the application and business profiles | [Setup](docs/SETUP.md) |
| Configure Drive, Picker, receipts, and cloud backups | [Google Drive](docs/GOOGLE_DRIVE.md) |
| Configure Maps autocomplete, routing, quotas, and billing | [Google Maps mileage](docs/GOOGLE_MAPS.md) |
| Review application legal terms and privacy practices | [Terms of Use](docs/TERMS_OF_USE.md) · [Privacy Policy](docs/PRIVACY_POLICY.md) |
| Use ledgers, receipts, mileage, reports, and imports | [Using Tabula Rasa](docs/USING_TABULA_RASA.md) |
| Inspect the frozen final Sheets workbook/archive source | [Final Sheets source contract](docs/SHEETS_SOURCE_CONTRACT.md) |
| Back up, validate, restore, and recover receipts | [Backup and recovery](docs/BACKUP_RECOVERY.md) |
| Run development checks and tests | [Development](docs/DEVELOPMENT.md) |

## Repository layout

- `tabula_rasa/` contains the Streamlit entry point and application modules.
- `scripts/` contains setup, validation, backup, and recovery utilities.
- `tests/` contains the automated test suite and UI workflow scenarios.
- `docs/` contains the canonical architecture, setup, Google integration, user,
  recovery, and development guides.

## Security

Never commit `.streamlit/secrets.toml`,
`.streamlit/business_profiles.json`, OAuth client secrets, OAuth refresh
tokens, exported Streamlit Secrets, backups, receipts, or private ledger data.
The ignored local profile file is plaintext and must remain on a protected,
non-synchronized filesystem.

The application password currently grants access to every configured business
profile. Use separate deployments or implement profile-level authorization when
different users must be restricted to different businesses.

## Development checks

Install the development dependencies, then run affected tests and applicable
fast lint/type/style checks for the behavior and shared dependencies you change.
Full local suites are exceptional diagnostics; the current revision's GitHub
Actions **Full test suite** check is the authoritative merge gate and runs
concurrently with PR review.

See the [development guide](docs/DEVELOPMENT.md#required-validation) for local
validation, CI coverage, required-check administration, failure diagnosis and
test isolation.

## Authors

- Roklion
