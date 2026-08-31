# Project Tabula Rasa — Design system

## Purpose and authority

This document is the durable user-interface and interaction specification for
Project Tabula Rasa. It defines the product character, visual tokens, layout
rules, reusable component behavior, responsive and accessibility requirements,
Streamlit constraints, page contracts, and objective UI acceptance criteria.

It is intentionally text-first. Screenshots are optional implementation
evidence; they do not replace the written contract.

Two kinds of authority must remain distinct:

- **Current-state authority:** When the question is what the application
  actually does now, the implementation and maintained tests are evidence of
  current behavior.
- **Intended UI authority:** When the question is what UI or interaction is
  intended, the active task requirements and this document are the durable
  design contract.

When code, tests, documentation, and this design disagree, identify the
discrepancy and reconcile it intentionally. Do not silently redefine intended
design because code drifted, and do not change runtime behavior as part of a
documentation-only cleanup.

The current application is a private, Google Sheets-backed bookkeeping tool
for one person or a small group of businesses. The active ledger remains
Google Sheets-backed. Architecture, setup, usage, and recovery detail belongs
in [Architecture](docs/ARCHITECTURE.md), [Setup](docs/SETUP.md),
[Using Tabula Rasa](docs/USING_TABULA_RASA.md), and
[Backup and recovery](docs/BACKUP_RECOVERY.md); this file should specify UI
intent rather than duplicate those guides.

## Product character

The interface should feel professional, calm, precise, trustworthy,
financially literate, operational, efficient, and purpose-built. It should
not feel like a marketing site, consumer-banking promotion, cryptocurrency
dashboard, gamified budgeting product, generic admin template, or decorative
spreadsheet. It must remain comfortable during extended bookkeeping sessions.

## Design principles

### Information before decoration

Financial data, bookkeeping state, required actions, warnings, and recovery
information take priority over ornament.

### Dense but readable

Use space efficiently for tables, filters, forms, navigation, financial rows,
validation summaries, backups, and imports. Use larger spacing only between
major information groups.

### Tables are primary

Transactions, mileage, accounts, categories, reports, and profile summaries
are core work surfaces. Charts support interpretation and must not become
decoration.

### One dominant action per workflow

Each independent form, tab, expander, or workflow section normally has one
obvious primary action. A multipurpose page may still contain several
independent workflows and must not hide valid secondary actions.

### Semantic, non-exclusive color

Use color for state, direction, risk, completion, selection, and attention.
Use text, signs, icons, or explicit messages as well; color is never the only
state indicator. Blue is the default interaction color, not a financial-gain
indicator.

### No hover-only behavior

Important actions, values, warnings, and states must remain visible or
keyboard-accessible without hover.

### Native Streamlit first

Prefer native Streamlit controls. Use custom CSS, HTML, or components only
when the benefit is substantial and maintainable.

### Safe actions are explicit

Destructive or consequential actions must state what changes before execution.
This includes permanent deletion, receipt-reference removal, credential
rotation, Drive disconnection, storage-root changes, imports, and backup
creation or upload.

### Profile context is always visible

The selected business and workbook context remain discoverable. Every
profile-sensitive read, write, import, export, receipt action, backup, cache,
selection, and prepared snapshot is scoped to that business.

## Visual tokens

### Color

| Token | Value | Use |
| --- | --- | --- |
| canvas | #F5F4F0 | Warm application background |
| surface-primary | #FFFFFF | Tables, forms, cards, and dialogs |
| surface-secondary | #FAFAF8 | Secondary grouped controls |
| surface-hover | #F2F3F4 | Row and control hover |
| surface-selected | #EAF0FC | Selected rows and active navigation |
| text-primary | #202124 | Main text and financial values |
| text-secondary | #62666B | Supporting descriptions |
| text-muted | #85898E | Timestamps and tertiary metadata |
| border-default | #DDDED9 | Standard boundaries |
| border-subtle | #E9E9E5 | Table separators |
| border-strong | #B8BAB6 | Focused or emphasized boundaries |
| interactive-primary | #3267D6 | Primary actions, links, selection |
| interactive-hover | #2858BC | Primary hover |
| interactive-focus | #6B96ED | Focus rings |
| success | #287A4B on #EAF5EE | Confirmed completion and healthy state |
| error | #B33A3A on #FBECEC | Failed or invalid state |
| warning | #996600 on #FFF5D9 | Attention and incomplete state |
| neutral | #62666B on #F1F2F1 | Pending or disabled state |

