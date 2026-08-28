# Using Project Tabula Rasa

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

Operational pages use compact native Streamlit forms, tables, tabs, and
expanders with consistent working-surface boundaries. The Dashboard gives its
summary and recent activity the strongest hierarchy; Reports and Data & backup
separate their independent sections with the same restrained spacing. At
narrow widths, columns stack and tables retain intentional horizontal scrolling
when all accounting fields need to remain available. Native component and
browser chrome differences remain possible across Streamlit versions. On narrow
screens, Streamlit's native navigation drawer may remain open after a route is
selected; it can be closed with the drawer control without affecting the active
route or page state.

## Select a business

Choose the active business in the sidebar after signing in. Every workbook
operation, cache, duplicate-submission check, Google Drive operation, import,
export, and report is scoped to that selected profile.

The current application password grants access to every configured profile. It
does not implement per-profile user permissions.

Changing the business selector keeps the selected business and its workbook
title visible while clearing page-local selections and pending notices from the
previous business. The route remains available, but table selections and edit
targets are rebuilt for the newly selected workbook.

## Dashboard

The Dashboard keeps the current four summary values near the top:

- **Total balance**;
- **Income this month**;
- **Expenses this month**; and
- **Net this month**.

Recent activity is the wider lower section and shows up to eight transactions
with Date, Type, Payee, Category, Account, and Amount. Account balances remain
alongside it on wide screens and stack after recent activity in a narrow
viewport. The tables keep their existing fields and use intentional table
scrolling when their content needs more width; no additional trends or cash
flow claims are inferred from the Dashboard.

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

The Accounts page presents the required Account, Layer, Parent, Classification,
Type, Active, Balance, and Transaction count columns in a compact selectable
table. The Active column says **Active** or **Inactive** in text; it does not
rely on color. The add and edit controls are grouped in the **Add account** and
**Edit or deactivate account** sections. The same family balance appears on a
Layer 1 parent row, and its transaction count includes transactions posted to
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

The Categories page presents Category, Layer, Parent, Type, and Transaction
count in a compact selectable table. Add and edit controls are grouped in the
**Add category** and **Edit category** sections, and the parent selector shows
the full hierarchy path while storing the stable parent ID. Categories can be
renamed without changing their IDs. A category with no transactions or child
categories can be permanently deleted only after acknowledging the permanent
consequence. Categories that are still referenced by transactions, or that
still have child categories, are blocked by a fresh reference check and must be
retained or edited instead.

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

The **View & edit ledger** tab includes a **Search transactions** field in
addition to the From, To, Type, and Accounts filters. Search is a trimmed,
case-insensitive substring match over Type, Account, To account, Category,
Payee, Description, Reference, and transaction ID. It applies after the
structured filters, so clearing the search restores exactly the current
date/type/account result set. Empty or whitespace-only text behaves like a
cleared search. Search does not inspect dates, amounts, receipt contents or
filenames, or hidden Google Drive metadata. The ledger reports the number of
visible rows and shows a separate no-results message when a search/filter
combination matches nothing; an entirely empty ledger has its own empty state.
Search persists while switching between the two Transactions tabs and resets
after leaving Transactions and returning. If the current edit row is filtered
out, selection moves to the first visible row; if none remain, the stale edit
selection is cleared.

### Bulk transaction actions

The ledger defaults to **Edit** mode, where the table selects one row and the
existing transaction editor remains available. Choose **Bulk** mode explicitly
to select multiple rows from the currently visible result set. Changing the
business, filters, search, mode, or navigation clears the bulk selection.

Bulk mode provides only these actions:

- **Export selected** downloads the selected user-facing ledger columns in the
  current visible order without changing the workbook.
- **Change category** is available only for a homogeneous Income or Expense
  selection and offers categories of that same kind.
- **Permanently delete selected** shows the count and aggregate absolute amount,
  requires an explicit acknowledgement, and removes only the ledger rows. The
  linked receipt references are removed, but the Google Drive files remain and
  become unreferenced files.

Category changes and deletions re-read the selected stable transaction IDs and
resolve worksheet rows immediately before one atomic Google Sheets
`spreadsheets.batchUpdate` request. Google validates the complete request before
applying it ([API reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)); a collaborator can still
change the final sheet. If a network response is uncertain, the application
reads the selected IDs again and reports whether the batch fully applied, did
not apply and is safely retryable, or has a mixed/ambiguous outcome. It never
blindly retries an ambiguous mutation.

The application validates required references, fresh account/category state,
and duplicate submissions before writing. A success message appears only after
Google Sheets confirms the operation.

### Receipts during transaction creation

The **Add transaction** form accepts zero, one, or multiple optional receipt
files for income, expense, and transfer entries. Select PDF, PNG, JPG, JPEG,
WEBP, or HEIC files; each file must be non-empty and no larger than 20 MB.
Every selected file is validated before the transaction is written to Google
Sheets.

