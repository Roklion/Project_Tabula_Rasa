# Using Tabula Rosa

This guide summarizes the application's ledger, receipt, mileage, reporting, and
export behavior. Setup and recovery procedures live in the task-specific guides
linked from the [documentation index](../README.md).

## Select a business

Choose the active business in the sidebar after signing in. Every workbook
operation, cache, duplicate-submission check, Google Drive operation, import,
export, and report is scoped to that selected profile.

The current application password grants access to every configured profile. It
does not implement per-profile user permissions.

## Accounts

Accounts store a balance-sheet classification separately from their subtype:

| Subtype | Normal classification |
| --- | --- |
| Bank | Asset |
| Cash | Asset |
| Credit card | Liability |
| Short-term debt | Liability |
| Equity | Equity |
| Other | Asset, Liability, or Equity |

Asset opening balances should normally be positive. Liability and equity
opening ledger balances should normally be negative; balance-sheet reporting
presents them as conventional positive balances.

Account names are referenced by imports, so rename or create accounts
deliberately before importing historical data.

## Categories

Categories are classified as Income or Expense. Transactions use categories for
income and expense reporting; transfers do not use categories.

QuickBooks imports can optionally propose missing categories, but all proposed
additions should be reviewed before the batch write.

## Transactions and transfers

Income and expense transactions affect both the selected source account and
income-and-expense reporting.

Transfers move value between two accounts. They change account balances but do
not affect income or expenses.

The application validates required references, fresh account/category state,
and duplicate submissions before writing. A success message appears only after
Google Sheets confirms the operation.

## Receipts

When Google Drive is configured for the selected profile, open a saved
transaction under **Transactions > View & edit ledger > Receipt**.

Receipt behavior:

- supported files are PDFs and images accepted by the application;
- files are uploaded to the profile's selected receipt folder;
- filenames are sanitized while retaining their recognizable original name;
- a conflicting filename receives a numeric suffix such as
  `receipt (2).pdf` instead of replacing the existing file;
- uncertain upload responses are checked before retrying to avoid duplicates;
- each transaction stores stable Drive file IDs and display names; and
- removing a receipt from a transaction removes only its ledger reference.

An unlinked Drive file remains in the receipt folder and becomes available in
the transaction editor's **Unreferenced receipt** list.

Receipt file contents are not embedded in the ledger backup ZIP. The backup
contains only receipt references; retain the separate Google Drive receipt
folder according to the business's recordkeeping needs.

## Mileage

The **Mileage** page records:

- trip date;
- total business miles;
- start and destination;
- business purpose;
- optional vehicle; and
- optional notes.

It supports date filtering, editing, deletion, totals, and CSV export.

Selecting **Round trip** while adding a trip creates two entries in one write:

1. the outbound entry; and
2. a return entry with the start and destination reversed.

Each entry receives the mileage value entered in the form. Enter the distance
for one direction when using this option.

QuickBooks mileage imports remain a separate workflow described in
[QuickBooks import](QUICKBOOKS_IMPORT.md).

## Reports

Tabula Rosa provides account balances, income-and-expense reporting, and a
balance sheet.

Current earnings are calculated as income minus expenses and included in total
equity. The balance sheet flags any difference in:

```text
Assets = Liabilities + Equity
```

Reports reflect the active business profile and the latest confirmed Google
Sheets state.

## Imports and exports

The **Data & backup** page provides:

- transaction and mileage CSV exports;
- QuickBooks transaction imports;
- QuickBooks mileage imports;
- a complete validated workbook backup ZIP; and
- Google Drive cloud backup controls when configured.

CSV and QuickBooks imports validate all rows before writing and use batch
appends. Follow [QuickBooks import](QUICKBOOKS_IMPORT.md) for supported formats
and duplicate rules.

Follow [Backup and recovery](../operations/BACKUP_AND_RECOVERY.md) for archive
contents, verification, scheduling, retention, and restoration.

## Availability and safety behavior

- Temporary Google failures are retried with bounded exponential backoff.
- Reads needed for edits, deletes, uniqueness checks, and reference checks are
  refreshed before writing.
- Identical completed submissions are suppressed briefly within the same
  session and business profile.
- A reported success means the relevant Google API confirmed the operation.
- This is a record-keeping tool, not tax or accounting advice.