Use green for confirmed success, balance, and favorable movement; red for
errors, adverse movement, invalid state, and destructive actions; amber for
duplicates, incomplete setup, out-of-balance state, and review conditions;
blue for links, navigation, selection, primary actions, and information; and
neutral gray for pending or inactive context. Do not make every save button
green or every ledger amount colored.

### Financial values

Direction must remain clear without color:

```text
+$1,250.00
−$420.00
$0.00
```

Use a plus sign when positive direction matters, a consistent minus sign,
tabular numerals, and consistent currency precision. Right-align comparable
amount and balance columns. Ordinary ledger amounts normally use neutral text
because their meaning depends on account context. A negative balance is not
automatically an error; normal liability and equity stored signs are not
errors.

### Typography

Use a system sans-serif stack:

```css
font-family:
  Inter,
  ui-sans-serif,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  sans-serif;
```

| Role | Size | Weight |
| --- | ---: | ---: |
| Application title | 24px | 600 |
| Page title | 22px | 600 |
| Section title | 16px | 600 |
| Card title | 14px | 600 |
| Body and controls | 14px | 400 |
| Table text | 13–14px | 400 |
| Secondary text | 12px | 400 |
| Major metric | 26–32px | 600 |

Use tabular numerals for financial figures where supported. UI writing is
direct, specific, concise, consistent, and action-oriented. Prefer Save
transaction over Submit and an explicit duplicate count over vague success.

### Spacing, geometry, and elevation

Use a 4px base grid with approved values 4, 8, 12, 16, 20, 24, 32, and 40px.
Use 36–44px table rows, compact filter controls, 12–16px metric-card
padding, and 16px primary surface padding. Keep related controls 8–12px
apart and major groups 24–32px apart.

Use moderate corner radii, thin borders, subtle dividers, and restrained
shadows only where hierarchy benefits. Do not use gradients, glassmorphism,
heavy cell borders, saturated alternating rows, or rounded cards for every
block.

## Charts and metric cards

Charts are quiet, readable, and subordinate to the values they explain. Use
lines for trends, bars for period comparisons, horizontal bars for category
ranking, and stacked bars only when composition matters. Avoid 3D charts,
rainbow palettes, and charts that repeat a visible metric without adding
meaning.

Every chart has a clear title, scope, units, readable axes, limited gridlines,
and visible values or a useful tooltip. A typical chart is 220–320px high and
must render safely for empty and single-point data. Use blue as the primary
series and related muted tones for neutral categories; semantic colors are for
semantic series, not decoration.

Metric groups use a short label, primary value, and optional comparison or
context. Support normal, positive, negative, warning, loading, and unavailable
states. Unavailable data is shown as an em dash rather than zero unless the
value is truly zero. Do not put every metric in a heavily bordered card.

## Application shell

The shell uses the Project Tabula Rasa identity in the page title, sign-in
surface, sidebar, and documentation. The authenticated sidebar is ordered:

1. Dashboard
2. Transactions
3. Mileage
4. Accounts
5. Categories
6. Reports
7. Data & backup
8. Account settings, only when local loopback administration is enabled
9. Log out in the utility area

Require application-password authentication before any ledger page or workbook
data is visible. Show the business selector when profiles exist and the
selected workbook title on ordinary pages. The current password grants access
to every configured profile; the shell must not imply per-profile user
authorization.

