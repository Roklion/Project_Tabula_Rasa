# Project Tabula Rasa

**Project Owner:** Heathcote Advisory LLC

Project Tabula Rasa is a bookkeeping and financial management application designed for individuals and businesses to manage accounts, transactions, expenses, assets, receipts, mileage, and financial reporting.

Bookkeeping runs in the React/FastAPI/PostgreSQL application. Named business access,
shared accounting services, Google Drive receipts, recurring jobs and separate database
and document recovery are documented in the guides below. The Streamlit entry point
now serves local operator administration only.

## Quick start

For browser/API development, follow [Runtime](docs/browser/RUNTIME.md). For a deployed
application, follow [Deployment](docs/operations/DEPLOYMENT.md), [business
access](docs/identity/BUSINESS_TENANCY.md) and [Using Tabula Rasa](docs/USING_TABULA_RASA.md).
New PostgreSQL businesses are created in the application.

For protected local Google consent, grant replacement, folder administration and
format-13 recovery setup, follow [Setup](docs/SETUP.md) and launch:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_local_profile_admin.ps1
```

The administrator requires the application password, explicit local-admin flag,
loopback binding and password reauthentication. It does not initialize a ledger or
generate recurring occurrences on startup. Google self-service connectivity remains
separate from native business creation; [connections](docs/identity/CONNECTIONS_AND_CLAIMS.md)
defines the operator-assisted grant handoff.

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
