# Commercial import, copy and bulk workflows

Issues [#357](https://github.com/Roklion/Project_Tabula_Rasa/issues/357),
[#358](https://github.com/Roklion/Project_Tabula_Rasa/issues/358),
[#362](https://github.com/Roklion/Project_Tabula_Rasa/issues/362) and
[#364](https://github.com/Roklion/Project_Tabula_Rasa/issues/364) port existing
internal workflows under [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
The reference actions are Data & backup's three importers, Transactions' ordinary
copy/bulk actions, Mixed-use expenses' source copy and an ordinary Expense's
Make recurring action. These extend #282/#284/#286 through the existing services
and PostgreSQL repositories. They introduce no new input format or bookkeeping
capability.

## Imports in Data & backup

**Data & backup** (`/data`) has independent uploaders for Tabula Rasa transactions,
QuickBooks transactions and QuickBooks mileage. Staging a file does not write.
Source tables show at most 20 Tabula Rasa CSV rows or 50 QuickBooks rows.
Changing files/options invalidates their earlier preparation. An explicit import
action commits only the selected file to the selected business. Files are UTF-8
CSV or the supported workbook formats below, at most 25 MB and 1,000 source rows
per batch. Larger sources must be split. ZIP/XLSX expansion and worksheet size
are bounded before conversion. Headers must be unique and nonempty.

- **Tabula Rasa CSV:** Date, Type, Amount, Account and Category are required.
  Payee, Description and Reference are optional. Type is Income or Expense.
  Account/category names refer to existing compatible references; this format
  does not import Transfers or journals. Preparation shows source cells and file
  diagnostics, preserving the internal workflow's actual preview. Domain/reference
  validation happens on the explicit **Import rows** command.
- **QuickBooks transactions:** Transaction Detail by Account CSV, or
  Self-Employed General ledger XLSX with its `General Ledger` worksheet, or a ZIP
  containing exactly one such XLSX (excluding macOS metadata). Preview preserves
  Income/Expense/Transfer counts, ready/duplicate counts, duplicate row numbers,
  conversion and validation errors, and optional account/category proposals.
  Auto-created accounts use the existing inferred type/classification and zero
  opening balance; categories use the existing inferred Income/Expense kind.
  Correct all conversion/validation errors before **Import validated rows**.
- **QuickBooks mileage:** Download Trips CSV with the existing parser's Date,
  Type, Trip Purpose, Vehicle, Start Address, End Address and Distance aliases.
  **Preview mileage import** shows ready, duplicate, Personal, Unreviewed and
  validation counts with row diagnostics. Only unique valid Business trips are
  eligible; distances use the existing miles/kilometres conversion and one-decimal
  normalization. Errors disable **Import validated mileage**, which requires
  confirmation. Mileage never writes financial entries.
  Preview duplicates reflect current trips; the commit also checks durable import
  provenance, so its confirmed imported count may be lower after records changed
  between preview and submission.

Each accepted PostgreSQL import is atomic: transactions and any proposed
references, or mileage records and import provenance, commit together. A known
failed batch leaves no partial import. The repositories revalidate fresh entity
references/duplicates inside the mutation boundary and retain stable identity
and durable import provenance. An explicit repeat skips already imported rows,
including after an uncertain response; the browser never retries automatically.
CSV replay protection applies to the identical committed batch; it preserves the
existing per-row semantics rather than adding a new duplicate policy. QuickBooks
duplicate rows are skipped. A confirmed API result supplies the imported count and
IDs. An unavailable/lost response does not prove rollback: inspect the appropriate
ledger/log and refresh preparation before an explicit retry. Corrected drafts and
file selections survive failures; no fallback to Sheets is offered.

The transport accepts raw `application/octet-stream` bytes with the existing
Origin/CSRF and server-resolved entity checks:

| Command below `/api/v1/entities/{entity_id}` | Behavior |
| --- | --- |
| `POST /imports/csv/prepare` | Read-only source preparation |
| `POST /imports/csv` | Confirmed ordinary CSV batch |
| `POST /imports/quickbooks/preview?filename=...&auto_create=...` | Read-only conversion/domain preview |
| `POST /imports/quickbooks?filename=...&auto_create=...` | Confirmed QuickBooks transaction batch |
| `POST /imports/quickbooks-mileage/preview` | Read-only mileage preview |
| `POST /imports/quickbooks-mileage` | Confirmed mileage batch |

Raw provider exceptions, file contents and source values never enter request logs
or error envelopes. Authorized preview responses show the source and diagnostics
only to the selected business. No file is stored as an alternate live ledger.

## Ordinary copy and bulk actions

In **Transactions**, entering Bulk mode reloads transaction baselines and then
refreshes the visible ledger before enabling selection. A failed refresh leaves
selection unavailable; subsequent concurrent edits still reject as stale.
Explicitly select visible complete logical entries. Selection
stores each stable ID and its original loaded baseline; filter/search/sort changes
clear the selection. **Copy transaction** requires exactly one eligible ordinary
transaction. The service validates its current baseline and prepares an independent
draft with its date/fields, active Tag associations and exactly one `Copy From
<source ID>` memo suffix. Recopying removes older generated copy suffixes. Receipt
references and recurring ownership are excluded. Saving uses a new stable identity
and fresh references; later changes to the original do not rewrite the draft.
Cancelling an untouched prefilled copy still requires confirmation.

**Apply changes** permits only explicit Category, Payee and complete-set Tag
replacement. Category requires a homogeneous Income or Expense selection; mixed
kinds and Transfers cannot change Category. Untouched fields are omitted; clearing
Payee/Tags requires explicitly applying the field. **Permanently delete selected**
shows the count/amount and requires acknowledgement; receipt files survive removal
of their references. Journals allow selected export only when that separate #359
port is available; generic copy/bulk mutation is disabled. Mixed-use and depreciation
projections remain with their source owners.

`POST /transactions/{record_id}/copy-draft` accepts the loaded baseline. The
`POST /transactions/bulk/update` and `/bulk/delete` commands require the complete
selected ID set and one loaded baseline per ID. Duplicate/missing IDs, extra or
missing baselines, stale rows and protected sources reject the entire operation.
PostgreSQL bulk mutations are atomic, with no silent subset application. Failed
mutations invalidate affected cached views and preserve the complete submitted
selection/draft for review, even when refreshed data no longer contains a selected
row. Leave Bulk mode and load a fresh selection before another attempt. Confirmed
success closes Bulk mode and retains its result/count on the ledger; uncertainty
requires inspection before another command.

## Mixed-use source copy and Expense conversion

Choose **Copy mixed-use expense** on one complete source to open
`/mixed-use/{recordId}/copy`. The service prepares the source fields, active Tags
and `Copy From <source ID>` provenance; receipts and recurring linkage are excluded.
Saving creates new source/projection IDs together and normalizes allocation again.
An edit to the original after preparation does not change the independent copy.
The prefilled draft and cancellation use the shared create-editor safeguards.

Choose **Make recurring** on an eligible ordinary Expense to open
`/transactions/{recordId}/recurring`. The form loads a fresh Expense/baseline and
uses the existing ordinary Expense fields and recurring schedule cadence. It
creates the schedule and links the existing Expense as its initial occurrence in
one operation; it does not add a duplicate initial expense. Income, Transfers,
derived records and already-linked Expenses reject conversion. The original
baseline travels with **Confirm recurring conversion** through
`POST /recurring/from-transaction/{record_id}`. A stale original rejects the
operation. Stable schedule identity survives failed responses; uncertain status
retains the draft and requires inspection before retry/cancellation. Completed
commands close their mutation surface rather than offering another same create.
Existing receipt references on the converted Expense remain owned by that Expense.

## Initiative and readiness boundary

These four ports cover TA-1, TA-2, TA-6 and TA-8 of
[#288's transition inventory](TECHNICAL_ALPHA.md#feature-routing-and-authority-during-transition).
They remain outside its completed default technical-alpha matrix. #359 financial
CSV, #361 mixed-use receipts and #363 Maps lookup/routing retain their separate
owners. #158/#159 proposed bulk workflows are not migration prerequisites, and
#360 category-template import/standalone report downloads are excluded by the
initiative's corrected existing-functionality scope.

[#303's owner readiness record](https://github.com/Roklion/Project_Tabula_Rasa/issues/303)
requires all applicable existing workflows before live use across its three
selected profiles. This implementation supplies synthetic local workflow evidence;
the selected release's CI/reviews, authenticated deployment/bindings, three-profile
verification, recovery decisions and explicit live execution remain required.
It does not activate authority, retire Streamlit, complete the epic/initiative or
establish external beta/paid readiness.

## Reuse and validation

TransactionImportService, MileageService, TransactionService, MixedUseService and
RecurringService retain domain decisions; their existing PostgreSQL repositories
retain fresh checks, atomic writes, provenance and isolation. File preparation is
shared without importing Streamlit. A pure copy-suffix owner serves internal and
browser paths; ordinary/mixed-use copies share association filtering through
TransactionService. Existing fields, protected/create
editors, confirmations and scoped cache/context owners handle browser forms.
New code owns bounded transport preparation, allowlisted DTOs and presentation,
with no parallel persistence, authority, accounting or retry implementation.

Focused tests cover file conversion/rejection, service copy preparation,
API batches/baselines/duplicates/rollback/lost responses and two-entity isolation,
plus compiled-browser confirmation/cancellation, protected selections, failures,
independent copies, conversion and desktop/mobile import behavior. Run these from
the repository root with a built `web` and explicitly disposable
`TABULA_RASA_TEST_DATABASE_URL`; see [Development](DEVELOPMENT.md#required-validation).
GitHub's current-candidate **Full test suite** remains the authoritative merge gate.

Local validation recorded October 13, 2026: 221 affected Python tests, 44 browser
unit tests and 27 compiled-browser scenarios passed using a disposable PostgreSQL
18.6 instance. The browser scenarios cover each new port, desktop/mobile imports,
two entities, atomic/replay behavior, failure guidance, independent copy/cancellation,
protected selections and inline-reference conversion after a lost response.
Python Ruff, browser ESLint, TypeScript/build, API contract generation and
`git diff --check` passed. Separate reviewer-context passes found and verified
remediation for copy completion, selection lifetime, bulk outcome preservation,
import recovery and full-DTO conversion replay. These are local implementation
results, not hosted CI, stage acceptance or approval for #303's live execution.