Account settings is visually separated from operational navigation and is
available only when the local administration flag and loopback binding pass.
It is a settings surface, not a user-identity or permission-management page.
The login surface uses the keyed native login_surface container so its readable
desktop width does not depend on an undocumented Streamlit test ID.

When the profile changes, keep the new business and workbook visible and clear
or rebuild page-local filters, selections, edit targets, widget generations,
and pending notices. Never initialize or access another profile's storage
under the new selection.

## Page headers, workflow groups, and messages

Page headers state the page purpose and place its primary workflow actions
near the relevant content. Use tabs for current workflow divisions:

- Transactions: Add transaction and View & edit ledger
- Mileage: Add trip and View & edit mileage log

Use bordered containers or expanders for dense independent workflows such as
edit forms, imports, profile administration, and backup controls. Do not move
long previews or multi-part recovery workflows into cramped dialogs.

Messages identify what happened, whether data changed, and what to do next.
Use informational blue, warning amber, error red, and confirmed-success green
with meaningful text. Do not show a success message before the relevant
Google API or storage operation confirms the write. Ordinary errors must not
expose secrets, tokens, private keys, private ledger data, receipt contents,
or raw stack traces.

## Tables and generic filters

Tables use compact rows, clear headers, subtle separators, restrained hover,
clear selection, and sticky headers where feasible. Dates and descriptions are
left-aligned; amounts, balances, and counts are right-aligned. Preserve stable
record-ID mapping and keep a reliable explicit selector inside edit workflows.
Do not hide important accounting fields solely to avoid narrow-screen
scrolling.

Generic filters use explicit labels, AND semantics, visible scope, and a
clear path back to the unfiltered state. Changing result scope clears
incompatible row selections. Exact control order and field meaning belong in
the relevant page contract below.

## Forms, buttons, and destructive actions

Use one column for sequential decisions and two columns only for clearly
related desktop fields. Keep labels visible, helper text concise, tab order
logical, and validation near the workflow. Stack related columns on narrow
screens.

Blue is the normal primary action. Neutral styling is for alternatives and
read-only checks. Red is for permanent deletion or an equally destructive
operation. Amber may call attention to a review or retry action. Disabled
actions remain legible and explain why they are unavailable.

Permanent deletion confirmations name the record, state that deletion is
permanent and cannot be undone, and require explicit acknowledgement. Receipt
reference removal must state that the ledger reference changes while the Drive
file remains.

## Receipts as a cross-cutting interaction

Receipts are managed within the selected saved transaction's workflow. When
Drive is unavailable, show a clear setup message and do not display
nonfunctional upload controls.

Supported files are PDF, PNG, JPG, JPEG, WEBP, and HEIC. Every selected file
is validated before upload; each is non-empty and no larger than 20 MB, and a
batch is no larger than 200 MB. Preserve a recognizable sanitized filename,
suffix conflicts numerically, and store stable identity, size, and SHA-256
metadata.

Show linked files with an open-in-Drive link, Remove receipt action, and the
consequence that only the ledger reference is removed. The unreferenced
workflow can link an eligible app-managed file without renaming it. Integrity
metadata warnings remain visible.

Receipt-on-create is an ordered workflow: validate fields and files, save the
transaction, upload files, and link each result independently. A confirmed
transaction is never reported as unsaved because receipt work failed. Partial
work keeps successful links, reports complete and unresolved counts, and
offers retry only for unresolved work. An uploaded-but-unlinked file is
retried by its existing identity, not blindly uploaded again. The editor
retains multi-file upload, retry, cancel recovery, recovery-check, unlink, and
unreferenced-link behavior.

The interface reports the concise outcome and next action; it does not expose
an internal pending/uploaded/linked/failed state machine as a separate product
surface.

## Imports as a cross-cutting interaction

