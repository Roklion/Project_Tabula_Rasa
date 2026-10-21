# Project Tabula Rasa

**Project Owner:** Heathcote Advisory LLC

Project Tabula Rasa is a bookkeeping and financial management application designed for individuals and businesses to manage accounts, transactions, expenses, assets, receipts, mileage, and financial reporting.

The project is transitioning from its original Streamlit and Google Sheets architecture to a modern React frontend, FastAPI backend, and PostgreSQL database, with support for multi-tenant data isolation, authenticated access, and scalable deployment.

The new architecture is under active development, while the legacy Streamlit application remains available during the transition.

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

This quick start runs the supported internal Streamlit/Google Sheets edition.
The browser/API edition uses PostgreSQL after its applicable deployment and
cutover gates; see [Commercial development](docs/browser/RUNTIME.md) and
[Bookkeeping cutover](docs/accounting/CUTOVER.md). Neither edition uses a local
SQLite database as an alternate live ledger.

## Documentation

Start with the [documentation index](docs/README.md), organized by application
and technical component:

- [Application use and internal setup](docs/README.md#application-use-and-internal-setup).
- [Browser application and HTTP API](docs/README.md#browser-application-and-http-api).
- [Identity and authorization](docs/README.md#identity-and-authorization).
- [Accounting and database](docs/README.md#accounting-and-database).
- [Document storage](docs/README.md#document-storage).
- [Deployment and operations](docs/README.md#deployment-and-operations).
- [Development and architecture decisions](docs/README.md#development-and-architecture-decisions).

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

## Ownership and License

**Project Owner:** Heathcote Advisory LLC

**Copyright © 2026 Heathcote Advisory LLC. All rights reserved.**

The source code of Project Tabula Rasa is publicly available for inspection and reference purposes.

No license is granted to copy, modify, distribute, sublicense, or commercially exploit this software without prior written permission from Heathcote Advisory LLC, except as permitted by applicable law or GitHub's Terms of Service.

For licensing or commercial-use inquiries, contact the project owner.