Sheets creates the transaction first. Only after that write is confirmed does
the application upload and link each receipt in the selected profile's Google
Drive folder. Duplicate filenames are retained as separate files with numeric
suffixes, such as `receipt (2).pdf`.

The transaction remains saved if any receipt fails. The form shows one concise
notice with the number of complete and unresolved receipts, reports available
errors, and provides **Retry unresolved receipts**. A receipt that is already
linked is not re-uploaded or re-linked during recovery. If a file was uploaded
but linking failed, recovery retries the same Drive file or uses the transaction
editor's **Unreferenced receipt** workflow.

## Receipts

When Google Drive is configured for the selected profile, open a saved
transaction under **Transactions > View & edit ledger > Receipt**.

The transaction editor accepts one or more receipt files in a single upload.
All selected files are validated before any upload begins. A partial result
keeps successful links, reports concise complete and unresolved counts, and
offers **Retry unresolved receipts**. If a file was uploaded but its ledger
link failed, retry uses that existing Drive file rather than uploading it
again. Duplicate filenames remain separate files with numeric suffixes.

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
Project Tabula Rasa refreshes the selected profile's receipt folder and reconciles
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

On **Add trip**, the form keeps related inputs compact: Trip date and Vehicle
share a row, Business miles and Round trip share a row, and Starting location
and Destination share a row. The primary **Save mileage trip** action remains
at the end of the form. In **View & edit mileage log**, From and To appear above
the Trips and Business miles metrics, followed by the secondary filtered CSV
download and the eight-column mileage table. Select a row or use **Mileage trip
to edit** in the **Edit mileage trip** section; its save and permanent-delete
actions remain independent.

Selecting **Round trip** while adding a trip creates two entries in one write:

1. the outbound entry; and
2. a return entry with the start and destination reversed.

Each entry receives the mileage value entered in the form. Enter the distance
for one direction when using this option.

QuickBooks mileage imports remain a separate workflow described in
[QuickBooks import](QUICKBOOKS_IMPORT.md).

## Reports

Project Tabula Rasa provides account balances, income-and-expense reporting, and a
balance sheet.

The Reports page is organized in this order:

1. **Report period** — separate **From** and **To** date controls for income and
   expense analytics;
2. **Income and expense analytics** — Income, Expenses, and Net metrics followed
   by Monthly performance and Expenses by category charts;
3. **Category detail** — a Category, Layer, Parent, Direct activity, and Layer 1
   total table when category activity exists; and
4. **Balance sheet** — a separate **As of** date, total assets/liabilities/equity
   metrics, Assets/Liabilities/Equity tables, and an explicit balance status.

The monthly performance chart is a grouped bar chart and the category chart is a
horizontal ranking bar chart. Both use currency axes and resize within their
columns. Charts are supporting views for the values above them; they do not add
cash-flow, reconciliation, or transaction-detail reports.

The complete current Reports inventory is:

- Controls: **From**, **To**, and the separate balance-sheet **As of** date.
- Income-and-expense metrics: **Income**, **Expenses**, and **Net**.
- Charts: **Monthly performance** with Income and Expenses series, and
  **Expenses by category** using Layer 1 rollup totals.
- Category table: **Category**, **Layer**, **Parent**, **Direct activity**, and
  **Layer 1 total**. Layer 1 totals include direct activity and Layer 2 children
  without double-counting them.
- Balance-sheet metrics: **Total assets**, **Total liabilities**, and **Total
  equity**.
- Balance-sheet tables: **Assets**, **Liabilities**, and **Equity**, each with
  **Account**, **Type**, and **Balance**. Equity also includes **Current
  earnings**. Hierarchical accounts may include **Layer 1 total** and **Direct
  activity** rows.
- States and errors: no activity in the selected period, no expenses in the
  selected period, no accounts in an empty statement group, a text-backed
  balanced status, a text-backed out-of-balance warning with the difference, and
  a storage error when the selected profile's Sheets reads fail.

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

The page is organized as **Cloud backup**, **Recovery status**, **Exports**, and
**Imports**. **Verify latest cloud backup** is read-only: it downloads and
validates the selected Drive archive without reading or changing the live
workbook. Export preparation creates a snapshot for the selected profile and
current workbook revision; a confirmed write makes an older prepared snapshot
ineligible for reuse. The manual page download names use `tabula-rasa` while
the backup archive format and cloud-managed compatibility names remain stable.

Transaction and mileage CSV exports remain available when Google Drive is not
connected. The complete backup ZIP requires the selected profile's receipt
folder so its receipt inventory cannot be mistaken for an empty folder.

Transaction CSV exports keep the existing machine-facing account and category
name columns unchanged. Hierarchy paths are presentation labels in the app and
do not replace those raw export values.

CSV and QuickBooks imports validate all rows before writing and use batch
appends. Each of the three import uploaders has separate staged state, and
previewing—including proposed account/category creation—does not write until
its explicit import button is selected. Follow [QuickBooks import](QUICKBOOKS_IMPORT.md)
for supported formats and duplicate rules.

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