The Data & backup page keeps Tabula Rasa CSV, QuickBooks transactions, and
QuickBooks mileage as separate uploaders. Parsing, preview, diagnostics,
duplicate detection, and proposed account/category creation are read-only.
Explicit import actions perform the confirmed batch write.

Preview states must clearly distinguish ready, duplicate, skipped, conversion,
validation, and storage failures. Imports use the selected profile and validate
references again before writing. No partial import is claimed after a failure.

### Import page contract

The Tabula Rasa CSV workflow requires Date, Type, Amount, Account, and
Category, accepts Payee, Description, and Reference, previews up to 20 rows,
and imports Income or Expense rows only. It does not import transfers.

QuickBooks transaction sources are Transaction Detail by Account CSV and
Self-Employed General ledger XLSX or its supported ZIP. Its preview retains
ready, duplicate, Income, Expense, Transfer, conversion-error, and
validation-error counts; duplicate and error row numbers; up to 50 source
rows; optional account/category auto-create proposals; and an explicit Import
validated rows action. Duplicates are skipped and valid rows are written in
one confirmed batch after references are checked again.

QuickBooks mileage retains ready, duplicate, Personal, Unreviewed, and
validation-error counts; row numbers and details; up to 50 source rows; and an
explicit Import validated mileage action. Only valid unique Business rows are
written. The three uploaders have separate staged state and never write during
preview.

## Responsive behavior

The application is desktop-first but remains usable at narrower widths. At
approximately 760px and below:

- multi-column forms stack;
- metric cards wrap;
- dashboard sections stack by priority;
- sidebar navigation may collapse;
- tables may scroll horizontally; and
- secondary actions may move below the primary action.

The priority order is page title and primary action, primary financial summary,
attention items, supporting metrics, main table or chart, and secondary
details. There must be no control overlap or unintended page-level horizontal
overflow. Intentional table scrolling is acceptable. Do not silently omit
important accounting columns.

## Accessibility

All pages require keyboard navigation, visible focus, explicit labels,
sufficient contrast, non-color state indicators, descriptive button text,
predictable control order, and accessible error messages. Do not remove focus
outlines without an equivalent replacement. Icons are never the only
representation of delete, edit, warning, success, financial direction,
active/inactive, or balanced/out-of-balance state. Avoid nonessential motion.

## Streamlit constraints

Prefer the following mappings:

| Need | Preferred control |
| --- | --- |
| Text | st.text_input or st.text_area |
| Amount, miles | st.number_input |
| Date | st.date_input |
| Single choice | st.selectbox |
| Account filter | st.multiselect |
| Transaction type | st.segmented_control |
| Boolean or acknowledgement | st.checkbox or st.toggle |
| Upload | st.file_uploader |
| Submission | st.form and st.form_submit_button |
| Read-only selectable table | st.dataframe with selection |
| Edit/Bulk mode | segmented control or toggle with explicit labels |
| Export | st.download_button |
| Status | st.success, st.warning, st.error, or st.info |
| Metric | st.metric |
| Chart | st.plotly_chart |

Avoid replacing native controls solely for styling. Large prepared exports
should not be regenerated on every rerun. Show their preparation timestamp,
change Prepare to Refresh when a set exists, and invalidate a set after a
confirmed workbook write.

## Page contracts

The page contracts below are the canonical location for exact control order,
fields, table schemas, and current UI acceptance criteria. Generic sections
above define reusable rules and do not repeat these details.

### Authentication and global shell

#### Required behavior

- Require application-password authentication before ledger access.
- Display the business selector when profiles exist.
- Display the selected workbook title on normal pages.
- Scope all operations to the selected profile.
- Preserve Log out on every normal page.
- Expose Account settings only under current local-administration safety
  conditions.

#### Acceptance criteria

No ledger page is visible before authentication. The active business and
workbook are discoverable. Authenticated users are not told that the password
restricts them to one profile.

### Dashboard

#### Purpose and content

