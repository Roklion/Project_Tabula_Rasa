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

## Notes

- Transfers change account balances but do not affect income or expenses.
- Credit card and loan opening balances should normally be negative.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.

