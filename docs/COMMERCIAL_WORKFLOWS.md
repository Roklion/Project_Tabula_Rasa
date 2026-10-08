# Commercial core bookkeeping workflows

Issues [#281](https://github.com/Roklion/Project_Tabula_Rasa/issues/281) and
[#282](https://github.com/Roklion/Project_Tabula_Rasa/issues/282) implement core
technical-alpha workflows in [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221),
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
They consume the #277/#278 foundation and #280 protected-edit contract.
This implementation branch starts from dependency PR #296 at `69d0533`;
integrate its final merged revision before publishing this dependent work.

## Business selection

The local development seed creates Alpha and Beta demonstration entities in the
disposable loopback database. **Select business** lists the development resolver's
server-configured choices. Switching requires **Keep current business** or
**Discard draft and switch**. A confirmed switch replaces the context, private
query cache, selections and drafts. Selection is disabled during a pending
bookkeeping mutation. Independent browser clients can select different businesses.

`GET /api/v1/entities` enumerates only resolver-supplied contexts and resolves
their names through the ledger service. `POST /api/v1/session/entity` requires
Origin/CSRF and write capability checks, permits only the explicit trusted
loopback development resolver, and sets an HttpOnly, SameSite=Strict selection
cookie. The cookie must identify one of its configured entities; tampering cannot
introduce another entity. Entity-qualified requests must agree with the resolved
context before service composition. Other injected resolvers retain their existing
selection/authorization ownership and cannot use this endpoint as a bypass.

This is functional technical-alpha context, not login or membership authorization.
#222 owns authenticated memberships and context selection. Hosted deployment and
staging acceptance remain #279/#288; beta/paid activation and operator recovery
agreements remain the separate initiative gates. No credentials, profile settings,
provider controls, schema migration or entity creation are exposed in the browser.

## Reference setup

Accounts, Categories, Payees and Tags expose **Add** links, labeled create forms
and tables. Accounts include type, classification, opening balance, parent and
status. Categories include kind and parent. Payees/tags show active/inactive status.
Creation, normalization, hierarchy/reference validation and persistence delegate
to the existing entity-scoped application services. Parent names are displayed
without treating table position or a display name as a mutation key.

Existing edits, removals and merges use the
[commercial concurrency contract](COMMERCIAL_CONCURRENCY.md). Accounts deactivate
rather than physically delete. Categories support guarded removal; the current
category service has no independent inactive flag. Payees/tags support rename,
active status, multi-source merge and the service's guarded remove/deactivate
result. Inactive historical references remain resolvable.

## Transactions and journals

**Transactions** shows the combined ledger with **Add transaction** and **Add
journal** actions. The standalone Journals page also links to journal creation.
Forms share field components with protected editors rather than introducing
parallel payload or bookkeeping implementations.

Simple creation offers Income, Expense and Transfer, local calendar date, amount,
active accounts, matching category, managed payee/tags, optional new payee/tag
names, memo and reference. Transfers clear the category; non-transfers clear the
destination account. New entries require the relevant setup before save is offered.
The service validates references again inside its mutation boundary and owns
inline reference creation. Receipt bytes and new attachments remain #283.

Journal creation starts with two posting rows. Each has a stable ID, account or
category target, debit/credit side, amount, optional payee and memo. Explicit add
and remove controls keep at least two editor rows. Changing target type clears
the previous typed target. Debit, credit and difference feedback uses integer
cents; save requires complete positive balanced rows. Application services remain
authoritative for balancing, reference validity and atomic parent/posting writes.
The commercial editor currently uses Side/Amount controls, consistent with its
#280 editor, rather than the internal edition's separate Debit/Credit inputs.

Create forms preserve drafts and stable transaction/journal identities through
errors, perform no automatic mutation retry and reset only after confirmed
success. Inline references, financial records and posting writes remain in the
existing PostgreSQL transaction. Successful creates advance draft identities;
an explicit retry after failure retains the original IDs. Inspect records after
an uncertain response before deciding how to proceed.

Protected edits/deletes retain their originally loaded baselines and conflict
review behavior. Opening an editor loads the complete service record and captures
its baseline; submission does not fetch a replacement token. Derived transactions
remain read-only in the ledger. Journals are complete mutable entries, with no
independently editable posting rows. Streamlit state/reruns are not involved.

## Ledger and reports

`GET .../ledger` delegates to `ReportingService.query_ledger`. Date boundaries are
inclusive. Type, account/category target and tag filters preserve the shared
service semantics, including either transfer account, whole-journal target
matching and OR-within-tag matching. The browser exposes From, To, Type, Accounts
and Tags, plus case-insensitive search of displayed text and journal posting text.
Search does not match amounts, dates or receipt contents. The initial view covers
all dates, newest first; **Clear filters** restores it.

The table resolves historical names and hierarchy paths, includes transfer
destinations, receipt counts, references and stable IDs, and groups journal
postings below their parent with Debit/Credit values. It scrolls within its region
on narrow screens; posting rows have no separate edit/delete action.

Dashboard and Reports use `GET .../reports/summary` over one fresh service snapshot.
`ReportingService` owns profit/loss, balance-sheet sections, hierarchy rollups,
current earnings, the accounting-equation difference and account balances.
The endpoint only projects these values into decimal-string DTOs. The browser
does not recompute accounting totals. Profit/loss uses the selected From/To
period; the balance sheet uses To as its as-of date. The separately labeled
**Current account balances · all dates** view includes inactive accounts and
opening balances. Transfers and mileage do not affect income or expenses.

Confirmed and uncertain mutations invalidate the selected context's reference,
entry, ledger and report queries. Loading, empty, validation, conflict and failure
states use the shared primitives. Pending editor loads replace ledger filters so
a quick interaction cannot accidentally change a similarly labeled list filter.

## Validation and remaining initiative work

Use the commands in [Commercial development](COMMERCIAL_WEB.md) and supply a
disposable `TABULA_RASA_TEST_DATABASE_URL` explicitly. Build the browser first:

```powershell
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
$env:TABULA_RASA_REQUIRE_BROWSER_TESTS = '1'
python -m pytest tests/http tests/postgres/test_http_workflows.py tests/postgres/test_browser_workflows.py tests/postgres/test_http_baselines.py tests/postgres/test_browser_baselines.py
```

Native tests cover reference setup, create/edit/delete, inline payee/tag creation,
invalid/foreign references, unchanged state after rejected writes, duplicate IDs,
inclusive filters, reporting, independent entity selection, original-token
conflicts, and desktop/mobile compiled forms. Synthetic screenshots may be saved
with `TABULA_RASA_WORKFLOW_SCREENSHOTS` pointing to an ignored artifact directory.
No live ledger or deployment credentials are used.

This does not close #253, #221 or #124 or certify staging/customer readiness.
Receipts (#283), recurring/mixed-use (#284), assets (#285), full mileage (#286),
wider accessibility/browser certification (#287) and staging alpha integration
(#288) retain their owners. Full report-catalog migration, bulk operations, copy
and imports are outside this core slice. Streamlit remains the reference/internal
edition while those release and retirement gates are completed.

Reuse map: inspected HTTP composition/DTOs, protected editors, loaded-form/cache
helpers, reference/transaction/journal/reporting services, PostgreSQL repositories,
internal renderers and the design contract. Extended transport DTOs/routes, existing
field renderers, scoped cache invalidation and native fixtures. New code owns
create-draft lifecycle, selection presentation and ledger/report presentation;
there is no parallel domain, persistence, concurrency or retry implementation.