Show Total balance, Income this month, Expenses this month, Net this month,
recent activity, and account balances using the latest confirmed Sheets state.
Recent activity retains Date, Type, Payee, Category, Account, and Amount and
the current recent-activity limit. Account balances retain Account,
Classification, Type, and Balance.

#### Acceptance criteria

All four metrics and both tables remain present. Empty ledgers direct the user
to Transactions. Expense signs preserve current display semantics. Account
balances sit beside recent activity on wide screens and stack by priority on
narrow screens.

### Transactions

#### Purpose

Create income, expense, and transfer entries; optionally attach receipts;
filter, search, and review the ledger; edit or permanently delete saved
entries; perform approved bulk actions; and manage receipt references.

#### Add transaction contract

The form presents:

1. Transaction type: Income, Expense, or Transfer
2. Date
3. Category and Amount for Income or Expense
4. Amount for Transfer
5. From Account
6. To account for Transfer
7. Payee / customer and Reference
8. Description / memo
9. Receipt (optional)
10. Save transaction

Only active accounts are offered for new entries. Income and Expense require a
same-kind category; Transfer has no category and requires two different
active accounts. If no active account or matching category exists, show a
clear warning and do not present a misleading save path.

The receipt control accepts the supported multi-file batch. All transaction
and file validation completes before the Sheets write. On no-receipt save,
confirm the write and intentionally reset the form on the next rerun. On
receipt save, follow the ordered receipt sequence in the generic receipt
contract.

#### Ledger controls and table

Controls appear in this exact order:

1. From
2. To
3. Type
4. Accounts
5. Search transactions
6. conditional Clear search
7. Edit/Bulk mode immediately before the table

The table columns, in exact order, are Date, Type, Account, To account,
Category, Payee, Description, Amount, Receipt, Reference, and ID. To account
is blank for non-transfers, Category is blank for transfers, Receipt indicates
one or more linked receipts, and ID remains accessible for disambiguation.

The ledger defaults to latest-date-first and Edit mode. The table does not
begin with a visibly preselected row. When the edit section opens, its
selector targets the first visible transaction. A selected visible row or the
selector changes the edit target. If the current target is filtered out, it
moves to the first visible row or clears when none remain.

Search is a trimmed, case-insensitive substring match applied after the
structured filters. It searches Type, Account, To account, Category, Payee,
Description, Reference, and ID. It does not search dates, amounts, receipt
contents, receipt filenames, or hidden Drive metadata. Show result count,
conditional clear, and a distinct no-results state. Whitespace-only text is
equivalent to cleared search.

Filters and search persist across Add transaction / View & edit ledger and
across Edit/Bulk changes. Changing a filter or search clears bulk selection.
Changing mode also clears incompatible selection and recreates the dataframe,
so the native client-side sort resets to latest-date-first. The design does
not promise to preserve client-side sort across that recreation. Interactive
sorting may persist while the same widget remains mounted, including across
the two Transactions tabs. Navigation away and back resets the table
generation and latest-date-first ordering.

#### Bulk behavior

Bulk mode is explicit and selects only visible rows. It shows the selection
count and only these actions:

- **Export selected:** downloads selected visible ledger columns without a
  workbook change.
- **Change category:** available only for a homogeneous Income or Expense
  selection and restricted to categories of that kind.
- **Permanently delete selected:** shows count and aggregate absolute amount,
  requires acknowledgement, removes selected ledger rows, and retains linked
  Drive files as unreferenced files.

Bulk actions revalidate all selected stable IDs immediately before one batch
write and never silently partially apply. Transfers and mixed Income/Expense
selections cannot use Change category. Bulk changes are not available for
dates, amounts, payees, descriptions, references, accounts, transfers, or
receipts.

Bulk category changes and deletions use one Google Sheets
[spreadsheets.batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)
request per mutation. The complete request is validated before application.
An uncertain response is followed by a fresh stable-ID read and classified;
the application never blindly retries an ambiguous mutation.

