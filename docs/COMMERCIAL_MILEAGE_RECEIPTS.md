# Commercial mileage and receipt workflows

[#286](https://github.com/Roklion/Project_Tabula_Rasa/issues/286) and
[#283](https://github.com/Roklion/Project_Tabula_Rasa/issues/283) extend
[EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) within
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
They consume the HTTP/browser foundation, #280's loaded-record forms, #250's
mileage persistence and #233/#251's document service and metadata boundary.
This independently deployable slice does not close the epic, retire Streamlit,
provide #222 identity/membership, satisfy #288's alpha gate or authorize external
beta or commercial activation. Existing deployment/cutover gates still apply.

## Mileage

Open **Mileage** to view the business's log. Shared **View mileage log** /
**Add trip** route links show the current workflow with weight and an underline,
wrap on narrow screens and retain the dirty-navigation confirmation. Add trip
is visible only to writers; detail routes remain associated with the log.

**From**, **To** and **Filter by tags**
align compact date controls with the top of the multiline tags list on desktop
and stack on narrow screens. They use one inclusive date/tag scope for the table, trip count, business-mile total
and **Download filtered mileage CSV**. Multiple selected tags match any selected
tag. The log preserves date, distance, vehicle, both locations, purpose, notes,
tags and stable identity. Read-only users can inspect a trip; writers can edit it.
CSV export prefixes formula-leading text with an apostrophe so spreadsheet
applications treat it as literal text; the stored trip remains unchanged.

Related create/edit fields share Trip details, Route and purpose, and Tags
groups. They stack on narrow screens; purpose and notes are multiline controls.
Save mileage trip is the primary action and Back to records retains the draft
navigation guard. The log wraps long locations, purpose, notes and tags, aligns
distance headings/values, and scrolls within its named keyboard-focusable region.
Tag listboxes expose keyboard guidance and the full selected labels.
Download filtered mileage CSV has a 16px gap before the log table, keeping the
action separate from the table header on desktop and narrow layouts.

**Add trip** captures the existing application-service fields. **Round trip**
initializes an independently editable return distance and creates two independent
records with reversed locations in one database transaction. Selected and inline
tags apply to both records. The return appears first when timestamps match.
Distances are normalized by MileageService to one decimal place; dates, positive
distance, required locations/purpose, tag validity and inactive history remain
service/repository rules. Mileage never creates financial transactions.

The detail/editor route loads its original baseline separately from editable
values. Save and confirmed permanent deletion keep the
[existing conflict/reload contract](COMMERCIAL_CONCURRENCY.md). Background reads
cannot replace a loaded draft/token. A create with uncertain status keeps its
draft, disables another submission and directs the user to inspect the log;
neither creates nor edits retry automatically.

The browser provides manual location and distance entry. #364 adds the existing
QuickBooks Download Trips preview/import in **Data & backup**, documented in
[Commercial import, copy and bulk workflows](COMMERCIAL_WORKFLOW_PORTS.md).
Google Maps lookup/route calculation remain with #363; no provider credentials
or routing rules are added to the HTTP/persistence layer by this import port.

The entity-qualified transport provides:

- `GET /api/v1/entities/{entity_id}/mileage` with optional inclusive `start`/`end`;
- `GET .../mileage/{record_id}` for fresh detail and its baseline;
- `POST .../mileage` with declared fields, `round_trip` and optional `return_miles`,
  returning confirmed records and baselines;
- the existing protected `PATCH` and `DELETE` detail paths.

## Transaction receipts

Choose **Receipts** on a saved ordinary transaction; its accessible name includes
the full record description. The page shows linked files, filename/size/type/integrity inspection and same-origin downloads. Receipt
actions for source-owned mixed-use/depreciation rows remain with their respective
source workflows; this slice does not provide a generic bypass for those rows.

Linked receipts, attachment and unreferenced recovery share section headers and
consistent action controls. Full filenames wrap, metadata disclosure is keyboard
accessible, and unlink guidance states that stored bytes remain. Read-only access
is labeled and retains downloads; unavailable storage has a reload/availability
surface without an attachment control. Selected-file states and partial-failure
guidance remain visible alongside the existing upload/link progress.

Select supported PDF, PNG, JPG, JPEG, WEBP or HEIC files, then **Attach selected
receipts**. The complete selected batch is checked before any upload: nonempty
files, 20 MB per file, 200 MB per selection and at most 100 receipts per target.
The service also validates each upload and the repository enforces the reference
limit at every link mutation. An indeterminate progress indicator and phase text
identify uploading versus linking while controls are disabled.

Each selected file receives a stable portable ID before sending bytes. The
browser first uploads bytes, retains the confirmed document response, then links
its canonical ID. Confirmed links remain attached if another file fails.
An explicit upload retry reuses a freshly confirmed document with matching
canonical safe filename, type, size and checksum; filename normalization is shared
with storage adapters so reserved names also reconcile on retry. Conflicting reuse of its ID is rejected before
sending bytes. An unavailable inventory stops the upload for inspection/retry.
Overlapping HTTP uploads for the same business and document ID are refused with
a conflict while the first request is running; inspect the result before retrying.
The PostgreSQL guard coordinates API workers; it does not roll back remote files
or promise transactionality across storage providers.
Counts distinguish attached and unresolved work. **Retry unresolved receipts** reuses
the same ID/file after an upload failure, or retries only linking after a confirmed
upload. DocumentStore retains responsibility for bounded uncertain-upload
reconciliation. There are no automatic browser mutation retries. **Cancel recovery**
or leaving the page retains already uploaded files in **Unreferenced receipts**;
the unsaved-work guard protects pending selections during navigation.
Partial-transfer and cancellation notices distinguish confirmed uploaded files from selections without a
confirmed upload. Check **Unreferenced receipts** before selecting unconfirmed
files again; an uncertain upload may have stored bytes despite its failed response.

**Remove …** requires acknowledgement and removes only the relationship. The
file remains downloadable and can be linked again from **Unreferenced receipts**,
including to another eligible transaction. Failed links do not commit misleading
database metadata, and failed removes retain the relationship. There is no byte
deletion endpoint or simulated rollback of uploaded files.

The API exposes portable IDs and provenance, never provider locators, folders,
profile keys or open URLs:

- `PUT .../documents/{document_id}/content?filename=...` transfers raw
  `application/octet-stream` bytes using a prepared 32-character lowercase hex ID.
  Buffering is capped at the existing per-file limit. No multipart dependency or
  base64 expansion is required.
- `GET .../documents` lists recoverable unreferenced documents and the count
  requiring integrity metadata.
- `GET .../documents/{document_id}/content` resolves the ID in the authorized
  business and downloads bytes through DocumentStore, with attachment disposition,
  `nosniff` and private `no-store` caching.
- `GET .../transactions/{record_id}/receipts` lists linked metadata;
  `POST` at that path accepts only `document_id` to link;
  `DELETE .../receipts/{document_id}` unlinks it.

All routes use the existing server context, capabilities and unsafe-request
Origin/CSRF checks. IDs do not grant access. Ordinary receipt link/unlink contracts
are not loaded-baseline commands; their repository already performs fresh scoped
target/reference checks. They advance the affected transaction baseline, so a
previously loaded transaction editor cannot overwrite changed receipt links.
No document-metadata edit surface or new concurrency bypass is introduced.
Provider errors are translated to safe typed responses without raw exceptions,
filenames, content or credentials in logs/errors.

The selected runtime must supply the authorized DocumentStore and stable store
kind when composing services. Existing migrated profiles reuse the shared
[trusted authority/document binding](BOOKKEEPING_CUTOVER.md). Unconfigured storage
returns a visible availability state with upload controls absent; the default
synthetic runtime does not silently configure Drive or invent a byte provider.
Production object-store selection and retention policy remain separately owned.

## Verification

Use a disposable PostgreSQL test administrator endpoint as described in
[PostgreSQL development](POSTGRESQL.md#native-integration-tests). After regenerating
the contract and building `web`, run:

```powershell
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
$env:TABULA_RASA_REQUIRE_BROWSER_TESTS = '1'
python -m pytest tests/http tests/test_application_documents.py tests/test_mileage_service.py tests/postgres/test_http_mileage_documents.py tests/postgres/test_browser_mileage_documents.py tests/postgres/test_http_baselines.py tests/postgres/test_browser_baselines.py
```

Native tests exercise the compiled browser, real HTTP/service graph and UUID
PostgreSQL databases with a synthetic DocumentStore. They cover desktop/mobile
capture, round-trip/filter/export/detail/delete, loaded-baseline conflicts,
upload progress, partial link recovery without reupload, uncertain upload retry,
download, remove confirmation, relinking, validation, safe failures and two-entity
isolation. Hosted acceptance and real provider smoke testing remain distinct.

Reuse map: inspected MileageService and its adapter/internal forms, ReceiptService
and its recovery/DocumentStore contracts, PostgreSQL receipt targets, the existing
HTTP models/client, ProtectedEditor and the native browser harness. Extended these
owners with thin list/create/detail and canonical document transport adapters;
extracted the mileage field adapter from the old bookkeeping editor. Browser
receipt sequencing handles the HTTP calls while existing application/provider
contracts retain validation, persistence and uncertainty ownership. No parallel
domain, persistence, authorization or retry engine was introduced.
