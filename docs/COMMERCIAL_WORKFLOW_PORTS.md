# Existing financial CSV, mixed-use receipts and Maps workflow ports

Issues [#359](https://github.com/Roklion/Project_Tabula_Rasa/issues/359),
[#361](https://github.com/Roklion/Project_Tabula_Rasa/issues/361) and
[#363](https://github.com/Roklion/Project_Tabula_Rasa/issues/363) extend EPIC
[#221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) within initiative
[#124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124). They port existing
supported actions without adding bookkeeping formats or changing authority.
They remain outside [#288](https://github.com/Roklion/Project_Tabula_Rasa/issues/288)'s default technical-alpha matrix. The owner's [#303](https://github.com/Roklion/Project_Tabula_Rasa/issues/303)
readiness record consumes the delivering revision's validation and configured
dependencies before live use; implementation does not authorize migration,
provider changes, deployment, or commercial activation under #298/#224.

## Financial CSV actions (#359)

Transactions offers **Export selected**. Checkboxes select logical entries only;
selecting a journal includes its parent and every ordered posting. Downloads
retain the visible selected-entry order. Changing filters/search/sort or the
displayed identity set clears the selection. The API freshly checks all requested
IDs against the structured filter scope and refuses a missing/filtered/deleted
entry as a whole, rather than returning a partial file. No selections means
the button is disabled; a direct empty API selection returns headings.

Data & backup offers **Download transactions CSV** and **Download journal
postings CSV**, covering the selected business's complete financial ledger,
including inactive reference labels. Mileage remains in its own CSV. Full
transactions include transfers without converting them into income or expenses.

| Existing action | Ordered fields and empty behavior |
| --- | --- |
| Export selected | Date, Type, Account, To account, Category, Payee, Amount, Tags, Description, Receipt, Reference, ID. When journals are present, Debit and Credit follow Amount; posting amounts appear only in their side column. Empty selection returns the ordinary headings. |
| Download transactions CSV | ID, Date, Type, Account, To account, Category, Payee, Description, Reference, Amount, Tags. No journal or mileage rows; empty ledger returns these headings. |
| Download journal postings CSV | Entry ID, Date, Memo, Posting ID, Position, Account type, Account ID, Account, Debit, Credit, Payee, Description. One row per ordered posting; empty ledger returns these headings. |

Full exports retain existing leaf account/category names; selected exports retain
hierarchical display paths, mixed-use/recurring labels and receipt indicators.
Existing numeric presentation is preserved, including signed values and blank
opposite-side cells. UTF-8 CSV quoting preserves commas, quotes and multiline
text. Formula-leading text receives an apostrophe; numeric cells keep their
signs. Downloads neither mutate stored values nor require a DocumentStore.

The three read-capability endpoints are `GET .../exports/transactions.csv`,
`GET .../exports/journal-postings.csv` and `GET .../ledger/selected.csv` beneath
`/api/v1/entities/{entity_id}`. The last accepts repeated `entry_ids` and the
existing structured ledger filters. Responses are private, uncached attachments;
failed reads show safe errors and never manufacture a file. Scope/navigation
changes abort delivery of a pending browser download.

Standalone report downloads and category-template import are excluded by the
owner's October 11 correction. Complete recovery export remains #260; customer
portability remains #345 under #224. These CSVs are not alternate live ledgers.

## Mixed-use source receipts (#361)

Choose **Receipts** on a saved mixed-use source detail. The ordinary receipt
screen owns the common file validation, stable upload IDs, upload/link progress,
download, reference-only removal and unreferenced-file recovery controls.
Mixed-use endpoints bind that workflow to the source owner. Source and financial
projection read one native link set; generic transaction endpoints refuse
source-owned mutations. Recurring templates have no receipts. Generated
occurrences own independent source receipts. Acquisition receipts stay with
their ordinary acquisition transaction; depreciation has no parallel workflow.

`GET .../mixed-use/{record_id}/receipts` lists metadata. `POST` accepts
`document_id` and the loaded source `baseline`; `DELETE .../receipts/{document_id}`
accepts the baseline. The native repository locks and validates the complete
source/projection pair before metadata/link writes. Confirmed responses return
the source with its advanced baseline, allowing the next file in a batch to use
that confirmed token. Background reads never replace the original loaded token.

A stale source stops further batch uploads. Pending files and confirmed uploads
remain available; **Review latest source** / **Reload source** explicitly accepts
the latest saved source before **Retry unresolved receipts**. Retry after a
confirmed upload sends only the link. Storage owns one bounded uncertain-upload
readback and safe retry; the browser never retries mutations automatically.
Removing a reference leaves bytes recoverable. No simulated rollback deletes
an uploaded file after a failed link.

Native documents validate opaque provider locators at their metadata boundary.
Financial source edits preserve the native link set while shared domain
preparation validates financial terms. The frozen Sheets/backup Drive-reference
decoder remains unchanged. Entity-qualified requests, capabilities, Origin/CSRF,
original profile grants and managed receipt-folder bindings remain enforced.

## Optional Maps mileage (#363)

With separately restricted deployment-wide keys, Mileage offers **Starting
location lookup** and **Destination lookup** alongside editable recorded-text
fields. Choosing a suggestion supplies transient Place IDs. **Calculate mileage**
returns the primary driving distance; round trips call each direction separately.
The browser displays Google Maps attribution, provisional editable distances,
and an explicit **I reviewed the recorded locations and mileage** confirmation.
Changing recorded terms clears that confirmation. **Save mileage trip** alone
persists confirmed user records; lookup IDs, raw responses and route suggestions
are absent from the persistence payload.

Changing a lookup clears its selected Place ID and unchanged calculated drafts;
manually edited values survive. Manual entry remains available with unconfigured
Maps, failed lookup, quota exhaustion, unavailable provider or no usable route.
A successful outbound with failed return remains visible with clear manual-return
guidance. Return distance is independently editable. Protected edit/delete
baselines and mileage's separation from financial transactions remain unchanged.

`GET .../mileage/maps` returns only the browser key, availability and optional
region. `POST .../mileage/routes` accepts two selected Place IDs and `round_trip`;
it returns transient distances and a safe failure code without writing records.
Both enforce selected-entity context; route requests require write capability,
Origin and CSRF. Routes keys and human OAuth tokens never enter these DTOs.

The shared runtime accepts `TABULA_RASA_MAPS_BROWSER_API_KEY`,
`TABULA_RASA_MAPS_ROUTES_API_KEY`, `TABULA_RASA_MAPS_ROUTES_TIMEOUT_SECONDS`
(default 15) and optional two-letter `TABULA_RASA_MAPS_REGION_CODE`. A migrated
runtime instead consumes the trusted app-wide `google_maps` table, including
existing `autocomplete_region_code`. Equal browser/server keys suppress browser
exposure. No profile-specific key fallback or Maps quota-grant reuse is added.

Follow [Google Maps setup](GOOGLE_MAPS.md#commercial-browserapi-configuration-363)
before enabling provider requests. #133 owns deployment restriction verification:
use exact website/API restrictions for the browser key and a Routes-only server
key with stable-egress IP restriction when available, or the explicitly accepted
quota/monitoring alternative. Provider configuration, rotation and a controlled
non-sensitive live request remain operator work; synthetic tests prove none of
those hosted conditions.

## Reuse and verification evidence for #288 / #303

Local implementation validation on October 13, 2026: 286 affected Python tests
passed against disposable PostgreSQL; all five new compiled-browser journeys
passed; 24 Vitest tests, Python lint, ESLint, TypeScript/Vite build and generated
OpenAPI/client consistency checks passed. These results cover the implementation
revision carrying this document. Hosted CI, restricted-key/provider acceptance
and selected live-profile readiness remain unclaimed.

Reuse: inspected internal `transactions/ledger.py`, `ledger_bulk.py`,
`data_backup/exports.py`, `ledger_records.py`, `ledger_presentation.py` and
ReportingService. Extracted only shared CSV preparation and type labels; internal
and HTTP adapters now call the same owner. ReceiptService, receipt_context,
DocumentStore, native receipt/source locks and the common browser receipt screen
own attachment behavior. Maps reuses GoogleRoutesClient, deployment configuration
and MileageService; the browser adapts transient widget state. No parallel
accounting, persistence, authorization or automatic retry engine is introduced.

Regression evidence lives in `tests/test_financial_csv.py`,
`tests/http/test_financial_csv_transport.py`,
`tests/postgres/test_http_financial_csv.py`,
`tests/postgres/test_http_mixed_use_receipts.py`,
`tests/postgres/test_http_mileage_maps.py` and
`tests/postgres/test_browser_workflow_ports.py`. These use synthetic providers and
disposable PostgreSQL, including two entities, empty/populated exports, complete
journals, signs/text safety, stale source refusal, opaque locators, upload/link
uncertainty, preserved bytes, generated-source ownership, provider/quota failure,
route confirmation and independent return distance. Native browser journeys
exercise the compiled SPA and production handlers at desktop/mobile widths.

Run the affected service/provider/native suites, Python lint, browser build,
ESLint, Vitest and generated-contract drift check before committing. Current-head
GitHub **Full test suite** remains the authoritative merge gate after publication.
For #303, retain a reviewed revision and actual hosted workflow/Maps restriction/
grant-folder evidence for all selected live profiles; other remaining ports,
normal authentication, recovery acceptance and operator authorization retain
their own gates. Local checks do not complete #303 or retire Streamlit.

---

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
QuickBooks transactions and QuickBooks mileage. Preparation, preview and import
require the selected business's import grant (Owner, Admin or Accountant), in
addition to read/write access. Editor access alone does not expose uploaders.
The existing restricted synthetic development context also permits imports;
its loopback/hosted gate and prohibition on migrated profiles remain in force.
Staging a file does not write.
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
of their references. Journals support complete-entry selected export through #359; generic copy/bulk mutation is disabled. Mixed-use and depreciation
projections remain with their source owners.

`POST /transactions/{record_id}/copy-draft` accepts the loaded baseline. The
`POST /transactions/bulk/update` and `/bulk/delete` commands require the complete
selected ID set and one loaded baseline per ID. Duplicate/missing IDs, extra or
missing baselines, stale rows and protected sources reject the entire operation.
PostgreSQL bulk mutations are atomic, with no silent subset application. Failed
mutations invalidate affected cached views and preserve the complete submitted
selection/draft for review, even when refreshed data no longer contains a selected
row. Actions remain disabled after failure. Leave Bulk mode and load a fresh
selection before another attempt. Confirmed
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
They remain outside its completed default technical-alpha matrix. #359 financial CSV, #361 mixed-use receipts and #363 Maps lookup/routing are integrated above with their original service ownership. #158/#159 proposed bulk workflows are not migration prerequisites, and
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