#### Edit, delete, and receipt acceptance

Preserve type-specific editing of source and destination accounts, category,
date, amount, payee, reference, and description. Transfer accounts remain
different, and inactive accounts already referenced by a selected historical
transaction remain available where currently supported. Single deletion has
the same permanent warning and acknowledgement strength as bulk deletion.

The page must retain linked receipt opening, reference removal without file
deletion, multi-file editor upload, unresolved retry, cancel recovery,
recovery check, and unreferenced receipt linking.

#### Acceptance criteria

Create, edit, single delete, search, bulk actions, table columns, and receipt
operations remain discoverable. Success occurs only after confirmation.
Receipt-on-create partial failure never duplicates or discards a confirmed
transaction. Bulk mode cannot operate on rows outside the current visible
scope. Reconciliation and tags are not implied.

### Mileage

#### Purpose and fields

Record and maintain dated business mileage. Add trip preserves Trip date,
Vehicle, Business miles, Starting location, Destination, Round trip,
Business purpose, Notes, and Save mileage trip. Related fields may share
desktop rows: Trip date/Vehicle, Business miles/Round trip, and
Starting location/Destination.

The log presents From and To, Trips and Business miles metrics, filtered CSV
download, and the complete table with ID, Date, Miles, From, Destination,
Business purpose, Vehicle, and Notes. It provides single-row selection and an
Edit mileage trip section with all fields, save, and permanent delete.

When app-wide Google Maps configuration is available, Starting location and
Destination use a narrowly scoped address-autocomplete component with an
explicit manual-entry path. After two Google suggestions are selected, an
explicit Calculate mileage action requests the primary driving route and
populates an editable one-decimal suggestion. Changing either endpoint clears
the corresponding calculated state. Calculation errors preserve manual entry,
and Google-derived content keeps visible Google Maps attribution.

Round trip performs separate outbound and reversed return calculations and
shows independently editable mileage values. Saving creates the same two
independent records in one confirmed write, with each row receiving its own
confirmed mileage and a separate ID; there is no durable pairing. Recalculating
a saved row affects only that row. The filters, metrics, table, and CSV use the
same date scope. Without Maps configuration, the current manual workflow
remains available.

#### Acceptance criteria

Round-trip help remains visible. Create, edit, delete, filtering, totals, and
export remain available. Autocomplete remains keyboard and narrow-layout
usable, manual entry is always available, and ordinary reruns do not trigger
paid route requests. Mileage remains separate from financial transactions.

### Accounts

#### Purpose and table

Maintain balance-sheet accounts, classifications, opening balances, active
state, hierarchy, and calculated balances. The table retains Account, Layer,
Parent, Classification, Type, Active, Balance, and Transaction count.

Add and edit fields are Account name, Type (Bank, Cash, Credit card,
Short-term debt, Equity, or Other), balance-sheet Classification, Opening
balance, Parent account, and Active where applicable.

#### Rules

Layer 2 parents share the same classification. Fixed subtypes retain their
normal classification. A Layer 1 account with children cannot be moved under
another parent until its children are promoted or reparented. Parent rows
show rollup balance and count; child rows show direct values. Accounts are
deactivated rather than deleted so history remains valid.

#### Acceptance criteria

Stable IDs and transaction references survive rename, promotion, and
reparenting. Active/inactive state is text-backed. Liability and equity
opening-balance guidance remains visible. No Delete account action is added
without a storage-model change.

### Categories

Maintain Income and Expense categories and their two-layer hierarchy. The table
retains Category, Layer, Parent, Type, and Transaction count. Add/edit fields
are name, type, and optional parent.

A child uses a same-kind parent. A parent with children cannot itself be moved
under another parent until its children are handled. Rename, promotion, and
reparenting preserve the stable category ID. Permanent deletion requires no
transaction references and no child categories, a fresh check, and explicit
acknowledgement. Paths remain available in selectors and reports.

