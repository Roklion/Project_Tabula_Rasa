# Documentation

This directory is the canonical source for Project Tabula Rasa's technical and
operational documentation. The root README remains intentionally short and
points here for durable setup, architecture, and recovery guidance.

## Choose a guide

### Understand the system

- [Architecture overview](architecture/OVERVIEW.md) explains the application,
  storage, identity, and recovery boundaries.
- [Google Drive OAuth and per-business access](architecture/GOOGLE_DRIVE_OAUTH.md)
  explains the shared OAuth client, per-profile grants and tokens, Google
  Picker, and receipt or backup data flows.

### Configure the application

- [Business profile setup](setup/BUSINESS_PROFILES.md) covers Google Sheets,
  service accounts, local profile administration, hosted Secrets export, and
  validation.

### Operate and recover

- [Backup and recovery](operations/BACKUP_AND_RECOVERY.md) covers local and
  cloud backups, scheduling, verification, retention, and blank-workbook
  restoration.
- [Synology recovery](operations/SYNOLOGY_RECOVERY.md) is the optional DS220j
  Cloud Sync runbook.

### Use and develop

- [Using Project Tabula Rasa](guides/USING_TABULA_ROSA.md) covers profile selection,
  ledger behavior, receipts, mileage, reports, and exports.
- [QuickBooks import](guides/QUICKBOOKS_IMPORT.md) covers transaction and
  mileage import formats, validation, and duplicate handling.
- [Development](development/DEVELOPMENT.md) covers dependencies, required
  checks, test isolation, and read-only live validation.
- [Pull-request review](development/PULL_REQUEST_REVIEW.md) defines reviewer
  roles, Gemini command modes, finding disposition, and validation.
- [Transactions surface inventory](development/TRANSACTIONS_SURFACE_INVENTORY.md)
  records the controls, state, feedback, and failure paths preserved by issue
  #54 for later transaction work.
- [Transactions extraction and redesign audit](development/TRANSACTIONS_CHANGE_AUDIT.md)
  separates mechanical movement, presentation changes, review remediations,
  and end-to-end AppTest evidence for issue #54.

## Documentation map

```text
docs/
|-- README.md
|-- architecture/
|   |-- OVERVIEW.md
|   `-- GOOGLE_DRIVE_OAUTH.md
|-- setup/
|   `-- BUSINESS_PROFILES.md
|-- operations/
|   |-- BACKUP_AND_RECOVERY.md
|   `-- SYNOLOGY_RECOVERY.md
|-- guides/
|   |-- QUICKBOOKS_IMPORT.md
|   `-- USING_TABULA_ROSA.md
`-- development/
    |-- DEVELOPMENT.md
    |-- PULL_REQUEST_REVIEW.md
    |-- TRANSACTIONS_CHANGE_AUDIT.md
    `-- TRANSACTIONS_SURFACE_INVENTORY.md
```

## Maintenance rules

- Keep one canonical home for each topic and link to it instead of copying it.
- Update documentation in the same change as the behavior it describes.
- Keep Mermaid source in Markdown so diagrams remain diffable and reproducible.
- Use repository-relative links for project files and documentation.
- Use placeholders for credentials, account addresses, spreadsheet IDs, folder
  IDs, and private paths.
- Never store private validation output, ledger data, OAuth tokens, or recovery
  workbook identifiers in Git.
