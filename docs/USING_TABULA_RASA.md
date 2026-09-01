# Using Tabula Rasa

This guide describes normal application workflows and the behavior a user can
see. Setup is in [Setup](SETUP.md), Drive administration is in
[Google Drive](GOOGLE_DRIVE.md), and backup or recovery procedures are in
[Backup and recovery](BACKUP_RECOVERY.md).

## Sign in and select a business

Enter the application password before any ledger page or workbook data is
shown. After signing in, select the business in the sidebar. The selected
business and workbook title remain visible while working.

The global footer makes the [Terms of Use](TERMS_OF_USE.md) and
[Privacy Policy](PRIVACY_POLICY.md) available before sign-in and on every
authenticated page. Opening either public document does not load a business
profile, workbook, or ledger data.

Every workbook operation, cache, duplicate-submission check, import, export,
report, receipt operation, and backup uses the selected profile. Changing
business clears or rebuilds page-local selections and pending notices; it does
not reuse another business's workbook state.

The current application password grants access to every configured profile. It
does not provide per-profile user permissions. Select **Log out** to clear the
authenticated session.

## Dashboard

The Dashboard shows:

- Total balance;
- Income this month;
- Expenses this month;
- Net this month;
- recent activity, up to the current application limit; and
- account balances, ordered by Asset, Liability, then Equity and account name.

On wide screens the two tables sit side by side. At constrained desktop widths
with the expanded sidebar, they stack so each table remains readable.

It uses the latest confirmed Sheets state. When there are no transactions,
the page explains that the first entry can be added from Transactions.

## Accounts

Accounts keep their balance-sheet classification separate from their subtype:

| Subtype | Normal classification |
| --- | --- |
| Bank | Asset |
| Cash | Asset |
| Credit card | Liability |
| Short-term debt | Liability |
| Equity | Equity |
| Other | Asset, Liability, or Equity |

Asset opening balances should normally be positive. Liability and equity
opening ledger balances should normally be negative; reports display those
balances conventionally.

Accounts can have two layers. A child uses a parent with the same
classification, and selectors show a path such as Operating accounts >
Petty cash. Both parent and child accounts can be used by transactions and
transfers. Renaming, promoting, or reparenting preserves the stable account
ID and existing transaction references. A parent with children cannot itself
be moved under another parent until its children are promoted or reparented.

The balance sheet combines direct parent activity and direct child activity
once. A parent with its own activity can show a separate Direct activity row.
The account page supports adding, editing, activation/deactivation, hierarchy
changes, and transaction counts. Accounts are deactivated rather than deleted
so historical references remain valid.

Account names are used by imports. Review names and hierarchy before importing
historical data.

## Categories

Categories are either **Income** or **Expense**. Transfers have no category.
Categories can also have two layers; a child must use a parent of the same
kind. Paths are shown in selectors and reports while the stable category ID
stays on existing transactions after a rename, promotion, or reparenting.

Category summaries retain direct parent activity and child detail without
double-counting. A category can be permanently deleted only when it has no
transaction references and no children. The application performs a fresh
reference check and requires explicit acknowledgement before an eligible
deletion.

Default accounts and categories are seeded only in a blank workbook. Renaming
or deleting a default does not recreate it later.

## Transactions

Income and expense entries affect account balances and income-and-expense
reporting. Transfers move value between two accounts, affect balances, and do
not affect income or expenses.

### Add a transaction

Choose **Income**, **Expense**, or **Transfer**, then enter the date, amount,
account information, and optional payee, reference, and description. Income
and Expense require a same-kind category. Transfer requires two different
active accounts and has no category. New transaction amounts start at **0.00**;
the amount must be greater than zero when you save.

The optional receipt uploader accepts PDF, PNG, JPG, JPEG, WEBP, or HEIC.
Each file must be non-empty and no larger than 20 MB; one selected batch may
not exceed 200 MB. All selected transaction fields and files are validated
before anything is written.

The application saves the transaction in Sheets first, then uploads and links
each selected receipt to the selected profile's Drive folder. If receipt work
is partial, the transaction remains saved, successful links remain linked, and
the page reports complete and unresolved counts with **Retry unresolved
receipts**. An uploaded-but-unlinked file is recovered by its existing Drive
identity rather than blindly uploaded again. A completed workflow resets the
form intentionally; a failed validation or transaction write does not upload
receipts.

### View and edit the ledger

The ledger opens latest-date-first. Its controls appear in this order:

1. **From**;
2. **To**;
3. **Type**;
4. **Accounts**;
5. **Search transactions**;
6. conditional **Clear search**; and
7. **Edit/Bulk** mode immediately before the table.

The table retains these user-facing columns: Date, Type, Account, To account,
Category, Payee, Description, Amount, Receipt, Reference, and ID. To account
is blank for non-transfers and Category is blank for transfers. Receipt shows
when one or more receipts are linked.

Search is a trimmed, case-insensitive substring match over Type, Account, To
account, Category, Payee, Description, Reference, and transaction ID. It is
applied after the date, type, and account filters. It does not search dates,
amounts, receipt contents, receipt filenames, or hidden Drive metadata.
Whitespace-only search behaves as cleared search. The result count and a
separate no-results message are shown; clearing search preserves the other
filters.

