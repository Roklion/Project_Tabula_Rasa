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
cutover gates; see [Commercial development](docs/COMMERCIAL_WEB.md) and
[Bookkeeping cutover](docs/BOOKKEEPING_CUTOVER.md). Neither edition uses a local
SQLite database as an alternate live ledger.

## Documentation

The documentation index is this section of the root README. Go directly to:

| Goal | Guide |
| --- | --- |
| Understand the system and data boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Implement the selected commercial browser/API/runtime stack | [Commercial web ADR](docs/adr/0002-commercial-web-runtime.md) |
| Select identity, sessions, roles and tenant authorization | [Commercial identity ADR](docs/adr/0003-commercial-identity-and-tenancy.md) |
| Prepare identity-provider setup and #311–#321 security handoff | [Commercial identity](docs/COMMERCIAL_IDENTITY.md) |
| Prepare named-user staging promotion, rehearsal and operator handoff | [Authenticated hosted rollout](docs/AUTHENTICATED_ROLLOUT.md) |
| Run tenant/identity security acceptance and inspect release gaps | [Security acceptance](docs/SECURITY_ACCEPTANCE.md) |
| Switch workspaces, manage invitations/members and bootstrap a ledger | [Workspace lifecycle](docs/WORKSPACE_LIFECYCLE.md) |
| Connect tenant-owned Google grants and claim existing entities | [Connections and existing entity claims](docs/EXTERNAL_CONNECTIONS_AND_LEGACY_CLAIMS.md) |
| Follow commercial package, local topology and deployment conventions | [Commercial development and deployment](docs/COMMERCIAL_WEB.md) |
| Use and validate browser mileage and transaction receipts | [Commercial mileage and receipts](docs/COMMERCIAL_MILEAGE_RECEIPTS.md) |
| Use recurring, mixed-use, assets and depreciation in the browser | [Commercial secondary workflows](docs/COMMERCIAL_SECONDARY_WORKFLOWS.md) |
| Use or validate commercial entity setup, entries, ledger and reports | [Commercial core workflows](docs/COMMERCIAL_WORKFLOWS.md) |
| Configure technical Render/Neon environments and deploy a tested image | [Technical deployment and operator checkpoint](docs/COMMERCIAL_DEPLOYMENT.md) |
| Configure tenant-safe diagnostics, alerts and operational triage | [Operational observability](docs/OBSERVABILITY.md) |
| Respond to incidents, roll back compatible images and rotate secrets | [Incident response](docs/INCIDENT_RESPONSE.md), [secret operations](docs/SECRETS_OPERATIONS.md) and [staging drill](docs/INCIDENT_DRILL.md) |
| Review commercial visual, responsive and accessibility evidence | [Integrated UI acceptance](docs/COMMERCIAL_UI_ACCEPTANCE.md) |
| Verify technical alpha and track the Streamlit transition | [Alpha release gate and retirement boundary](docs/TECHNICAL_ALPHA.md) |
| Review retained capabilities, cleanup evidence and retirement conditions | [Issue #377: transition retirement inventory](https://github.com/Roklion/Project_Tabula_Rasa/issues/377) |
| Implement the commercial PostgreSQL accounting model | [Canonical schema ADR](docs/adr/0001-canonical-accounting-schema.md) |
| Start PostgreSQL, run migrations, and test database infrastructure | [PostgreSQL development and operations](docs/POSTGRESQL.md) |
| Implement PostgreSQL mutations and carry loaded-record baselines | [PostgreSQL concurrency convention](docs/POSTGRESQL_CONCURRENCY.md) |
| Run durable jobs and inspect atomic audit-history contracts | [Jobs and bookkeeping history](docs/OPERATIONS_JOBS_AUDIT.md) |
| Apply the approved interim audit retention/access contract and track legal decisions | [Audit policy](docs/AUDIT_POLICY.md) |
| Adopt monthly accounting locks and linked reversing journals | [Accounting periods and corrections](docs/ACCOUNTING_PERIODS.md) |
| Dry-run and rehearse a final-format Sheets migration | [Sheets to PostgreSQL migration](docs/SHEETS_POSTGRES_MIGRATION.md) |
| Accept a whole migrated profile and control backend cutover | [Bookkeeping acceptance and cutover](docs/BOOKKEEPING_CUTOVER.md) |
| Export complete PostgreSQL bookkeeping privately | [Complete entity export](docs/BOOKKEEPING_EXPORT.md) |
| Define managed backup/PITR protection and verify recovery rehearsals | [PostgreSQL recovery](docs/POSTGRESQL_RECOVERY.md) |
| Verify retained audit history, schema protections and activation gaps after restore | [Audit recovery](docs/AUDIT_RECOVERY.md) |
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

## Ownership and License

**Project Owner:** Heathcote Advisory LLC

**Copyright © 2026 Heathcote Advisory LLC. All rights reserved.**

The source code of Project Tabula Rasa is publicly available for inspection and reference purposes.

No license is granted to copy, modify, distribute, sublicense, or commercially exploit this software without prior written permission from Heathcote Advisory LLC, except as permitted by applicable law or GitHub's Terms of Service.

For licensing or commercial-use inquiries, contact the project owner.
