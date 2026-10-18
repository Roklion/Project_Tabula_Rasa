# Commercial recurring, mixed-use and asset workflows

Issues [#284](https://github.com/Roklion/Project_Tabula_Rasa/issues/284) and
[#285](https://github.com/Roklion/Project_Tabula_Rasa/issues/285) extend
[EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221), under
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
They consume #277/#278/#280, the merged #248 recurring/mixed-use and #249 asset
repositories, and the core commercial workflows. This implementation builds on
merged PR #304 at `c8069ea6344eeacca8e84d33135204d3c8a0e9c5`, retaining its mileage,
receipt, browser-quality and protected-form integrations.

These are secondary coverage slices. They do not expand #288's default first
technical-alpha scope, establish #222 membership, implement #223's durable job
platform, retire Streamlit, execute #303 live migration or satisfy #298/#224's
commercial activation/recovery sign-off. Applicable owner workflow requirements
may consume them independently of the default alpha matrix.

The #329/#330 visual slice under #323 reuses shared fields, section headers,
detail summaries, action tones and named keyboard-scrollable tables. Related
fields align on desktop and stack on narrow screens; long labels and notes wrap,
and comparable amounts align with their headings. Source ownership, immutable
posted history and command consequences are explained beside their existing
controls. These presentation changes preserve the state and command contracts
below; [UI foundations](COMMERCIAL_UI_FOUNDATIONS.md#wave-2-forms-and-secondary-routes-329330)
records route coverage and synthetic evidence. Integrated acceptance remains
#331, independent of hosted #288 and identity/onboarding #314/#317.

List actions use **Manage** for writers opening Assets, Recurring or Mixed-use
details, which include protected editing and supported commands. Read-only users
see **View** and retain inspection without mutation controls. Row actions stay
visible during wide-table scrolling on desktop; names, amounts, secondary details
and compact text statuses have distinct visual roles without changing permissions.

## Recurring expenses

Transactions links to **Recurring expenses**. The schedule list shows cadence,
next due date, latest current occurrence, status, attention and stable identity.
Details show current occurrence IDs, dates, amounts and initial/generated roles,
including mixed-use source provenance.

**Add recurring expense** supports ordinary or mixed-use Expenses. Save invokes
the existing initial operation, committing the schedule and initial occurrence
together. Repeat every starts at one month; create identities and corrected
drafts survive failure. Templates contain managed references rather than receipts.
Schedule edits affect future occurrences; existing occurrences retain their
saved amounts and provenance. **Pause**, **Resume** and **End** require explicit
confirmation and the originally loaded baseline. End is permanent and retains
history. The application service has no permanent schedule-delete operation;
the browser/API does not invent one.

**Generate due occurrences** is an explicit, confirmed command with a cutoff
date. Its response reports confirmed generated and attention counts. Repeating
the action uses existing stable schedule/date identities and does not duplicate
occurrences. Listing schedules, loading details, visiting other pages and loading
the runtime never invoke reconciliation. This technical command is not a durable
scheduler itself. [Jobs operations](OPERATIONS_JOBS_AUDIT.md) owns #334's opt-in
durable authority: when enabled, this same explicit command queues bounded jobs
and reports queued schedules; the browser asks the user to refresh later.
Timer/explicit requests share the service/idempotency path. Cutoffs cannot exceed
the approved zone's current business date in worker mode. Existing synchronous
generation remains available when worker authority is disabled.

[Accounting periods](ACCOUNTING_PERIODS.md) defines #336's independent opt-in
month lock. Source, generated and import writes encounter the same transactional
boundary. Missing closed occurrences stop with attention and durable job failure;
an Owner unlock and eligible retry can recover without partial source pairs.

## Mixed-use sources and projections

Transactions links to **Mixed-use expenses**. The source log exposes total,
business-use percentage, allocated amount, rationale and linked projection.
Incomplete source/projection relationships remain visible for inspection with
editing/removal unavailable; normal commands do not silently repair them.

Create and edit use Expense references plus the allocation inputs. The live
**Ledger result** calls the existing service's Decimal allocation calculation;
the browser does not calculate financial results. Save creates or updates the
source and its existing projection as one source-owned operation. New sources
have distinct stable source/projection IDs. Protected deletion removes the pair,
subject to the service's reference rules. Generated sources show recurring
provenance. The generic ledger cannot mutate their projections independently.
Its derived rows link to Mixed-use expenses or Assets for source-owned actions;
mixed-use allocations are labeled **Mixed-use** in the ledger.

The commercial slice exposes source setup/edit/delete and recurring creation.
#361 adds **Receipts** on each source detail through the shared receipt workflow,
with the original source baseline required for linking/removing references.
Source and projection retain one receipt set; generic transaction receipt
endpoints refuse derived rows. Recurring templates do not own receipts; generated
sources own their own set. See [workflow ports](COMMERCIAL_WORKFLOW_PORTS.md) for
recovery, conflicts and validation. Independent source copy and ordinary Expense-to-recurring conversion are also available under #362; their preparation, baseline and recovery contracts are documented in the same workflow guide.

## Assets and depreciation

Assets offers a register, **Add asset**, detail and protected editing. Asset types
come from the service's canonical enumeration. Terms include acquisition/start
dates, cost, salvage, whole-quarter life, posting accounts and optional managed
references and acquisition linkage. Only straight-line depreciation is supported.

The server-calculated schedule displays amounts, cumulative depreciation, book
value, override reasons, Posted/Pending and durable ledger entry IDs. Viewing the
schedule never posts. **Post due depreciation** requires a cutoff and explicit
confirmation, returns the committed count/IDs and never retries automatically.
PostgreSQL commits all requested periods atomically; a later-period failure
leaves no partial posting. Repeating a confirmed action after a fresh load skips
already-posted periods.

Before posting, due/past period overrides require an amount and reason. The API
caps the requested as-of date at the server's current date so a browser clock
cannot make a future quarter eligible. Removing
the final override restores editable schedule terms. Saved overrides or postings
prevent permanent deletion; posted history locks terms, overrides and posting
accounts. Descriptive fields remain editable. Retirement requires confirmation,
preserves history and cannot precede posted periods. The service enforces these
rules even for callers that bypass disabled browser controls. Posted entries
retain depreciation provenance and cannot be independently rewritten by the
ordinary ledger editor.

## Protection and ownership

All reads and commands use server-resolved entity context. Unsafe requests retain
capability, Origin and CSRF checks. Edits, deletes, transitions, overrides and
posting submit the loaded baseline; missing/stale tokens fail without mutations.
Conflicts keep drafts and offer explicit Keep draft or Discard draft and reload.
Each detail visit waits for its fresh read before opening an editor, including
when cached data exists. Later background read failures preserve the loaded draft.
Commands require saved main-form changes before confirmation. A completed command
closes that editor's mutation surface; return to the list to load updated metadata.
Confirmed responses establish success. Failures retain drafts and invalidate the
affected private caches, with no automatic browser retry or success readback.

Reuse: existing application services and PostgreSQL repositories own rules and
mutations; `CreateEditor`, `ProtectedEditor`, fields, confirmations and scoped
query invalidation own form behavior. `ProtectedEditor` now also owns confirmed
source commands. Mileage and secondary detail routes share the fresh-read gate.
Read-only detail views reuse the same field presentation without
mutation controls. Asset detail reads assemble source/history together and use a
shared domain schedule annotation, also used by the internal renderer. New code
owns transport allowlists, responsive workflow presentation and representative
integration scenarios; it introduces no second accounting or retry owner.

## Validation

After building `web`, run affected checks from the repository root against a
disposable PostgreSQL database with `TABULA_RASA_TEST_DATABASE_URL` configured:

```powershell
python -m pytest tests/postgres/test_http_secondary.py tests/postgres/test_browser_secondary.py
```

Native browser coverage uses the compiled app, real API/services/PostgreSQL,
desktop/mobile Chromium, Firefox and WebKit, and independently loaded stale forms.
HTTP/repository coverage includes source/projection parity, atomic failure,
provenance, duplicate prevention, required baselines and two-entity isolation.
The existing [repository CI gate](DEVELOPMENT.md#authoritative-ci-and-required-check)
remains authoritative for the current PR candidate; these local checks do not
claim staging acceptance or hosted review completion.
