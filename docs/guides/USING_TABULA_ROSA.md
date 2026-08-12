# Using Tabula Rosa

This guide summarizes the application's ledger, receipt, mileage, reporting, and
export behavior. Setup and recovery procedures live in the task-specific guides
linked from the [documentation index](../README.md).

## Sign in and application shell

Enter the application password before any ledger page or workbook data is
rendered. After sign-in, the sidebar keeps the active business, operational
routes, selected workbook title, and **Log out** action discoverable. The
business selector scopes all subsequent work to one profile; signing out clears
the authenticated session and returns to the password gate.

The shell uses a warm application canvas, white data surfaces, compact spacing,
visible keyboard focus, and text-backed status messages. These presentation
choices do not change route order, form fields, ledger columns, profile
selection, or storage behavior.

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

Accounts may be arranged in two layers. A Layer 2 account selects a Layer 1
parent with the same balance-sheet classification. Both layers remain valid
transaction and transfer choices, and selectors show children as paths such as
`Operating accounts › Petty cash`. Reparenting or promoting an account keeps its
stable ID and all existing transaction references. A Layer 1 account that still
has children cannot itself be moved under another parent. Deactivating a parent
does not deactivate its children or remove its name from historical paths.

The balance sheet shows each Layer 1 account as a family total: the parent's
direct balance plus every Layer 2 child balance. When a parent has its own
opening balance or transactions, a separate **Direct activity** row explains
that component before the child detail. Grand totals still count every direct
account balance exactly once; displayed family totals are never added again.

The Accounts table shows the same family balance on a Layer 1 parent row and
counts the parent's transactions together with transactions posted to its
children. Layer 2 rows continue to show their own direct balance and count.

## Categories

Categories are classified as Income or Expense. Transactions use categories for
income and expense reporting; transfers do not use categories.

QuickBooks imports can optionally propose missing categories, but all proposed
additions should be reviewed before the batch write.

Categories also support two layers. A Layer 2 category must use a Layer 1 parent
of the same Income or Expense kind. Transaction selectors and ledger views show
the full path, while promotion and reparenting preserve the category ID stored
on existing transactions.

The primary category chart groups activity into Layer 1 totals. The detail table
separates each parent's direct activity from its Layer 2 children so grouped
amounts remain explainable without double-counting. Transactions may post
directly to either layer; transfers remain category-free and mileage remains a
separate workflow.

Categories can be renamed without changing their IDs. A category with no
transactions or child categories can be permanently deleted. Categories that
are still referenced by transactions, or that still have child categories, must
be retained or edited instead.

The initial default accounts and categories are seeded only in a blank
workbook, so renaming or deleting a default does not recreate it later.

## Transactions and transfers

Income and expense transactions affect both the selected source account and
income-and-expense reporting.

Transfers move value between two accounts. They change account balances but do
not affect income or expenses.

The transaction ledger opens with the latest transaction dates first. Any
interactive table sort remains in place while moving between **Add transaction**
and **View & edit ledger**, and resets to latest-first after navigating away and
back to **Transactions**.

The application validates required references, fresh account/category state,
and duplicate submissions before writing. A success message appears only after
Google Sheets confirms the operation.

## Receipts

When Google Drive is configured for the selected profile, open a saved
transaction under **Transactions > View & edit ledger > Receipt**.

Receipt behavior:

- supported files are PDFs and images accepted by the application;
- files are uploaded to the profile's selected receipt folder;
- filenames are sanitized while retaining their recognizable original name and
  remaining portable through the documented Windows and Synology recovery path;
- a conflicting filename receives a numeric suffix such as
  `receipt (2).pdf` instead of replacing the existing file;
- uncertain upload responses are checked before retrying to avoid duplicates;
- SHA-256 is calculated from the bytes before every upload;
- Drive stores a stable receipt identity and checksum in private metadata;
- each transaction stores the stable identity, Drive file ID, original and
  stored filenames, MIME type, byte size, and SHA-256; and
- removing a receipt from a transaction removes only its ledger reference.

An unlinked Drive file remains in the receipt folder and becomes available in
the transaction editor's **Unreferenced receipt** list.

Linking an unreferenced receipt copies its existing integrity metadata without
renaming or rewriting the Drive file. Before a complete backup is created,
Tabula Rosa refreshes the selected profile's receipt folder and reconciles
active references with Drive. This preparation is resumable, does not download
receipts that already have valid metadata, and preserves an explicitly empty
reference list as intentionally unlinked. If preparation fails, no backup is
created; resolve the reported problem and retry.

Receipt file contents are not embedded in each ledger backup ZIP. Format-version
5 and later backups contain a checksummed `receipts.json` metadata inventory,
including intentionally unreferenced app-managed files. Recoverable receipt
bytes must be retained separately; follow the [Synology recovery
runbook](../operations/SYNOLOGY_RECOVERY.md) for the independent, versioned
copy and Drive ID-remapping workflow.

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

Transaction and mileage CSV exports remain available when Google Drive is not
connected. The complete backup ZIP requires the selected profile's receipt
folder so its receipt inventory cannot be mistaken for an empty folder.

Transaction CSV exports keep the existing machine-facing account and category
name columns unchanged. Hierarchy paths are presentation labels in the app and
do not replace those raw export values.

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