### Reports

#### Content and scopes

Use From and To for income-and-expense analytics and a separate As of date for
the balance sheet. Present, in order:

1. Report period controls;
2. Income, Expenses, and Net;
3. Monthly performance grouped bars;
4. Expenses by category horizontal ranking bars;
5. Category detail with Category, Layer, Parent, Direct activity, and Layer 1
   total;
6. Total assets, liabilities, and equity; and
7. Assets, Liabilities, and Equity tables, with Current earnings in Equity.

Current earnings are income minus expenses and are included in total equity.
Layer 1 totals and direct activity are explainable without double-counting.
Reports show text-backed balanced or out-of-balance status with the difference
for Assets = Liabilities + Equity. They communicate empty activity, empty
expense results, empty statement groups, and storage failures.

#### Acceptance criteria

Charts remain subordinate to reported values and resize within their columns.
No unsupported cash-flow, transaction-detail, or reconciliation report is
presented as current.

### Data & backup

#### Purpose and order

Provide cloud backup controls, recovery-configuration visibility, live exports,
and imports in this order:

1. Cloud backup
2. Recovery status
3. Exports
4. Imports

Cloud backup retains not-configured guidance, profile-scoped destination,
latest backup information, no-backup warning, Upload fresh backup now, and
Verify latest cloud backup. Verification is read-only and never implies
restore or live-workbook mutation.

Recovery status retains optional Synology guidance, invalid metadata warnings,
profile-root source, Receipts and Ledger Backups children, download-only
direction, destination-deletion protection, destination, schedule, retention,
and the explicit statement that the app does not configure or observe DSM.
An absent hosted/local record is reported as unavailable, not as healthy.

Exports retain one Prepare/Refresh workflow, preparation timestamp,
transactions CSV, mileage CSV, and a complete backup when receipt preparation
succeeds. CSV downloads remain available when the complete backup fails.
Prepared data is scoped to profile, configuration revision, and confirmed
workbook data revision.

Imports retain the three distinct workflows and all previews, diagnostics,
duplicate summaries, and explicit actions in the import contract above.

#### Acceptance criteria

Cloud upload, cloud verification, CSV exports, complete backup, all three
imports, and recovery status remain available. No local Drive Desktop
dependency is implied for cloud-native backup.

### Account settings

#### Purpose and availability

Account settings is the local administration home for business profiles,
credentials, Drive storage, recovery metadata, and hosted Secrets handoff. It
requires loopback-only availability and application-password reauthentication.
It is unavailable for writable administration in hosted environments.

Organize the surface as Business profiles, Google Drive storage, Recovery, and
Security & deployment information. The last section is informational except
for Generate hosted Secrets file, which creates a local handoff but cannot
write to or verify hosted Streamlit Secrets.

#### Business profiles

When no local profile exists, lead with profile creation and do not render
unrelated Drive or Synology controls. Preserve:

- profile summary with key, business, masked spreadsheet ID, local backup
  folder, service-account email, Drive state/account, Synology state/path,
  and configuration source;
- business name and immutable safe profile key;
- spreadsheet URL or ID;
- optional local backup folder;
- complete service-account JSON upload;
- Validate and save;
- workbook validation, required-sheet initialization, and default seeding;
- edit of business name, spreadsheet, and local backup folder; and
- separate replacement-key upload and Validate and rotate credential action.

Failed validation leaves the prior profile intact. Never display private keys,
refresh tokens, private ledger data, or receipt contents. Readiness performs
fresh workbook and configured-destination checks without walking ordinary
Drive parent folders.

#### Drive storage

Preserve profile-scoped Connect or reconnect, disconnect without deleting
Drive files, existing-root Picker selection or app-managed root creation,
Provision storage folders, and authorized-account/destination summaries.
Managed Receipts and Ledger Backups children are identified by stored IDs and
profile metadata rather than names alone.

