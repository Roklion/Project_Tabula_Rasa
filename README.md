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

## Notes

- Transfers change account balances but do not affect income or expenses.
- Credit card and loan opening balances should normally be negative.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.
