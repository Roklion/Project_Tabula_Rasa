# Plain Ledger

A local-first bookkeeping app for one person or a very small business. It tracks income, expenses, transfers, accounts, categories, and simple profit-and-loss reports without connecting to a bank.

## Run it

1. Install Python 3.11 or newer.
2. In this folder, run:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   streamlit run app.py
   ```

The app creates `data/ledger.db` automatically. Set `LEDGER_DB_PATH` to place the database elsewhere, including a mounted Synology folder:

```powershell
$env:LEDGER_DB_PATH = "Z:\Bookkeeping\ledger.db"
streamlit run app.py
```

For two users, run the app on one always-on computer or NAS-accessible Docker host and let both people open its local network address. SQLite is suitable for this low-write workload, but keep only one app process pointed at the database and use the built-in database backup regularly.

## Back up before migration

Keep the SQLite app and at least one verified database backup until the Google Sheets migration has been fully checked. Create a consistent, non-overwriting backup with:

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

The UI tests use disposable databases and a test-only password hash. They do not read the local ledger, application password, or Google credentials.

## Notes

- Transfers change account balances but do not affect income or expenses.
- Credit card and loan opening balances should normally be negative.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.
