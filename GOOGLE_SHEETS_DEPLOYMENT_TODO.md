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
- [x] Add a second application password.
- [x] Store only the password hash in Streamlit Secrets.
- [x] Block all pages and data operations until authentication succeeds.
- [x] Add logout behavior.
- [x] Ensure logs and error messages never expose credentials.

## 5. Build the Google Sheets storage layer

- [x] Add the required Google API or Sheets client dependencies.
- [x] Verify create, read, update, and delete access using a disposable worksheet.
- [x] Isolate workbook access in a dedicated storage module.
- [x] Implement worksheet and header validation.
- [x] Implement account listing, creation, editing, and deactivation.
- [x] Implement category listing and creation.
- [x] Implement transaction listing, creation, editing, and deletion.
- [x] Implement CSV transaction import.
- [x] Implement backup and export functions.
- [x] Keep Google-specific code out of the Streamlit UI where practical.

## 6. Replace SQLite behavior safely

- [x] Replace integer IDs with UUID strings; never use worksheet row numbers as IDs.
- [x] Enforce unique account names in the application.
- [x] Enforce unique category name-and-kind combinations.
- [x] Validate every account and category reference before writing.
- [x] Validate positive numeric amounts and valid dates.
- [x] Require a different destination account for transfers.
- [x] Prevent deletion of referenced accounts or categories.
- [x] Store timestamps consistently in ISO 8601 format.
- [x] Preserve existing balance, transfer, income, expense, and P&L behavior.

## 7. Handle spreadsheet-specific concerns

- [x] Address columns by header name rather than relying on fixed positions where possible.
- [x] Use batch updates for related changes.
- [x] Re-read records before editing or deleting them.
- [x] Cache reads briefly and clear affected caches immediately after writes.
- [x] Add retries with exponential backoff for temporary Google API failures.
- [x] Display clear availability errors and report success only after confirmed writes.
- [x] Prevent duplicate submissions caused by repeated button clicks.
- [x] Consider an append-only audit worksheet; defer it until audit writes can be made reliably without implying atomicity.

## 8. Migrate existing data — not applicable

- [x] Skip the SQLite migration because there is no existing user-entered SQLite data to preserve.
- [x] Use the initialized Google Sheets workbook as the starting data set.

## 9. Add and test backups

- [x] Export all worksheets as CSV files in a single ZIP archive.
- [x] Include a versioned manifest with backup time, workbook title, headers, row counts, and checksums.
- [x] Save periodic backup copies in a separate Google Drive folder through Google Drive Desktop.
  - [x] Create and verify the first backup in the Google Drive Desktop-synchronized `backup` folder.
  - [x] Schedule one weekly backup for Monday at 10:00 PM, with Tuesday and Wednesday at 10:00 PM as retry opportunities only.
- [ ] Optional upgrade: replace the local Drive mount with cloud-native Google Apps Script or user OAuth Drive API uploads.
- [ ] Optionally synchronize the backup folder to the DS220j.
- [ ] Test restoration into a disposable blank Google workbook.
  - [x] Test verified restoration into a blank in-memory workbook without changing live data.
- [x] Retain several timestamped historical backups instead of overwriting one file (default: 30).

## 10. Test the application

- [x] Test account and category management after the Google Sheets UI cutover.
  - [x] Test the in-memory Google-backed UI workflow and storage-layer behavior.
- [x] Test income, expenses, transfers, edits, and deletions after the Google Sheets UI cutover.
  - [x] Test Google-backed UI entry/deletion and storage-layer CRUD/editing.
- [x] Test CSV imports, duplicate validation, and report totals after the Google Sheets UI cutover.
  - [x] Test batch CSV prevalidation, account/category duplicates, balances, transfers, and P&L calculations.
  - [x] Test malformed and valid CSV uploads, duplicate UI submissions, and exact dashboard/report totals through Streamlit.
- [ ] Test simultaneous browser tabs after deployment.
  - [x] Test short-window suppression of repeated identical submissions.
- [x] Test temporary Google API failures through the integrated UI.
  - [x] Test safe storage-layer failure handling without credential leakage.
- [x] Test application-password authentication, logout, and unauthorized page blocking.
- [ ] Test the complete workflow on a phone after deployment.

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