Search and filters persist while switching between the Add transaction and
View & edit ledger tabs and while changing Edit/Bulk mode. Leaving and
returning to Transactions resets the table-generation state. Interactive
client-side sorting can persist while the same dataframe widget remains
mounted. Switching Edit/Bulk recreates the widget, safely clears incompatible
selection state, and resets ordering to latest-date-first; the application
does not promise to preserve client-side sorting across that mode change.

Edit is the default mode. The table does not begin with a visibly preselected
row. When the edit section is opened, its selector targets the first visible
transaction. Selecting a visible row or using the selector changes the edit
target. If filters or search hide the current target, the target moves to the
first visible row or is cleared when no rows remain.

### Bulk actions

Choose **Bulk** explicitly to select multiple rows from the visible result
set. Changing the business, filters, search, mode, or navigation clears the
bulk selection. Bulk mode provides only:

- **Copy transaction**, available for exactly one selected row and opening the
  new-transaction copy editor;
- **Export selected**, which downloads the selected visible ledger columns
  without changing the workbook;
- **Change category**, only for an all-Income or all-Expense selection, using
  categories of that same kind; and
- **Permanently delete selected**, which shows the count and aggregate
  absolute amount, requires acknowledgement, removes the ledger rows, and
  leaves linked Drive files in place as unreferenced files.

Transfers and mixed Income/Expense selections cannot use Change category.
Bulk actions recheck the complete stable-ID selection immediately before a
write. The application reports an uncertain mutation after a fresh read rather
than blindly repeating an ambiguous write.

No bulk changes are available for dates, amounts, payees, descriptions,
references, accounts, transfer fields, or receipts. Reconciliation, tags,
receipt-content search, and cash-flow reporting are not part of this workflow.

### Edit and delete

Saved transactions retain their type and can edit the source account,
destination account for transfers, category for income or expense, date,
amount, payee, reference, and description. Transfer accounts must remain
different. An inactive account already referenced by a transaction remains
available when editing that historical record.

Single and bulk deletion are permanent. The acknowledgement explains the
consequence and explicitly says linked Drive files remain.

### Copying a transaction

