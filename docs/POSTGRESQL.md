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

Baseline revision **`0001_canonical`** contains all 26 ADR tables, named
row-local constraints, entity-qualified FKs, required indexes, immutable object
identities, and deferred entry balance/shape and two-level hierarchy checks.
It includes category-kind revalidation and the owned-event requirement for
zero-valued depreciation entries. Opening balances remain signed account values;
they are not duplicated as entries. Document tables hold metadata/links only.

Each future migration gets a new immutable revision in
`tabula_rasa/infrastructure/postgres/migrations/versions/`, with explicit
upgrade/downgrade behavior and native tests. Do not edit a revision once it has
been deployed. The SQL files beside `0001_canonical.py` are frozen migration
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
Run the existing full suite with this endpoint too when validating shared changes.

## Delivery boundary for the initiative

#244 supplies a reusable runtime and baseline, not finished commercial ledger
repositories. #245–#252 implement domain SQL mappings and complete their own
mutation constraints/tests. #253 owns caller-baseline transport, aggregate
version advancement (including detail/link changes), deterministic multi-root
lock order, concurrent-writer verification, and the remaining specialized
deferred relationship/provenance enforcement from ADR 0001. In particular,
mixed complete/inspectable pairs, recurring target/history rules, asset override
and committed-event immutability, and allowed document/import targets need
those repository slices and coordinated #253 migrations before use.

These unimplemented paths are not exposed by the current application; no
commercial mutation should rely on FK/row checks alone. Every repository slice
must enforce its supported invariants from its first implementation. Stable
entity/reference/transaction slices (#245/#246 and usable #247) unblock early
#221 web/API work. Final v13 extraction/reconciliation (#254–#257), complete
entity export (#260), recovery rehearsal (#259), and controlled single-backend
activation (#258) remain separate. No Sheets data migration, dual write,
identity model, frontend replacement, or production activation happens here.
