# Using Tabula Rasa

This guide describes normal application workflows and the behavior a user can
see. Setup is in [Setup](SETUP.md), Drive administration is in
[Google Drive](GOOGLE_DRIVE.md), and backup or recovery procedures are in
[Backup and recovery](BACKUP_RECOVERY.md).

The Streamlit edition uses Sheets. A profile configured by the operator for
bookkeeping maintenance or PostgreSQL stops before Sheets initialization; it
does not silently open another backend. Backend changes have no UI picker and
follow the [controlled cutover procedure](BOOKKEEPING_CUTOVER.md).
Lasting owner-operated PostgreSQL use follows its
[owner-operated production procedure](BOOKKEEPING_CUTOVER.md#owner-operated-production-procedure-299)
on the shared web/API application, with normal authorization and explicitly
accepted recovery limitations. This does not add a backend picker to Streamlit
or claim that unfinished web workflows or NAS protection are delivered.

The separate commercial technical-alpha browser now supports editing existing
accounts, categories, payees/tags, simple transactions, journals and mileage.
Accounts deactivate rather than delete; referenced records retain their deletion
guards. If another client changes a loaded record, your save/delete is refused
and your draft stays visible. Choose **Review latest record**, then **Keep draft**
or **Discard draft and reload**; review the latest values before saving again.
Payee/tag merges also protect every loaded target/source. See
[Commercial concurrency](COMMERCIAL_CONCURRENCY.md) for scope and local validation.
The core commercial workflows also provide business selection, reference setup,
transaction/journal creation, the combined ledger and essential reports. Choose
**Select business** to switch the configured demonstration business, then confirm
whether to discard the current draft. Use **Add account/category/payee/tag** on
the setup pages, or **Add transaction/journal** on Transactions. Reports and the
Dashboard show server-calculated totals; their date controls govern the period
and balance-sheet as-of date. See [Commercial core workflows](COMMERCIAL_WORKFLOWS.md)
for the supported scope, creation/error behavior and remaining initiative work.
These forms do not change the Streamlit workflows described below or establish
commercial production readiness.

The browser also provides the complete manual mileage list/create/detail/edit/
delete journey, date/tag filters, totals, CSV download and round-trip capture.
Saved ordinary transactions offer receipt attachment, inspection/download,
unreferenced-file recovery and confirmed unlink without deleting the file when
the business's DocumentStore is configured. Upload/link errors keep confirmed
work and offer retry for unresolved files. See
[Commercial mileage and receipts](COMMERCIAL_MILEAGE_RECEIPTS.md) for these browser
workflows, their recovery behavior and remaining release boundaries.
The [technical-alpha release guide](TECHNICAL_ALPHA.md) lists the exact staged
workflow coverage, outstanding hosted receipt/rollback/manual evidence and
remaining internal-edition workflows during the Streamlit transition.

## Sign in and select a business

Enter the application password before any ledger page or workbook data is
shown. After signing in, select the business in the sidebar. The selected
business and workbook title remain visible while working.
The sidebar also shows the selected profile key directly below the Business
selector. Use that key when identifying a profile in setup or recovery steps.

The global footer makes the [Terms of Use](TERMS_OF_USE.md) and
[Privacy Policy](PRIVACY_POLICY.md) available before sign-in and on every
authenticated page. Opening either public document does not load a business
profile, workbook, or ledger data.

Every workbook operation, cache, duplicate-submission check, import, export,
report, receipt operation, and backup uses the selected profile. Changing
business clears or rebuilds page-local selections and pending notices; it does
not reuse another business's workbook state.

Ledger initialization, lazy Drive clients, and page settings use one configuration snapshot. Switching workbooks initializes its defaults and scopes prepared exports to the new workbook.
Configuration changes take effect together on the next rerun. If the selected
profile cannot be resolved during initialization, the app stops and asks you
to reload and check its settings; it does not substitute another workbook.

The current application password grants access to every configured profile. It
does not provide per-profile user permissions. Select **Log out** to clear the
authenticated session.

## Google Maps API usage

The bottom of the authenticated sidebar contains a compact **Google Maps API
usage** expander. Routes API and Places API (New) are shown separately with
effective quota and the latest Google-sampled rate in the quota's limit units.
If monitoring is not configured, the expander shows setup guidance; a
successful response with no Google data shows zero. Cloud Monitoring
sampling/reporting can lag several minutes, including up to about 240 seconds
after sampling, so this is not a real-time remaining-request or billing/spend
meter. The refresh action clears only this view's 120-second cache.

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

## Assets

Use **Assets** to keep a separate, durable record for each business-use item
whose cost is depreciated over time. Assets is a top-level Workspace page, not
a Transactions tab. Adding an asset does not create, delete, reclassify, or
otherwise change the transaction used to buy it.

Each asset records its name, pre-enumerated asset type, optional notes,
acquisition date, depreciation start date, cost basis, salvage value, useful
life in quarters, and the currently supported **Straight-line** method. You can
also select an existing managed Payee, Tags, a reference, and an optional source
acquisition transaction. A linked transaction's existing receipt names appear
as audit context; receipts are not copied. If the transaction is later missing,
the asset remains valid and the page identifies the broken link.

The available types cover computers and office equipment; furniture, fixtures,
and appliances; photography, communication, and video equipment; machinery,
equipment, and tools; vehicles; construction and farm
equipment; residential and commercial real property; land and leasehold
improvements; software and other intangibles; and other depreciable property.
Land itself is not offered because land is not depreciable. The selected type
does not automatically choose a tax life or calculate MACRS, Section 179,
bonus depreciation, or a tax return.

Select an asset and choose **Calculate quarterly schedule** to see its schedule.
The first row uses the configured depreciation start date and later rows occur
every three months on the same calendar-day anchor. When that day does not
exist, the occurrence uses month-end without permanently shifting later dates.
There is no partial-quarter proration. The last quarter absorbs any rounding
remainder, so total depreciation always equals cost basis minus salvage value.

To preserve a known historical amount, open **Override a due or past quarter**,
choose the quarter, enter the amount and a required reason, and save. The saved
override is part of the asset's backed-up source record. Later quarters are
rebalanced so the complete schedule still ends at salvage value. Schedule terms
remain locked while any override exists. Before posting, remove the overrides
to return to the ordinary editable straight-line schedule. After posting begins,
all overrides and schedule terms are locked.

Permanent deletion is available only before an asset has saved depreciation
history. Once an override or posted period exists, keep the durable history and
retire the asset instead of deleting it.

Retiring an asset stops schedule rows after the retirement date. It does not
calculate sale proceeds, disposal gain or loss, recapture, or a write-off of
remaining book value. The retirement date cannot precede a posted quarter.

### Post due depreciation

1. Create an **Expense** category for depreciation and an **Other** account
   classified as **Asset** for accumulated depreciation if they do not exist.
2. Select these in the asset's **Depreciation expense account** and
   **Accumulated depreciation account** fields, then save. Simple Ledger uses
   Expense categories as expense debit accounts. The accumulated depreciation
   account must be active when posting.
3. Select the asset, set **Post depreciation through** (defaults to today), and
   choose **Post due depreciation**. The action posts all pending quarters due
   through that date, using their exact scheduled amounts and dates.
4. Choose **Calculate quarterly schedule** to see each quarter's Posted/Pending
   status and its linked **Ledger entry ID**.

Each posted quarter debits depreciation expense and credits accumulated
depreciation. It affects P&L and the balance sheet without changing cash or bank
balances. Zero-amount quarters still receive a durable posting record. This works
in Simple Ledger; no multi-line journal or Full Accounting Ledger is required.
Posting is explicit: calculating, navigating, and rerunning do not post entries.
Repeated posting skips quarters already posted.

After the first posting, schedule terms, overrides, and posting accounts are
locked. Descriptive details remain editable, and retirement stops later quarters.
Generated entries are labelled **Depreciation** in Transactions. Selecting one
explains that it is managed from Assets; ordinary editing, copying, deletion,
recurrence conversion, and receipt changes are unavailable for these entries.
The linked acquisition transaction still owns any existing receipts.

If posting stops partway through, earlier confirmed quarters remain posted.
Refresh the asset schedule and ledger, then post again to continue pending
quarters. An uncertain write is checked by its stable entry ID before a bounded
retry. If the application reports conflicting source history, inspect the asset
and its linked entries before continuing; do not manually recreate the same
quarter. Supported concurrent sessions in one application share the workbook
mutation lock. Independent deployments writing the same workbook concurrently
are outside that coordination boundary.

Asset-period links are included in the existing checksummed backup. Restore
validates each posted entry against its asset schedule and still requires a new
blank workbook.

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

The Accounts table and account selectors are ordered Asset, Liability, then
Equity. Within each classification, parent accounts are sorted by name and
their children follow immediately, sorted by child name.

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
Category selectors follow the same parent-first order as the Categories table:
parents are sorted by name and each parent's children follow immediately,
sorted by category name.

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

Single transaction edits and deletion recheck the visible record against the
current ledger. If it changed, refresh and review it before trying again.

### Add a transaction

In **Add transaction**, the **Entry Type** selector defaults to **Simple
Transaction**. Date and Description / memo are shared above the selected editor.
Changing to **Multi-line Journal** after entering mode-specific values asks you
to discard those values or keep editing. Shared Date and memo are retained.

Choose **Income**, **Expense**, or **Transfer**, then enter the date, amount,
account information, and optional payee, Tags, reference, and description. Income
and Expense require a same-kind category. Transfer requires two different
active accounts and has no category. New transaction amounts start at **0.00**;
the amount must be greater than zero when you save.

The account field is labeled **To Account** for Income and **From Account** for
Expense. Transfers show both **From Account** and **To account**.

Payee / customer is optional. Select an existing active managed Payee or type
a new name into the selector and press Enter to create it inline. Existing
Payee names are recognized case-insensitively, and a new Payee is stored before
the transaction references it.

Tags are optional profile-local labels that remain separate from accounting
Categories. Select zero, one, or multiple stored Tags; remove any selection
without clearing the others. Type a new name into the selector and press Enter
when searching to create a normalized, duplicate-safe Tag and attach it when
the transaction is saved. Enter only one new Tag name at a time; existing Tag
names are recognized as existing selections even when typed with different
capitalization.

The optional receipt uploader accepts PDF, PNG, JPG, JPEG, WEBP, or HEIC.
Each file must be non-empty and no larger than 20 MB; one selected batch may
not exceed 200 MB. All selected transaction fields and files are validated
before anything is written.

The application saves the transaction in Sheets first, then uploads and links
each selected receipt to the selected profile's Drive folder. If receipt work
is partial, the transaction remains saved, successful links remain linked, and
the page reports complete and unresolved counts with **Retry unresolved
receipts**. An uncertain upload is checked once by its stable receipt ID and
content hash, then retried once only when Drive reports no matching file. An
uncertain Sheets link is read back once; if it still cannot be confirmed, the
uploaded file remains available under **Unreferenced receipt**. A completed
workflow resets the form intentionally; a failed validation or transaction
write does not upload receipts.

### Add a multi-line journal

Choose **Multi-line Journal** for an advanced balanced entry. Start with two
blank posting rows, use **+ Add line** for more, and **Remove** to discard a draft
line. Each row has Account, Debit, Credit, Description, and Payee / customer.
The Account selector includes managed accounts and Income/Expense categories,
identified by their labels. Payees are selected from the existing managed list.

Enter a positive amount on exactly one side of every populated row. Completely
blank rows are ignored; an incomplete populated row must be completed or cleared.
The editor shows Total Debits, Total Credits, and Difference. Save becomes
available only when at least two complete lines balance to the cent.

For example, debit Office Expense $100, debit Meals Expense $50, and credit
Checking $150. This saves one journal with three linked postings. It reduces
Checking by $150 and records $150 of expenses. A credit to an expense category
reduces expenses; debit/credit direction is retained exactly, including reversals.

Journals share the normal ledger and affect account balances and reports. They
do not support receipts, Tags, recurrence, copying, or import in this release.
Use the ordinary Simple Transaction editor for those supported workflows.
Depreciation remains available independently through Assets.

### Mixed-use expenses

Open **Mixed-use expenses** as the third tab on Transactions to record an
expense used partly for business. Enter **Total Expense**, **Business Use %**
(greater than 0 and no more than 100, with up to five decimal places), and a
required **Allocation Rationale**. Allocation is total × percentage ÷ 100,
rounded using the normal currency convention; amounts rounding to $0.00 cannot
be saved.

The live **Ledger Result** preview updates without storage writes. Save
immediately creates the source and exactly one linked Expense projection; there
is no Draft workflow. Complete sources can be edited and permanently deleted
only from this tab and preserve the linked transaction identity. A source
without its linked projection is inspection-only; Save and permanent deletion
are unavailable until the source and ledger relationship has been reviewed.
Receipts use the same
configured Drive folder and retry-safe workflow as ordinary transactions.

The allocated projection remains in the normal ledger for balances, reports,
search, filters, and exports, but is marked **Mixed-use** and read-only.
Normal Edit, Delete, Copy, bulk actions, and receipt mutation cannot change it.
If a source exists without its linked ledger projection, the source is shown
for inspection only; Save and permanent deletion are unavailable until the
source and ledger relationship has been reviewed. Bulk source editing is not
supported. For one selected complete source, use **Copy mixed-use expense**.
The app re-reads and validates the source and its linked projection when
copying starts, then opens a distinct new-source editor from an independent
snapshot. It pre-generates new source and projection IDs, preserves the date,
ordinary Expense fields, allocation fields, and active managed Payee/Tag
associations, and ends the memo with exactly one `Copy From <mixed-use source
ID>` suffix. Allocation is normalized again when saved. Copy mode has no
receipt uploader or receipt references; attach receipts only after saving the
new source. **Cancel copy** creates nothing and leaves the original source and
projection unchanged. Incomplete sources remain inspection-only and cannot be
copied.

The **Mixed-use Expense Log** is a single-row-selectable table above the
editor. Select a row to edit that source; the table selection is tied to the
source's stable ID, not to a displayed row value. The selection is scoped to
the active business profile and current workbook revision, so a changed,
removed, or stale selection is cleared safely. The tab starts in **Add
mixed-use expense** mode. Use **Copy mixed-use expense** to open an independent
new-source copy editor, or **Add new mixed-use expense** to clear an edit
selection and return to Add mode. A copy snapshot remains saveable if the
original source changes after copying starts. Switching business profiles
clears or ignores copy state from the other profile. Its columns are Date,
Payee, Account, Category, Total, Business %, Allocated, Rationale, Description,
and Receipt. The Receipt column shows a paperclip when one or more receipts
are linked.

### View and edit the ledger

The ledger opens latest-date-first. Its controls appear in this order:

1. **From**;
2. **To**;
3. **Type**;
4. **Accounts**;
5. **Tags**;
6. **Search transactions**;
7. conditional **Clear search**; and
8. **Edit/Bulk** mode; and
9. **Sort entries by** and **Entry order** when the workbook contains journals.

The table retains these user-facing columns: Date, Type, Account, To account,
Category, Payee, Amount, Tags, Description, Receipt, Reference, and ID. To
account is blank for non-transfers, Category is blank for transfers, and Tags
is blank when no Tags are assigned. The Tags filter includes records containing
any selected Tag. Receipt shows when one or more receipts are linked.

Ordinary transactions remain one row. A journal shows a parent summary followed
by all its postings, with Debit and Credit columns when journals are visible.
Its summary amount is total debits, equal to total credits. Select a parent or
posting to open the entire journal editor. A saved record always opens in its
original editor type. Permanent journal deletion removes every linked posting
after acknowledgement; individual postings cannot be deleted from the ledger.

Type includes **Journal**. The Accounts filter also offers labeled categories.
If a journal posting matches an account, payee, or description search, the whole
journal stays visible. Counts represent logical entries. With journals present,
use the sort controls: header clicks select columns, keeping journal groups
together. App-level ordering remains selected across Edit/Bulk changes.

Search is a trimmed, case-insensitive substring match over Type, Account, To
account, Category, Payee, Tags, Description, Reference, and transaction ID. It is
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
This native sorting behavior applies to workbooks without journals; journals use
the controlled sort behavior described above.

Edit is the default mode. The table does not begin with a visibly preselected
row. When the edit section is opened, its selector targets the first visible
transaction. Selecting a visible row or using the selector changes the edit
target. If filters or search hide the current target, the target moves to the
first visible row or is cleared when no rows remain.

### Bulk actions

If the selection contains a journal, only **Export selected** is available and
includes the complete selected journals. Use Edit to change or permanently delete
a journal. Copy and bulk edits/deletion remain available for eligible simple
transactions; a mixed selection never silently changes only its simple entries.

Choose **Bulk** explicitly to select multiple rows from the visible result
set. Changing the business, filters, search, mode, or navigation clears the
bulk selection. Bulk mode provides only:

- **Copy transaction**, available for exactly one selected row and opening the
  new-transaction copy editor;
- **Export selected**, which downloads the selected visible ledger columns
  without changing the workbook;
- **Apply changes**, which edits Category, Payee, and Tags for the selected
  visible transactions. Category is available only for an all-Income or
  all-Expense selection and uses categories of that same kind. Payee uses an
  existing profile-local Payee, including an explicit **No Payee / blank**
  choice. Tags use complete-set replacement.
- **Permanently delete selected**, which shows the count and aggregate
  absolute amount, requires acknowledgement, removes the ledger rows, and
  leaves linked Drive files in place as unreferenced files.

Transfers and mixed Income/Expense selections cannot use Category changes.
The editor shows the shared current Category, Payee, or complete Tag set, or
the explicit **Mixed / Multiple values** state. Changing a control or selecting
**Apply <field> to all selected** marks only that field for mutation. Untouched
fields—including mixed fields—remain unchanged. Applying Tags replaces the
complete set; clearing all Tags requires the explicit Apply action.

Bulk actions recheck the complete stable-ID selection immediately before a
write. If a transient response is uncertain, the application performs one
fresh readback: a confirmed result is reported as success, an entirely
unchanged selection may be retried once, and any partial or unreadable result
invalidates caches and gives explicit inspection guidance.

No bulk changes are available for dates, amounts, descriptions, references,
accounts, transfer fields, or receipts. Reconciliation,
receipt-content search, and cash-flow reporting are not part of this workflow.

### Payees & Tags

The fifth Transactions tab, **Payees & Tags**, manages the stored values for
the selected business profile. Its separate **Payees** and **Tags** subtabs
show active and inactive records and provide **Add**, **Rename**, **Merge**, and
**Remove** workflows. Names are normalized case-insensitively, while renaming
preserves the stable ID and all references.
Select a Payee or Tag row in its table before opening **Rename** or **Remove**.
Both actions use the selected row; neither requires another record dropdown.

Merging requires an explicit target, one or more source values, and an
acknowledgement. Payee merges update transaction, recurring-schedule, journal, and asset
references and both sides of each MixedUseExpenses source/projection pair. Tag
merges update Transactions, Mileage, recurring schedules, Assets, and
MixedUseExpenses and remove duplicate associations when a row already has both
the source and target tag. Other fields and associations are preserved.

Removal is permanent and allowed only for an unreferenced value. If a Payee or
Tag is still used, the page shows the fresh reference count and blocks removal;
unassign it in the relevant transaction, mileage, recurring, or asset editor or
merge it instead.
Every operation is scoped to the selected profile and reports success only
after the Sheets write is confirmed. An uncertain response is read back once;
only a clearly unchanged operation is retried, while a partial or unreadable
state invalidates caches and gives explicit inspection guidance.

### Recurring expenses

The fourth Transactions tab, **Recurring expenses**, lists profile-local
Expense schedules with their cadence, next due date, status, and stable ID.
Select a schedule row and click **Edit** to open its template editor. The
selected row also controls Pause, Resume, and End. Select a different row to
work on another schedule.
Recurring templates contain only flat Expense fields; receipt references are
never copied into a schedule or generated occurrence. Creating a schedule
also creates its initial occurrence. You can enable **Repeat this Expense**
while editing an ordinary Expense, or **Repeat this mixed-use Expense** while
editing a mixed-use Expense, to use that saved edit as a new schedule's initial
occurrence. The option is hidden when the expense already belongs to a schedule.
The initial Repeat every setting is one month; you can change the cadence before
saving.
Startup reconciliation generates due
occurrences using deterministic schedule/date IDs and is safe to repeat.

Schedules can be paused, resumed, or ended. Editing or deleting an occurrence
does not change its schedule; changing a schedule affects only future
occurrences. A schedule with a failed or invalid occurrence reports attention
for that schedule while other schedules remain available. If a recurring edit
cannot confirm its initial occurrence link, the schedule remains out of
reconciliation and reports attention; if the link is still pending, end that
schedule and retry the expense edit. Mixed-use schedules retain the
source-authoritative source/projection pair and keep receipts specific to
individual occurrences.

### Edit and delete

Saved transactions retain their type and can edit the source account,
destination account for transfers, category for income or expense, date,
amount, payee, Tags, reference, and description. Each Tag can be added or
removed independently. Transfer accounts must remain
different. An inactive account already referenced by a transaction remains
available when editing that historical record.

Single and bulk deletion are permanent. The acknowledgement explains the
consequence and explicitly says linked Drive files remain.

### Copying a transaction

In **View & edit ledger**, select exactly one visible transaction and choose
**Copy transaction**. The editor opens in a clearly labeled copy mode with the
source date, active Tags, and other eligible fields prefilled. The description retains the
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
**Unreferenced receipt**. Add and Edit use the same transaction-specific recovery
and receipt limits. Pending work is cleared if the selected profile's
workbook or receipt folder changes, preventing cross-profile or cross-folder
linking; select any local-only files again after returning to the intended
configuration.

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
destination, business purpose, optional vehicle, optional Tags, and optional notes. It
supports date filtering, trip and mile totals, filtered CSV export, editing,
and permanent deletion. New mileage entries start at zero miles; a positive
distance is required when saving.

Mileage uses the same profile-local Tag list and inline type-and-Enter flow as
Transactions. Select zero, one, or multiple Tags, and remove individual
selections without affecting the others. The log and CSV display resolved Tag
names, and the Tags filter includes trips containing any selected Tag. A round
trip applies the same Tags to both independently saved legs. Enter only one
new Tag name at a time; existing Tag names are recognized as existing
selections even when typed with different capitalization.

When Google Maps is configured, Starting location and Destination offer Google
address suggestions. Select both suggestions, then choose **Calculate mileage**
to request the primary driving distance. Until that action succeeds, a warning
indicates that the selected route has no calculated comparison yet; it is
advisory, and manual mileage entry remains available. The one-decimal suggestion
is editable before save. Changing an endpoint invalidates the old suggestion;
choose **Recalculate** or enter mileage manually. Changing only **Round trip**
preserves the outbound mileage draft; enabling it creates a new return-mileage
field initialized from the current outbound value and warns until the return
route is calculated, while disabling it removes only that return field without
changing outbound mileage. Autocomplete and
calculation remain optional, and manual address/mileage entry continues to work
when Google is not configured or is temporarily unavailable. The recorded
Starting location and Destination controls are the single direct manual-entry
fields when Maps is unconfigured, so the page does not show duplicate address
inputs. When Maps is configured, separate recorded-text fields remain visible;
the normal Add and Edit screens do not require an **Enter address manually**
button.

**Round trip** calculates the outbound and reversed return directions
separately and exposes independently editable mileage values. Saving still
creates two independent entries in one confirmed write: one outbound row and
one return row with reversed locations. For newly created round trips, the log
shows the return row before the outbound row within the same date/timestamp
pair; existing rows are not rewritten. The rows have separate IDs and can be
edited or deleted independently later. Recalculating a saved row changes only
that selected row. The log's From and To filters control its metrics, table,
and CSV together.

When editing a saved trip with Maps configured, the calculation button appears
directly below the address controls. Changing an address displays a potential
mileage mismatch warning immediately, even before recalculation. Recalculate the
route, or review and edit the existing mileage manually, before saving. In
manual-only mode, changing recorded text does not display a route-recalculation
warning because no Google route is available.
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

Payees are managed values. Transaction forms offer existing active payees and
support inline creation by typing a new name into the selector and pressing
Enter. Existing populated workbooks must match the frozen
[format-13 Sheets source contract](SHEETS_SOURCE_CONTRACT.md); older ledger
layouts and backup formats are unsupported. Validation preserves incompatible
workbooks. Use a supported workbook or restore a validated format-13 backup
into a new blank workbook; historical converters are retired.

Tags remain managed, profile-local values referenced by stable IDs from
transactions, mileage, mixed-use sources, schedules, and assets. Inline Tag
creation normalizes names and prevents duplicates. Format retirement preserves
existing accounting records, receipt files, and backup files.

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
