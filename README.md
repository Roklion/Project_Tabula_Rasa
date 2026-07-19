# Plain Ledger

A private Google Sheets-backed bookkeeping app for one person or a small group of businesses. Each business can use its own spreadsheet and Google service account while sharing one Streamlit deployment.

## Run it

1. Install Python 3.11 or newer.
2. Configure the ignored `.streamlit/secrets.toml` with the spreadsheet ID, service-account credential, and application password hash.
3. In this folder, run:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   streamlit run app.py
   ```

The app reads and writes the private Google workbook through its narrowly scoped service account. It does not use a local SQLite database as its active datastore.

## Multiple business profiles

Use one top-level application password and put each isolated business under
`business_profiles` in `.streamlit/secrets.toml` (and in the hosted deployment's
Secrets settings):

```toml
app_password_hash = "scrypt$..."

[business_profiles.heathcote]
name = "Heathcote Advisory"
spreadsheet_id = "FIRST_SPREADSHEET_ID"

[business_profiles.heathcote.gcp_service_account]
type = "service_account"
project_id = "first-google-cloud-project"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "ledger@first-google-cloud-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."

[business_profiles.second_shop]
name = "Second Shop"
spreadsheet_id = "SECOND_SPREADSHEET_ID"

[business_profiles.second_shop.gcp_service_account]
# Paste the complete service-account values for this business here.
type = "service_account"
project_id = "different-google-cloud-project"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "ledger@different-google-cloud-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Share each spreadsheet as Editor with the `client_email` from that same
profile. The Google Cloud projects and owning Google accounts may be different;
each profile authenticates independently. After signing in, choose the active
business in the sidebar. Storage clients, default initialization, and duplicate
submission protection are isolated by profile.

The application password currently grants access to every configured profile.
Use separate deployments or add profile-level authorization if different users
must only see particular businesses.

The original single-profile `spreadsheet_id` and `[gcp_service_account]` format
continues to work, so existing deployments do not require an immediate secrets
migration.

## Legacy SQLite backup

The pre-cutover SQLite backup remains available until the Google Sheets implementation has been fully checked. Create another consistent, non-overwriting legacy backup with:

```powershell
python scripts/backup_sqlite.py data/ledger.db data/ledger-pre-google-migration.db
```

The command validates SQLite integrity and the required ledger tables before reporting success.

## Validate Google Sheets access

After configuring the ignored `.streamlit/secrets.toml`, verify the private workbook and its headers with:

```powershell
python scripts/validate_google_sheets.py --profile heathcote
```

To verify create, read, update, and delete permissions, run the reversible disposable-worksheet test:

```powershell
python scripts/validate_google_sheets.py --profile heathcote --write-test
```

The test removes its temporary worksheet during cleanup and does not read or modify ledger rows.

## Run automated tests

Run the isolated authentication, UI workflow, Google storage, and reporting tests with:

```powershell
python -m unittest discover -s tests -v
```

The UI tests use an in-memory Google workbook and a test-only password hash. They do not read the live ledger, application password, or Google credentials.

Run a read-only end-to-end dashboard check against the configured live workbook with:

```powershell
python scripts/validate_app_google.py
```

## Spreadsheet reliability

- Worksheet reads are cached for 10 seconds and the affected cache is cleared immediately after every confirmed write.
- Edits, deletions, uniqueness checks, and reference checks force a fresh read before writing.
- Temporary network and quota failures are retried up to four times with exponential backoff.
- Identical completed submissions are suppressed for 10 seconds within the same application session.
- CSV imports and default seeding use batch appends after complete validation.
- Availability errors are generic and success is shown only after the Google API confirms the write.

An append-only audit worksheet was considered but deferred. A separate audit append cannot currently be guaranteed atomic with its ledger write, so it could create a misleading or incomplete history. Versioned ZIP backups are the current recovery record.

## Google Sheets backups

