# Google Sheets + Streamlit Deployment Checklist

Target architecture: a private Streamlit Community Cloud app using a private Google Sheets workbook as its live datastore, with optional backups synchronized to the Synology DS220j.

Expected required service cost: $0/month under normal personal usage.

## 1. Prepare the project

- [x] Put the project in a private GitHub repository.
- [x] Confirm that no ledger data, passwords, or credentials are committed.
- [x] Add `.streamlit/secrets.toml`, service-account JSON files, `.env`, CSV exports, and `ledger.db` to `.gitignore`.
- [x] Keep the existing SQLite version and database backup until migration is verified.
- [x] Pin dependency versions in `requirements.txt`.

## 2. Create the Google workbook

- [x] Create a private Google Sheets workbook named `tabula_rosa_data_raw`.
- [x] Create an `Accounts` worksheet with columns: `id`, `name`, `type`, `opening_balance`, `active`, `created_at`.
- [x] Create a `Categories` worksheet with columns: `id`, `name`, `kind`.
- [x] Create a `Transactions` worksheet with columns: `id`, `txn_date`, `kind`, `amount`, `account_id`, `to_account_id`, `category_id`, `payee`, `description`, `reference`, `created_at`.
- [x] Freeze and protect each header row.
- [x] Avoid merged cells, formulas in data columns, and manual column renaming.
- [x] Record the spreadsheet ID from its URL (store outside the repository).

## 3. Configure Google Cloud

- [x] Create Google Cloud project `tabula-rosa-heathcote-advisory`.
- [x] Enable the Google Sheets API.
- [x] Enable the Google Drive API for backups and exports.
- [x] Create service account `tabula-rosa-app@tabula-rosa-heathcote-advisory.iam.gserviceaccount.com`.
- [x] Create service-account credentials and store them in the ignored local `cred/` directory.
- [x] Share only the ledger workbook with the service account email.
- [x] Give the service account Editor access to that workbook.
- [x] Keep the workbook private and exclude service-account credentials from Git.

## 4. Configure secrets and authentication

- [x] Create a local `.streamlit/secrets.toml` for development.
- [x] Store the spreadsheet ID and service-account credentials in secrets.
- [ ] Deploy the Streamlit app as private and restrict viewer access.
- [ ] Optionally add a second application password.
- [ ] Store only the password hash in Streamlit Secrets.
- [x] Block all pages and data operations until authentication succeeds.
- [x] Add logout behavior.
- [ ] Ensure logs and error messages never expose credentials.

## 5. Build the Google Sheets storage layer

- [x] Add the required Google API or Sheets client dependencies.
- [ ] Verify create, read, update, and delete access using a disposable worksheet.
- [ ] Isolate workbook access in a dedicated storage module.
- [ ] Implement worksheet and header validation.
- [ ] Implement account listing, creation, editing, and deactivation.
- [ ] Implement category listing and creation.
- [ ] Implement transaction listing, creation, editing, and deletion.
- [ ] Implement CSV transaction import.
- [ ] Implement backup and export functions.
- [ ] Keep Google-specific code out of the Streamlit UI where practical.

## 6. Replace SQLite behavior safely

- [ ] Replace integer IDs with UUID strings; never use worksheet row numbers as IDs.
- [ ] Enforce unique account names in the application.
- [ ] Enforce unique category name-and-kind combinations.
- [ ] Validate every account and category reference before writing.
- [ ] Validate positive numeric amounts and valid dates.
- [ ] Require a different destination account for transfers.
- [ ] Prevent deletion of referenced accounts or categories.
- [ ] Store timestamps consistently in ISO 8601 format.
- [ ] Preserve existing balance, transfer, income, expense, and P&L behavior.

## 7. Handle spreadsheet-specific concerns

- [ ] Address columns by header name rather than relying on fixed positions where possible.
- [ ] Use batch updates for related changes.
- [ ] Re-read records before editing or deleting them.
- [ ] Cache reads briefly and clear affected caches immediately after writes.
- [ ] Add retries with exponential backoff for temporary Google API failures.
- [ ] Display clear availability errors and report success only after confirmed writes.
- [ ] Prevent duplicate submissions caused by repeated button clicks.
- [ ] Consider an append-only audit worksheet for important changes.

## 8. Migrate existing data

- [ ] Back up `data/ledger.db`.
- [ ] Build a one-time SQLite-to-Google-Sheets migration tool.
- [ ] Migrate accounts, then categories, then transactions.
- [ ] Map old integer IDs to new UUIDs while preserving relationships.
- [ ] Compare row counts, account balances, income, expenses, transfers, and P&L totals.
- [ ] Do not retire SQLite until every comparison passes.

## 9. Add and test backups

- [ ] Export all worksheets as CSV files or a single ZIP archive.
- [ ] Include a manifest with backup time and row counts.
- [ ] Save periodic backup copies in a separate Google Drive folder.
- [ ] Optionally synchronize the backup folder to the DS220j.
- [ ] Test restoration into a blank workbook.
- [ ] Retain several historical backups instead of overwriting one file.

## 10. Test the application

- [ ] Test account and category management.
- [ ] Test income, expenses, transfers, edits, and deletions.
- [ ] Test CSV imports, duplicate validation, and report totals.
- [ ] Test simultaneous browser tabs and repeated submissions.
- [ ] Test temporary Google API failures.
- [ ] Test authentication, logout, and unauthorized access.
- [ ] Test the complete workflow on a phone.

## 11. Deploy and cut over

- [ ] Push the sanitized project to the private GitHub repository.
- [ ] Deploy `app.py` through Streamlit Community Cloud.
- [ ] Copy secret values into the deployment's Secrets settings.
- [ ] Confirm service-account workbook access and private viewer restrictions.
- [ ] Review deployment logs for sensitive or overly detailed output.
- [ ] Put the SQLite app temporarily into read-only mode.
- [ ] Run and verify the final migration.
- [ ] Begin entering all new transactions through the hosted app.
- [ ] Retain the final SQLite backup and verify the first Drive/NAS backup.
- [ ] Document credential locations and the recovery procedure.

## Security notes

- A private repository is an additional safeguard, not a substitute for secrets management or app authentication.
- Google Drive should hold the Google Sheets workbook and backups, not a live SQLite file synchronized through Drive.
- Grant the service account access only to the specific workbook it needs.
- Rotate any credential immediately if it is accidentally committed, even to a private repository.