In **View & edit ledger**, select exactly one visible transaction and choose
**Copy transaction**. The editor opens in a clearly labeled copy mode with the
source date and other eligible fields prefilled. The description retains the
user's memo, adds a period when needed, and ends with exactly one `Copy From
<source ID>` suffix. Recopying a transaction removes stale generated `Copy From
<id>` or `Copied from transaction <id>` notes before adding the current source.
Receipts and receipt
references are never copied; save the new transaction first, then attach any
receipts from its editor. **Save copied transaction** creates a new ID, while
**Cancel copy** leaves the source unchanged and creates nothing.

## Receipts

When Drive is configured for the selected profile, the transaction editor
shows linked receipts with recognizable filenames, open-in-Drive links, and a
Remove receipt action. Removing a receipt reference does not delete the Drive
file.

The editor supports multiple PDF or image uploads in one validated batch.
Filenames are safely sanitized and conflicts receive a numeric suffix such as
receipt (2).pdf. Uploaded files receive stable identity and checksum metadata.
Partial uploads keep successful links, report unresolved files, and offer
retry. **Cancel recovery** discards unresolved local file contents without
deleting files already in Drive; those files remain available in
**Unreferenced receipt**. **Retry recovery check** is shown when a saved
transaction must be rechecked before the upload surface is restored.

In the edit form, choose receipts in the optional uploader immediately above
**Save changes**. Saving the edit starts receipt processing; no separate upload
button is used.

The unreferenced workflow lists eligible app-managed files in the selected
profile's receipt folder and links a chosen file without renaming or
rewriting it. Files needing integrity metadata are called out before linking.
Receipt bytes are not embedded in each ledger backup; recovery uses the
independent protected copy described in [Backup and recovery](BACKUP_RECOVERY.md).

## Mileage

The Mileage page records trip date, business miles, starting location,
destination, business purpose, optional vehicle, and optional notes. It
supports date filtering, trip and mile totals, filtered CSV export, editing,
and permanent deletion. New mileage entries start at zero miles; a positive
distance is required when saving.

When Google Maps is configured, Starting location and Destination offer Google
address suggestions. Select both suggestions, then choose **Calculate mileage**
to request the primary driving distance. The one-decimal suggestion is editable
before save. Changing an endpoint invalidates the old suggestion; choose
**Recalculate** or enter mileage manually. Autocomplete and calculation remain
optional, and manual address/mileage entry continues to work when Google is not
configured or is temporarily unavailable. The recorded Starting location and
Destination controls are the single direct manual-entry fields when Maps is
unconfigured, so the page does not show duplicate address inputs. When Maps is
configured, separate recorded-text fields remain visible; the normal Add and
Edit screens do not require an **Enter address manually** button.

**Round trip** calculates the outbound and reversed return directions
separately and exposes independently editable mileage values. Saving still
creates two independent entries in one confirmed write: one outbound row and
one return row with reversed locations. For newly created round trips, the log
shows the return row before the outbound row within the same date/timestamp
pair; existing rows are not rewritten. The rows have separate IDs and can be
edited or deleted independently later. Recalculating a saved row changes only
that selected row. The log's From and To filters control its metrics, table,
and CSV together.

When editing a saved trip, the calculation button appears directly below the
address controls. Changing an address displays a potential mileage mismatch
warning immediately, even before recalculation. Recalculate the route, or
review and edit the existing mileage manually, before saving.
When an existing trip is opened, its saved addresses appear in the recorded
fields. With Maps configured, those fields are separate from empty Google lookup
controls; without Maps, the single manual controls are initialized from the
saved addresses.

Google-derived address suggestions and route mileage retain visible Google Maps
attribution, including a note below the current mileage control after an
autocomplete selection or route calculation. See
[Google Maps mileage setup](GOOGLE_MAPS.md) for operator, privacy, quota,
billing, and credential requirements.

## Reports

Reports use From and To for income-and-expense analytics and a separate As of
date for the balance sheet. The page presents:

- Income, Expenses, and Net;
- monthly performance;
- expenses by category using Layer 1 rollups;
- category detail with direct activity and Layer 1 total; and
- total assets, liabilities, and equity with Assets, Liabilities, and Equity
  tables.

Current earnings are income minus expenses and are included in total equity.
The balance sheet reports a text-backed balanced state or an out-of-balance
warning with the difference for Assets = Liabilities + Equity. Empty periods,
empty expense results, empty statement groups, and storage failures have
distinct messages. Charts support the reported values; no reconciliation,
cash-flow, or transaction-detail report is implied.

## Data and backup

The **Data & backup** page is organized as:

1. Cloud backup;
2. Recovery status;
3. Exports; and
4. Imports.

Transaction and mileage CSV exports remain available without Drive. A complete
current-format workbook backup requires a valid selected-profile receipt
folder and receipt inventory. **Verify latest cloud backup** only downloads
and validates the selected Drive archive; it does not read or change the live
workbook. See [Backup and recovery](BACKUP_RECOVERY.md) for the operator
workflow.

## Imports

All import previews are profile-scoped and read-only until their explicit
import action. Every row is parsed, validated, and checked for duplicates
before a confirmed batch write. Keep source exports outside the repository
because they may contain private financial or location data.

### Tabula Rasa CSV

Upload a CSV with the required Date, Type, Amount, Account, and Category
columns, plus optional Payee, Description, and Reference columns. Type must be
Income or Expense; this workflow does not import transfers. Review the first
20 rows, diagnostics, and duplicate summary before **Import rows**.

### QuickBooks transactions

Supported source exports are:

- QuickBooks Online Transaction Detail by Account CSV; and
- QuickBooks Self-Employed General ledger XLSX or a ZIP containing the
  supported workbook.

For Transaction Detail by Account, export the report with its headers and
remove title, subtotal, and footer rows before uploading. For Self-Employed,
enable General ledger under Settings > Export data and upload the ZIP or its
General_ledger.xlsx file.

The supported English-language source columns are Date, Transaction Type, Num,
Name, Memo/Description, Account, Split, and Amount.

| QuickBooks value | Import behavior |
| --- | --- |
| Account | Source account |
| Split on Income or Expense | Category |
| Split on Transfer or Funds Transfer | Destination account |
| Positive Amount | Income |
| Negative or parenthesized Amount | Expense |
| Name | Payee |
| Memo/Description | Description |
| Num | Reference |

Names match existing accounts and categories case-insensitively. A duplicate
has the same date, type, amount, source and destination accounts, category,
payee, description, and reference as an existing row or an earlier upload row.
Duplicates are skipped. The preview reports ready, duplicate, income,
expense, transfer, conversion-error, and validation-error counts. Fix
blocking errors before **Import validated rows**; valid rows are written in
one batch.

The optional **Automatically create missing accounts and categories** control
shows proposed additions before writing. New accounts use zero opening balance
and infer a subtype/classification; new categories infer Income from positive
amounts and Expense from negative amounts. New items are Layer 1 records.
Matching uses the stored name, so existing child records remain valid matches.

### QuickBooks mileage

In QuickBooks Online, open Expenses & Bills > Mileage, choose Download Trips,
and upload the CSV under Import QuickBooks mileage.

Recognized data includes trip date, classification, purpose, vehicle, start
address, end address, and distance. Only Business rows are imported.
Personal and Unreviewed rows are counted and skipped. A business row requires
a date, purpose, start address, end address, and positive distance. Explicitly
kilometer-labeled distance columns are converted to miles.

The preview shows ready, duplicate, personal, unreviewed, and validation-error
counts plus row details. A duplicate has the same date, distance, vehicle,
start address, end address, and business purpose as an existing or earlier
upload row. Review the preview before **Import validated mileage**.

## User-visible safety behavior

Temporary Google failures use bounded retries. Edits, deletes, uniqueness
checks, and reference checks use fresh reads. Duplicate completed submissions
are suppressed within the current session and profile. A success notice means
the relevant Google API confirmed the operation; a failure message states
whether data changed and what to do next.
