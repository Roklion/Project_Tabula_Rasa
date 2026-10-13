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