The **Data & backup** page can download a complete ZIP archive. Each archive
contains `Accounts.csv`, `Categories.csv`, `Transactions.csv`, and a JSON
manifest with the backup time, workbook title, worksheet headers, row counts,
and SHA-256 checksums.

Create and validate a timestamped backup from the command line with:

```powershell
python scripts/backup_google_sheets.py --profile heathcote --output-dir backups\heathcote --keep 30
```

By default, this writes to the ignored `backups/` directory, never overwrites an
existing archive, and retains the newest 30 generations. Backups contain private
ledger data and must not be committed. To place backups in a Google Drive
Desktop or NAS-synchronized folder, pass its local path:

```powershell
python scripts/backup_google_sheets.py --profile heathcote --output-dir "G:\My Drive\Tabula Rosa Backups\heathcote" --keep 30
```

The configured Windows task runs at 10:00 PM every Monday, Tuesday, and
Wednesday. `--once-per-week` verifies existing archives before accessing Google
Sheets, so Tuesday and Wednesday act only as retry opportunities when the
week's earlier run did not succeed. If all three opportunities are missed or
fail, that week is skipped. The task runs interactively because Google Drive
Desktop and its mounted folder are available only in the signed-in Windows
session. The `G:` streaming mount does not remain available independently:
Google Drive for desktop must be running and signed in when the task starts. If
the app, computer, network, or mount is unavailable at 10:00 PM, no backup is
marked complete and the next scheduled Tuesday or Wednesday opportunity tries
again. Starting Drive after a missed run does not trigger an immediate catch-up.

Recreate or update the task with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_weekly_backup_task.ps1 -BackupDirectory "G:\My Drive\path\to\backup\heathcote" -Profile heathcote -TaskName "Tabula Rosa Backup - Heathcote"
```

Register one task with a distinct backup directory and task name for each
profile. This prevents archives with identical timestamps from different
businesses being mixed together.

An optional future upgrade is to replace the local mount with a cloud-native
Google Apps Script or Google user OAuth flow that uploads directly through the
Drive API. The service account remains appropriate for editing the existing
spreadsheet but cannot own newly created backup files in a personal My Drive.

### Restore drill

1. Create a new blank Google spreadsheet and share it with the service-account
   email as Editor.
2. Copy the new spreadsheet ID from its URL.
3. Restore a selected archive with:

```powershell
python scripts/restore_google_sheets_backup.py backups\heathcote\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip --profile heathcote --target-spreadsheet-id NEW_ID --initialize
```

The restore command verifies checksums, headers, IDs, relationships, and row
counts before writing. It refuses the configured live workbook and refuses any
target whose required ledger worksheets already contain data. After writing, it
rereads every restored row and verifies it against the archive.

## Credentials and recovery

- Local development credentials live only in the ignored
  `.streamlit/secrets.toml` file.
- The hosted app uses a separate copy of those TOML values in Streamlit
  Community Cloud's encrypted Secrets settings.
- Required secret entries are `app_password_hash` plus either the legacy
  `spreadsheet_id` and `[gcp_service_account]` entries or one or more
  `[business_profiles.PROFILE]` configurations. Never store their real values
  in Git, README files, issue trackers, or deployment logs.
- The original service-account JSON is not required after both secrets stores
  are configured. If retained for disaster recovery, keep it only in protected
  credential storage outside the repository.
- To rotate the Google credential, disable the old key in Google Cloud, create
  a replacement, update local and hosted secrets, verify access, and then delete
  the old key.
- To replace a forgotten application password, run
  `python scripts/set_app_password.py`, then copy the new hash to the hosted
  Secrets settings.
- Recovery uses a verified versioned ZIP and
  `scripts/restore_google_sheets_backup.py` with a new blank workbook. Never
  test restoration against the live workbook.
- Google Drive holds the newest 30 generations. The optional DS220j Cloud Sync
  copy should use one-way download with destination deletions disabled.

## Notes

- Transfers change account balances but do not affect income or expenses.
- Credit card and loan opening balances should normally be negative.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.
