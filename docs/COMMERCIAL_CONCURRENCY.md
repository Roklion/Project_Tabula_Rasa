# Commercial loaded-record concurrency

[#280](https://github.com/Roklion/Project_Tabula_Rasa/issues/280) is Wave 2 of
[EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221), within
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It consumes the #277/#278 HTTP/browser foundation and the persistence-neutral
[baseline/transaction contract](POSTGRESQL_CONCURRENCY.md) from #253.
This commercial caller bridge enables #253's final verification without waiting
for the remaining #221 workflow tickets.

## Delivered boundary

Existing accounts, categories, payees, tags, simple transactions, advanced journals
and mileage trips can be edited through the compiled browser, API, application
services and PostgreSQL. Accounts deactivate rather than delete; active accounts use the confirmed Deactivate action. Inactive accounts may be reactivated through Active and Save changes. Parent choices contain compatible roots only; records with children must stay roots. Bookkeeping selectors offer active references and only the inactive associations retained by that loaded field/posting. Categories,
payees and tags retain fresh reference checks before removal. Payee/tag merges
require the target and every selected source baseline. Derived mixed-use and
depreciation transactions retain their source owner and have no generic editor.
Transaction edits preserve receipt links and immutable provenance; there is no
receipt metadata edit/delete UX here. Journal posting IDs remain stable. Changing a posting target type clears its
selected target; new or cleared targets explicitly show Choose target until
the user selects an account or category.

These narrow forms are available on Accounts, Categories, Transactions and
Mileage; Categories links to Payees/Tags and Transactions to Journals. Full
list/create/report/receipt workflows remain #281–#286. Streamlit behavior and
internal service compatibility remain unchanged. Real identity/memberships (#222),
hosted environments (#279), operations (#223), wider browser QA (#287), alpha
acceptance (#288) and production activation gates remain separate.

## Transport

Entity-qualified list responses used to initialize editors return each record's
opaque `baseline` from the same persisted snapshot as its values. This is the
existing neutral `v1` token, with no SQL/ORM representation. Clients retain it
without decoding or recomputing it. It never grants authorization or selects a
business; context, capability, Origin and CSRF checks remain prerequisites.

`PATCH /api/v1/entities/{entity_id}/{resource}/{record_id}` carries load metadata
separately from the declared editable DTO:

```json
{
  "baseline": "<original-loaded-token>",
  "changes": {"name": "Reviewed name", "active": true}
}
```

This example edits a payee/tag; each domain has its own generated changes schema.
Unknown fields, including any internal bypass, are rejected. Successful updates
return the saved record and its new baseline. Optional changes omitted from the
request retain the existing service behavior; DTO defaults never clear saved
parents or associations. `DELETE` at the same path accepts
`{"baseline":"<original-loaded-token>"}`. Accounts instead use
`POST .../accounts/{record_id}/deactivate` with that body. Confirmed responses are
authoritative; clients do not perform a success-verification read or retry saves.

`POST .../{payees|tags}/{record_id}/merge` takes the target as `record_id`:

```json
{
  "source_ids": ["source-one", "source-two"],
  "baselines": {
    "target": "<loaded-target-token>",
    "source-one": "<loaded-source-one-token>",
    "source-two": "<loaded-source-two-token>"
  }
}
```

The map contains exactly the target and selected sources. Missing/null/blank
required tokens return **422 `baseline_required`**. Malformed tokens or extra
merge baselines return **422 `baseline_invalid`**. A mismatched entity, record,
kind, incarnation or persisted version returns **409 `stale`**. Safe error
envelopes contain a request reference and never echo tokens, drafts or backend
exceptions. Existing mutation boundaries check tokens before related accounting,
reference or inline-tag writes. Handlers never manufacture a fresh expected token.

## Form lifecycle and recovery

`ProtectedEditor` extends `useLoadedForm` with one shared mutation/reload lifecycle;
thin domain adapters own fields and DTO mapping. Loaded identity/baseline metadata
is cloned separately from editable values. Rerenders, background reads and cache
invalidation cannot replace the draft or its baseline. Merge forms keep their
original target/source token map separately from editable selections. Existing
scope boundaries remount private state on session/entity/capability changes.

Errors preserve the draft and expose **Review latest record**, or **Reload** for
validation failures. The confirmation offers **Keep draft** and **Discard draft
and reload**. Only the latter replaces values and metadata together. Review the
latest values before saving again. If another client removed the record, reload
reports an error without converting the draft into a create. Successful saves
advance the baseline from the confirmed response. Delete/deactivate requires an
explicit acknowledgement, including payee/tag active-to-inactive saves. Cancelling keeps the draft; confirming uses its original baseline. Fixed account types constrain classification to the domain-required value and clear an incompatible parent when classification changes. Hierarchy roots retain their classification/kind while they have children; compatible subtype changes remain available. Transfer destination choices exclude the source and source changes clear an identical destination. Transaction kind changes clear an incompatible category; entering a new payee clears the selected payee and selecting an existing payee clears the new name. Dirty navigation/close keeps the keep/discard choice.
Uncertain failures invalidate private caches, preserve the draft and never retry
automatically.

## Validation

Set `TABULA_RASA_TEST_DATABASE_URL` explicitly to a disposable PostgreSQL
administrator endpoint using [PostgreSQL operations](POSTGRESQL.md#native-integration-tests).
Build the browser before running native form scenarios:

```powershell
python -m tabula_rasa.http.export_openapi --output contracts/http/openapi.json
npm --prefix web run api:generate
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
python -m playwright install chromium
$env:TABULA_RASA_REQUIRE_BROWSER_TESTS = '1'
python -m pytest tests/http tests/postgres/test_http_foundation.py tests/postgres/test_http_baselines.py tests/postgres/test_browser_baselines.py
```

HTTP tests use independently pooled clients: both load, one commits, and the
other's later edit/delete/deactivate and missing-token commands fail. Full database
snapshots prove failure leaves postings, associations, inline references and
versions unchanged. Coverage includes multi-source merges, two-entity isolation,
successful reloads and internal omission compatibility.

Native browser tests serve the compiled SPA through the real app factory, using
independent desktop/mobile contexts and synthetic PostgreSQL without intercepted
responses. They cover seven editors and both merge forms, retained drafts/tokens,
visible conflicts and reviewed resubmission. CI builds first and requires the
build and Chromium, so that gate cannot silently skip. Unbuilt Python-only
checkouts may skip browser cases. Fixtures own UUID test databases and ephemeral
loopback servers. These tests do not establish hosted activation or wider
cross-browser/device certification.

Reuse map: inspected foundation DTOs/handlers, client/cache/form helpers,
reference/accounting/mileage services, PostgreSQL adapters and internal UI behavior.
Reused baseline encoding, transactional checks, domain rules and scoped state.
Added transport adapters, declared domain fields and one form lifecycle; no parallel
bookkeeping, retry, identity, persistence or concurrency implementation.