#### Recovery

Preserve enable/disable, profile-root Cloud Sync summary, NAS destination,
schedule, retention, download-only direction, and destination-deletion
protection. Enabled records use layout profile-root automatically. Saving
these local metadata fields must not access Drive or verify DSM, and equivalent,
shared, or nested normalized NAS destinations are rejected.

Changing only local backup or Synology metadata does not change hosted Secrets.
Changing a Drive root while recovery is enabled is blocked until the recovery
record is disabled and saved.

#### Security and deployment

State that the application password grants access to every configured profile,
profile keys are configuration identifiers rather than users, local profile
storage is plaintext protected by the operating system, and hosted changes
require the documented export and replacement process. Generate hosted Secrets
reloads and validates profiles, uses an explicit allowlist, writes a new
ignored owner-only file without overwriting an existing one, and reports only
its path.

#### Acceptance criteria

All existing profile, credential, Drive, storage, recovery, readiness, and
hosted-export functions remain discoverable. The page does not imply
per-profile permissions, DSM monitoring, or in-app restore.

## Component contracts

### Date control

Use explicit labels such as From, To, Date, Trip date, or As of. Preserve the
scope. Reports As of is never combined with the income-and-expense range.

### Hierarchy selectors

Display full hierarchy paths where used, preserve stable IDs behind labels,
restrict category options by kind, and include inactive accounts only for
historical edit contexts where supported. Transfer destinations must differ
from the source.

### Currency input and output

Use two decimal places, a minimum of 0.01 for current transaction entry,
right-aligned displayed values, and the existing opening-balance sign
conventions.

### Selectable table

Map every displayed row to a stable ID, make selection clear, preserve an
explicit edit selector, and do not add multi-row selection outside the
approved Bulk transaction workflow.

### File upload

Show accepted types and preserve input after non-write validation errors where
possible. Distinguish parsing failure, validation failure, Drive upload
failure, and ledger-link failure. Never expose file contents or secrets in
diagnostics.

### Prepared exports

Avoid repeated large payload generation, show preparation time, use Refresh
when a set exists, and invalidate or separate the set after a confirmed
workbook write.

### Ledger search

Use the Search transactions label, the exact field scope above, structured
filter AND semantics, result count, clear action, no-results state, and the
same profile/table-generation reset behavior as the Transactions contract.

### Bulk action bar

Hide it without a selection, show count, expose only valid actions, keep
export secondary, and show category-change and deletion review summaries
before writing.

### Receipt-on-create

Treat save, upload, and link as ordered stages. Never report a confirmed
transaction as unsaved. On partial failure show its saved identity and retry
path. Do not reset the form until the selected workflow completes.

### Success notice

Use concise confirmed messages such as Transaction saved, Category updated for
12 transactions, Permanently deleted 3 transactions; linked Drive files were
retained, Imported 24 transactions, and Latest cloud backup downloaded and
verified. Do not show success before confirmation.

## Durable non-goals and prohibited patterns

The current design does not include reconciliation, transaction tags,
receipt-content search, cash-flow reports, per-profile user authorization, or
bulk changes beyond export, compatible category change, and permanent delete.
Do not add them as implied badges, controls, status fields, or backlog entries
in this design specification.

Do not introduce marketing hero sections, oversized headings, excessive
whitespace, gradients, glassmorphism, neon accents, decorative animation,
oversized pills, unexplained icon-only controls, colorful charts without
semantic purpose, hidden critical errors, generic confirmation language, or
irreversible actions without explicit confirmation.

When implementing a UI change, inspect the current page implementation and
the relevant canonical guide, preserve every current function, prefer native
Streamlit controls, and verify success and relevant failure paths at the
supported desktop and narrow viewports. This is an implementation discipline,
not a PR or agent-review procedure; repository review rules belong in
AGENTS.md and .gemini/styleguide.md.
