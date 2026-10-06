# PostgreSQL development and operations

Issue [#244](https://github.com/Roklion/Project_Tabula_Rasa/issues/244) supplies
the opt-in database foundation for [EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
[ADR 0001](adr/0001-canonical-accounting-schema.md) owns the accounting model.
This foundation does not select a managed provider or activate a PostgreSQL
ledger. The Streamlit composition still uses Google Sheets, even if a database
URL is present. Installing only `requirements.txt` remains sufficient for it.

## Access and migration tools

Use synchronous **SQLAlchemy Core 2.0 + Psycopg 3**, with **Alembic** for
schema revisions. Core supplies bound SQL, connections and pooling without
an ORM domain model. Repository SQL and returned-row mapping belong to
`tabula_rasa/infrastructure/postgres/`; services retain the existing application
contracts and domain owners. An ORM session or SQL row must never become a
service parameter/result. See the [SQLAlchemy Core documentation](https://docs.sqlalchemy.org/en/20/core/)
and [Alembic connection-sharing recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).

Database dependencies are pinned separately in `requirements-postgres.txt`.
`requirements-dev.txt` includes them for tests. A future commercial deployment
must install both its application dependencies and this database file.

## Local setup

From the repository root with Python 3.12 and Docker running:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
docker compose -f compose.postgres.yml up -d --wait
$env:TABULA_DATABASE_URL = 'postgresql+psycopg://tabula_dev@127.0.0.1:55432/tabula_dev'
python -m tabula_rasa.infrastructure.postgres upgrade
python -m tabula_rasa.infrastructure.postgres current
python -m tabula_rasa.infrastructure.postgres health
```

The Compose service uses PostgreSQL 18.6, a named Docker volume, loopback-only
port 55432, and trust authentication for disposable development. Use a different
`TABULA_POSTGRES_PORT` if the port is occupied. Use synthetic bookkeeping data
here; real staging/production use authenticated roles and appropriate TLS.
The `.env.example` contains only synthetic configuration. Python does not
automatically load `.env`: supply process environment explicitly or through
your deployment's secret injection. Neither CLI output nor settings repr includes
the connection URL, username, password, SQL parameters, or private row contents.

`docker compose -f compose.postgres.yml down` stops the local service and keeps
the volume. `down --volumes` destroys its development data and should be used
only for an intentional local reset.

## Environment variables

| Variable | Meaning / default |
| --- | --- |
| `TABULA_DATABASE_URL` | Explicit target database. `postgresql://` normalizes to `postgresql+psycopg://`; other drivers are rejected. Optional for Sheets, required for DB commands. |
| `TABULA_DATABASE_CONNECT_TIMEOUT` | Initial connection timeout in seconds, 1–60; default 5. |
| `TABULA_DATABASE_POOL_SIZE` | Connections retained per process, 1–50; default 5. |
| `TABULA_DATABASE_MAX_OVERFLOW` | Extra concurrent connections per process, 0–50; default 5. |
| `TABULA_TEST_DATABASE_URL` | Explicit test administrator endpoint with CREATE DATABASE permission. No fallback to `TABULA_DATABASE_URL`. |
| `TABULA_POSTGRES_PORT` | Compose loopback port; default 55432. |

URLs accept only the transport options `sslmode`, `sslrootcert`, `sslcert`, and
`sslkey`. URL-encode credentials containing reserved characters. Database roles
and pool sizing are deployment concerns; selected business entity context remains
mandatory on every repository query/mutation. A DB URL is not an entity selector
or commercial authorization grant. #222 supplies authenticated membership.

## Schema versions and migration policy

`python -m tabula_rasa.infrastructure.postgres upgrade` applies all revisions
to head in one PostgreSQL transaction. An advisory transaction lock serializes
migrators in the same database. Schema changes run only through this explicit
operator step; startup and connectivity checks never create tables or stamp
revisions. The baseline refuses conflicting pre-existing table names rather than
silently adopting an unknown schema. Alembic's revision table is independent of
v13 Sheets/archive versions and per-record optimistic versions.

`current` reports the exact revision (null for an empty DB), repository head,
connectivity, and `at_head`. It exits successfully if connected, allowing
inspection before migration. `health` and `upgrade` exit successfully only when
connected and at head. These commands emit one credential-safe JSON object.
This is a foundation readiness diagnostic, not an application health endpoint.

Baseline revision **`0001_initial`** contains all 26 ADR tables, named
row-local constraints, entity-qualified FKs, required indexes, immutable object
identities, and deferred entry balance/shape and two-level hierarchy checks.
It includes category-kind revalidation and the owned-event requirement for
zero-valued depreciation entries. Opening balances remain signed account values;
they are not duplicated as entries. Document tables hold metadata/links only.

Each future migration gets a new immutable revision in
`tabula_rasa/infrastructure/postgres/migrations/versions/`, with explicit
upgrade/downgrade behavior and native tests. Do not edit a revision once it has
been deployed. The SQL files beside `0001_initial.py` are frozen migration
assets, not runtime schema/model generators. No autogenerate/create_all/stamp
path substitutes for versioned migrations.

For local/staging and later production, inspect `current`, review migration SQL
and data impact, establish the required recovery point, apply `upgrade` once as
a deployment step, then inspect `health`. The deploying operator supplies the
target secret and migration role; ordinary application roles should not have
schema-administration privileges. Destructive upgrades require explicit reviewed
migration instructions and maintenance/recovery planning; do not bury deletion
inside startup or an automatic compatibility branch.

Downgrades are **never automatic application rollback**. Prefer rolling back
compatible application code or shipping a corrective forward migration. A
downgrade may delete accounting data and requires the explicit
`--allow-destructive` switch plus an operator-reviewed recovery plan:

```powershell
# Disposable development database only: removes the entire canonical schema.
python -m tabula_rasa.infrastructure.postgres downgrade --revision base --allow-destructive
```

The baseline drops named owned tables/functions explicitly, without CASCADE;
unexpected external dependencies stop the transaction. It does not delete a
database or document-store files. Production backup/PITR requirements and real
restore rehearsals remain #259/#223's work and gate #258 activation.

## Infrastructure operation convention

[#253's implemented operation and baseline convention](POSTGRESQL_CONCURRENCY.md)
extends this runtime with the adapter error boundary, ordered root guards and
the consolidated initial revision `0001_initial`. Later repository slices must
consume its version and specialized relationship/history guards before exposing
supported mutations. Schema initialization is explicit and atomic.

Composition constructs one `Database(DatabaseSettings(...))` per process/service
graph. Infrastructure adapters use `with database.transaction() as connection`
for a supported mutation. Participating repositories share that same Database
instance and context; nested boundaries join the existing connection, with
only the outer boundary committing. Adapters must not call `commit()` or create
independent transactions for coupled reference/source/entry writes.

A caught nested failure marks the entire operation aborted. A caught SQL failure
that leaves PostgreSQL's transaction aborted also cannot report commit success.
Exceptions roll back, return the connection to the pool, and reset operation
context. Do not swallow a database error and continue accounting work. There is
no automatic mutation retry or successful-write readback. Connection loss is an
unavailable outcome, not proof of rollback; later adapters under #253 must
classify uncertain commits using their stable operation/record identities.

Top-level `transaction(read_only=True)` uses read-only REPEATABLE READ for
coherent reporting/export snapshots. Nested reads join a mutation's existing
READ COMMITTED transaction. A mutation cannot join a read-only operation.
UTC applies to instants; SQL dates keep their calendar meaning. Call `dispose()`
on worker/test shutdown. Infrastructure connections never escape to services.

Recurring reconciliation must invoke a separate outer operation for each
occurrence. Committed earlier occurrences survive a later failure; an aborted
occurrence rolls back before best-effort attention writes or the next schedule.
Wrapping an entire reconciliation run in this transaction helper is unsupported.

## Constraint names and error boundary

The baseline names PKs `pk_<table>`, FKs `fk_<table>_<reference>`, row checks
`ck_<table>_<rule>`, and unique constraints/indexes `uq_<table>_<keys>`.
The migration SQL is the exact constraint/index inventory. Aggregate checker
codes include `ck_entry_balance`, `ck_simple_shape`, `ck_simple_category`,
`ck_journal_shape`, `ck_depreciation_entry`, `ck_reference_hierarchy`,
`ck_object_identity`, `ck_object_version`, `ck_entry_identity`, and
`ck_posting_identity`.
Specialized codes include `ck_mixed_category`, `ck_mixed_relationship`,
`ck_recurring_relationship`, `ck_recurring_identity`, `ck_asset_relationship`,
`ck_asset_history`, `ck_depreciation_history`, `ck_document_target`,
`ck_import_target` and migration-only `ck_link_target`. All use SQLSTATE 23514
and the same safe `invariant` application code; constraint text is not user text.

| PostgreSQL SQLSTATE | Safe infrastructure error code |
| --- | --- |
| 23505 unique | `duplicate` |
| 23503 FK | `reference` |
| 23514 CHECK / deferred invariant | `invariant` |
| 23502 NOT NULL | `required` |
| 40001 / 40P01 serialization / deadlock | `concurrent_write` |
| 25006 read-only write | `read_only` |
| Other driver/connectivity errors | `unavailable` |

Messages never interpolate PostgreSQL DETAIL, raw constraint messages, record
IDs, fingerprints, or parameters. Unknown constraint names do not become user
text. #253 and domain repositories translate these infrastructure codes into
the existing application error/result contract at their boundary. No provider
exception type is added to a service contract in this foundation.

## Core repository composition (#245 / #246)

`create_postgres_services(database, entity_id)` supplies the existing ledger,
account, category, payee, tag, transaction, journal and reporting application
services for one explicit, existing business entity. All adapters share the same `Database`.
The caller supplies authorized entity context and owns the database lifecycle;
this function neither authenticates users nor selects the production backend.
Schema upgrades remain an explicit operator step.

For a migrated disposable development database:

```python
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services

database = Database(DatabaseSettings.from_environment(required=True))
try:
    # Explicit provisioning, once per entity; duplicate IDs are refused.
    PostgresLedgerSetupRepository.create_entity(database, "example", "Example business")
    services = create_postgres_services(database, "example")
    services.ledger.ensure_defaults()
    loaded = services.accounts.list()[0]
    services.accounts.rename(
        loaded["id"], "Operating account",
        expected={"baseline": loaded["baseline"]},
    )
finally:
    database.dispose()
```

Defaults use the same definitions as Sheets and seed only when **both** accounts
and categories are empty. Names, active states, signed openings, classifications
and two-level hierarchies retain the current domain rules. Account deletion is
not a supported port. Category and managed-reference deletion refuse remaining
references. Payee/tag merges repoint every canonical owner atomically, including
journal line payees and mixed-source, schedule, asset and mileage associations.
Tag merges deduplicate associations before removing source identities. Display
names continue to resolve from stable IDs; a rename does not alter the referring
entry's baseline.

Simple Ledger entries contain the existing two canonical postings with stable
`<transaction-id>:1` / `:2` IDs. Advanced journals retain their original ordered
line IDs in the separate journal namespace. Simple and journal read models are
disjoint; both preserve exact amounts and shared accounting/domain validation.
Transaction CRUD/bulk and journal CRUD commit their complete aggregates together.
Inline payee/tag creation during service preparation joins the same transaction;
a validation or deferred-commit failure rolls it back too. Bulk selection is
all-or-nothing. No process-local workbook lock or remote-write retry applies.

Loaded records return #253's opaque `baseline` token from the same snapshot as
their values. Pass it separately through `expected`, never as an editable field
or entity selector. The adapters use the shared token/lock/error helpers and
`0001_initial` aggregate-version triggers. Returned tokens are mapped after participating
posting/tag/document-link writes, before the outer commit. A later stale submit,
including one after deletion and recreation with the same domain ID, fails.
Journals require a token or complete normalized loaded entry/posting snapshot.
Account/category snapshots must also be complete; the existing payee/tag/simple
transaction partial-snapshot compatibility remains. Derived labels and totals
are excluded from comparisons. Optional no-`expected` paths remain available
for legacy/internal callers and cannot detect a stale form. #221 must propagate
and require the agreed loaded baseline for supported commercial interactive
mutations; tokens confer no authorization.

Hierarchy mutations take the entity guard; accounting operations protect the
reference fields used during preparation. Bulk and merge roots use #253's ordered
aggregate locks. Merges discover all affected roots before locking and stop if
new owners appear while locks wait. FK, uniqueness and deferred posting checks
remain authoritative at commit. Repository failures use the shared safe error
codes documented in [PostgreSQL mutations and baselines](POSTGRESQL_CONCURRENCY.md).
An unavailable outcome does not prove rollback and does not trigger a blind retry.

Receipt references can link only matching metadata already registered in the
selected entity. Unlinking/deleting an ordinary entry retains the document.
New document acceptance and external bytes remain #251's responsibility. Existing
source-owned projections and recurring provenance are readable; generic mutation
of derived projections or provenance is refused. Existing ordinary recurring
occurrences retain their association on edit and remove it on deletion. New
recurring/source/asset workflows remain in their owning later repository slices.
Mileage, document-store, import and other secondary services are not
installed by this core composition.

Reuse map: the implementation inspected and extends the existing reference-data,
transaction/journal preparation, canonical posting translation, service assembly,
and #244/#253 infrastructure owners. Shared bootstrap defaults were extracted
from the Sheets schema without changing workbook format. New SQL mappings and
legacy snapshot normalization belong to the core adapters; there is no parallel
domain state machine, token format, version counter or error translator.

## Reporting repository (#247)

`PostgresLedgerQueryRepository` implements #229's `LedgerQueryRepository` and
is installed as `services.reporting` by the opt-in composition above. This is
the core reporting slice of #220/#124 and supports the early #221 web/API
milestone. It does not activate an entity, migrate Sheets data, or satisfy the
later whole-profile reconciliation, complete export, recovery or production
activation gates.

`read_ledger()` opens its own read-only REPEATABLE READ operation. The entity
existence check, accounts, categories, entry projections, tags, receipt counts
and recurring metadata all use that connection and committed snapshot. Reporting
refuses nesting inside **any** existing `Database` operation, including another
read-only operation, with the shared `boundary_mismatch` error. This prevents
joining a READ COMMITTED mutation with incomplete/uncommitted aggregates; the
normal operation-abort rules still apply. Invoke reporting at the query boundary
and reuse the returned snapshot for multiple service calculations.

Reads include inactive accounts and historical payee/tag labels. Every join uses
the selected entity as well as local IDs. The adapter returns only native
`ReportingAccount`, `ReportingCategory`, `LedgerTransaction`, `LedgerJournal`
and `LedgerPosting` values: SQL dates, exact Decimal amounts, booleans, tuples
and UTC timestamp strings. SQL connections, rows, version tokens, document
locators and worksheet-shaped records do not enter these projections.

The immutable `projection_kind` separates simple entries from advanced journals.
Simple entries map their two ordered canonical postings into one transaction;
advanced journals retain their complete ordered lines, even when posting IDs
overlap the separate simple namespace. Mixed-use entries use source tags and
receipt links once, and occurrences resolve through the ordinary entry or mixed
source owner. Depreciation, including zero periods, remains a source-owned
Simple Ledger Expense. Only persisted activity is read; nothing is regenerated.

The adapter batches each relation rather than querying once per entry. There is
no process cache: `force_refresh` is accepted for port compatibility and either
value reads a fresh snapshot. Date/kind/account/category/tag filters, complete
journal selection, opening balances, P&L, current earnings and hierarchy rollups
remain owned by `ReportingService`, `ledger_queries.py`, `ledger_reporting.py`
and `accounting_postings.py`. Dataframe/display formatting remains in presentation
code. No financial calculations or second filter implementation are added to SQL.

### Query plans and index coverage

The current port reads the full selected entity before applying service filters;
it does not accept a SQL date/target/tag filter or pagination input. Snapshot work
therefore grows with that entity's ledger size. The canonical baseline already
provides the required access paths; #247 adds no migration or speculative index.

| Read relationship | Existing access paths |
| --- | --- |
| Entity/reference rows | `business_entities` PK; entity-leading account/category/payee/tag PKs |
| Entry projection and date | `ix_entries_projection_date (entity_id, projection_kind, txn_date, id)` and `ix_entries_date` |
| Complete ordered postings | `uq_postings_entry_id_position (entity_id, entry_id, position)`; entity-qualified projection/entry FK |
| Account/category targets | `ix_postings_account_entry` and `ix_postings_category_entry` |
| Ordinary/source tags | Entry/source join PKs and `ix_entry_tags_reverse` / `ix_mixed_use_tags_reverse` |
| Recurring owner lookup | Entity/entry and entity/source unique occurrence indexes |
| Receipt owner counts | Entity-leading document-link owner indexes and unique owner/position indexes |

`tests/postgres/test_reporting_plans.py` seeds two synthetic entities, each with
2,000 simple entries, 200 journals, 500 tag associations and 200 receipt links.
It analyzes table statistics, verifies the index catalog, executes the actual
adapter SQL with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, checks output
cardinality, and enforces a fixed snapshot query budget (seven SELECTs rather
than one per entry). Both entities independently report income 22,000.

On PostgreSQL 18.6, the representative run returned 2,000 simple projections,
500 tag rows, 200 receipt counts and 400 journal lines. The planner used hash
joins and sequential/bitmap scans for broad entity reads, indexed mixed-owner
lookup, and the projection/date index for the smaller journal subset. Sequential
scans are reasonable when a selected entity contains half of a small table; the
test does not disable them or freeze a particular node strategy. Observed query
execution times were approximately 3.3, 0.9, 0.1 and 0.3 ms respectively, excluding
connection setup, transport and Python service calculations. These are development
diagnostics, not a production latency guarantee. Reassess with representative
customer distributions before extending the port or adding indexes.

Native reporting tests also verify independent expected balances/totals,
contra activity, inclusive dates, hierarchy rollups, complete journals, two-entity
isolation with overlapping IDs, inactive historical labels, source-owned history,
safe read failure and a bounded concurrent-write snapshot. The existing shared
service-contract fixture runs one independently calculated reporting workflow
on both Sheets and PostgreSQL.

## Native integration tests

```powershell
$env:TABULA_TEST_DATABASE_URL = 'postgresql+psycopg://tabula_dev@127.0.0.1:55432/tabula_dev'
python -m pytest tests/postgres
```

Every integration test creates its own uniquely named `tabula_test_<UUID>`
database, migrates it from zero, closes its connections, and drops only that
database in fixture cleanup. The administrator database is never truncated,
downgraded, or populated by these fixtures. No SQLite substitute is accepted.
Missing test configuration skips integration tests; configured but inaccessible
PostgreSQL fails them. Configuration and Sheets independence tests still run
without a test endpoint. `.github/workflows/postgres.yml` supplies real
PostgreSQL for automated checks, so its integration coverage cannot skip for
missing configuration. Interrupted runs may leave a disposable UUID database;
an operator may remove that specific test database after checking its identity.

Coverage includes zero-to-head and repeat upgrades, destructive downgrade and
re-upgrade, schema inspection, direct invalid writes, two-entity references,
exact money/signed openings, complete posting commit, nested atomicity, aborted
operations, independent-connection read snapshots, and safe failure diagnostics.
Core tests cover service workflows on both adapters, complete canonical postings,
all-owner multi-source merges, two-entity isolation, late validation/commit rollback,
inline-reference atomicity, independent loaded callers and overlapping writers,
recreated identities, receipt metadata retention and immutable provenance.
Run the existing full suite with this endpoint too when validating shared changes.

## Delivery boundary for the initiative

#244 supplies the reusable runtime and baseline. #245/#246 now supply the core
reference and accounting adapters described above. #247–#252 complete the
remaining domain mappings and mutation constraints/tests. #253 supplies shared
caller-baseline transport, aggregate version advancement and ordered locks.
Cross-adapter acceptance remains coordinated with the domain repository slices.
The `0001_initial` baseline includes #253's specialized enforcement from
ADR 0001: mixed complete/inspectable pairs, recurring target/history rules,
asset override and committed-event immutability, and allowed document/import
targets. The actual domain repository slices
must consume these guards, reuse the existing domain algorithms and verify
their full supported paths before use. Native service contract probes validate
shared atomicity and recurring failure isolation without supplying full adapters.

The full PostgreSQL repository paths are not exposed by the current application; no
commercial mutation should rely on FK/row checks alone. Every repository slice
must enforce its supported invariants from its first implementation. Stable
entity/reference/transaction slices (#245/#246 and usable #247) unblock early
#221 web/API work. Final v13 extraction/reconciliation (#254–#257), complete
entity export (#260), recovery rehearsal (#259), and controlled single-backend
activation (#258) remain separate. No Sheets data migration, dual write,
identity model, frontend replacement, or production activation happens here.


## Initial baseline and Sheets migration

Issue #254 consolidates the unused pre-production `0001_canonical`,
`0002_aggregate_versions`, and `0003_domain_integrity` revisions into
`0001_initial`, retaining their table definitions, aggregate-version machinery,
and domain/history guards. The operator confirmed on 2026-10-05 that only
disposable development/test databases exist and no staging database has been
provisioned. Original revisions remain in Git history, not the active Alembic
chain. `migration_id_mappings.source_updated_at` retains original source update
provenance independently of database-controlled aggregate update instants.

An old disposable database must be explicitly recreated, never stamped to the
new revision. An unexpected retained database is a stop-and-investigate case;
preserve its data and old revision chain. This implementation recreates only
synthetic UUID test databases through the existing test fixture. It does not
reset an operator database or silently upgrade an old revision identifier.

Parallel repository tickets #248–#252 consume this baseline. Repository code
alone need not introduce a revision. Any later schema/constraint change uses a
new forward revision after `0001_initial`, coordinated to keep one Alembic head.
Once this baseline is deployed to a retained database, keep it immutable.
Do not delay #254 framework work for every secondary repository; corresponding
loaders remain #256's responsibility.

See [the migration operator guide](SHEETS_POSTGRES_MIGRATION.md) for dry-run,
explicit loading, extension contracts, restart, and the persistent staging
checkpoint. #257 whole-profile acceptance and #258 cutover remain separate.
