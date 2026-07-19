# Plain Ledger

A private Google Sheets-backed bookkeeping app for one person or a very small business. It tracks income, expenses, transfers, accounts, categories, and simple profit-and-loss reports without connecting to a bank.

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

## Legacy SQLite backup

The pre-cutover SQLite backup remains available until the Google Sheets implementation has been fully checked. Create another consistent, non-overwriting legacy backup with:

```powershell
python scripts/backup_sqlite.py data/ledger.db data/ledger-pre-google-migration.db
```

The command validates SQLite integrity and the required ledger tables before reporting success.

## Validate Google Sheets access

After configuring the ignored `.streamlit/secrets.toml`, verify the private workbook and its headers with:

```powershell
python scripts/validate_google_sheets.py
```

To verify create, read, update, and delete permissions, run the reversible disposable-worksheet test:

```powershell
python scripts/validate_google_sheets.py --write-test
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
python scripts/backup_google_sheets.py --keep 30
```

By default, this writes to the ignored `backups/` directory, never overwrites an
existing archive, and retains the newest 30 generations. Backups contain private
ledger data and must not be committed. To place backups in a Google Drive
Desktop or NAS-synchronized folder, pass its local path:

```powershell
python scripts/backup_google_sheets.py --output-dir "G:\My Drive\Tabula Rosa Backups" --keep 30
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
powershell -ExecutionPolicy Bypass -File scripts\register_weekly_backup_task.ps1 -BackupDirectory "G:\My Drive\path\to\backup"
```

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
python scripts/restore_google_sheets_backup.py backups\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip --target-spreadsheet-id NEW_ID --initialize
```

The restore command verifies checksums, headers, IDs, relationships, and row
counts before writing. It refuses the configured live workbook and refuses any
target whose required ledger worksheets already contain data. After writing, it
rereads every restored row and verifies it against the archive.

## Notes

- Transfers change account balances but do not affect income or expenses.
- Credit card and loan opening balances should normally be negative.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.
