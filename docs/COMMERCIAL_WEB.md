# Commercial web development and deployment

[ADR 0002](adr/0002-commercial-web-runtime.md) is the selected stack/topology
contract for [#276](https://github.com/Roklion/Project_Tabula_Rasa/issues/276),
under [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Use it together with [Development](DEVELOPMENT.md),
[PostgreSQL operations](POSTGRESQL.md), and
[loaded-record concurrency](POSTGRESQL_CONCURRENCY.md).

## Implementation status

#277/#278 now provide the runnable local HTTP/browser foundations. See
[Foundation conventions](COMMERCIAL_FOUNDATION.md) for endpoints, context/error
contracts, query/form primitives and test ownership. The image, workflows and
temporary hosted gate are implemented under #279; [Technical deployment](COMMERCIAL_DEPLOYMENT.md)
owns setup, promotion and rollback. Closed #279 records hosted dev/staging
acceptance; [Technical alpha](TECHNICAL_ALPHA.md) defines #288's separate
workflow/receipt/staging gate, evidence and controlled retirement boundary.
Repository implementation does not establish external-beta readiness or
production authority. Streamlit/Sheets continues as the internal/reference runtime.

#280 adds the [protected commercial edit/delete bridge](COMMERCIAL_CONCURRENCY.md)
over those foundations, carrying loaded baselines through actual browser/API
mutations while preserving service-owned concurrency and compatibility.
Broader domain workflow migration remains #281–#286.

#299's [owner-operated production procedure](BOOKKEEPING_CUTOVER.md#owner-operated-production-procedure-299)
uses this same application and deployment. `open_migrated_runtime` binds accepted
profiles through the normal authenticated context resolver and existing cutover
checks. HTTP `production` and database branch names are distinct from commercial
activation evidence policy. Owner recovery acceptance does not require a provider
upgrade; NAS automation/restore remains #294. The current synthetic foundation,
missing normal identity/deployment integration and unfinished browser workflows
must not be presented as a completed live owner deployment.

## Package and build ownership

Keep one repository, the existing Python package and existing Alembic chain.
Do not move neutral services into the HTTP package or introduce an ORM mirror.
The package ownership is:

```text
tabula_rasa/
  application/                  existing neutral services/contracts/domain seams
  infrastructure/postgres/      existing SQL adapters, database lifecycle, migrations
  http/                         #277 Python transport package
    app.py                      create_app factory, lifespan, route assembly
    composition.py              database + authorized entity/document service binding
    context.py                  replaceable #222 context resolver
    models/                     transport-only Pydantic request/response models
    routes/                     thin resource/command handlers
    errors.py                   safe error/HTTP mapping
    export_openapi.py           schema-only deterministic export CLI
  jobs/                         reserved for #223, no alpha scheduler scaffold
web/                            #278 single npm package
  package.json
  package-lock.json
  src/api/schema.d.ts            generated from HTTP OpenAPI
  src/api/                      typed client + query keys/mutation wrappers
  src/app/                      routing/context and responsive shell
  src/components/               shared accessible controls/form states
  src/features/                 independently delivered bookkeeping slices
  src/styles/                   design tokens and common layout rules
  dist/                         ignored build output
contracts/http/openapi.json      generated, committed transport schema
requirements-api.txt             #277 API + audited non-UI Python dependencies
deploy/commercial/Dockerfile      #279 multi-stage Node-build/Python-runtime image
deploy/commercial/render.yaml     #279 Render environment/resource declaration
tests/http/                      #277 transport and real-PostgreSQL integration
web/src/**/*.test.tsx             #278 Vitest/React Testing Library tests
web/e2e/                         #278 shell smoke; #287 grows workflow coverage
```

Use root Python imports for `tabula_rasa` in local commands, tests and images.
Do not create a second Python distribution or npm workspace manager for one
browser package. `requirements-api.txt` pins the API runtime and required
shared dependencies without importing/installing Streamlit as an API runtime
requirement. Install it together with `requirements-postgres.txt` in the image;
extend the development dependency file for API tests. #283 adds document-provider
dependencies when its adapter is selected, without making Drive part of HTTP
models. Commit library locks/pins; never commit generated build output or
environment secrets.

Required npm scripts from #278: `dev`, `build` (TypeScript check + Vite build),
`typecheck`, `lint`, `test` (Vitest run), `test:e2e` (run-once contracts then
Playwright UI), `test:contracts` (HTTP/Git),
`test:browser` (all UI projects or an explicit shard), and
`api:generate` (`openapi-typescript` over `../contracts/http/openapi.json`).
The API exporter from #277 writes deterministic JSON to `--output` without
reading settings/credentials, starting database lifespan or using the network.
CI runs export then generation, rejects changes to committed generated files,
and compiles the consumer; no schema fetch from a running staging service.

## Local topology and commands

Use Python 3.12 and Node.js 24 LTS with npm. From the repository root, the
**existing, runnable** database setup is:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
docker compose -f compose.postgres.yml up -d --wait
$env:TABULA_RASA_DATABASE_URL = 'postgresql+psycopg://tabula_dev@127.0.0.1:55432/tabula_dev'
python -m tabula_rasa.infrastructure.postgres upgrade
python -m tabula_rasa.infrastructure.postgres health
```

This is a synthetic, disposable loopback database. Native pytest integration
requires the separate `TABULA_RASA_TEST_DATABASE_URL` process variable pointing
to a disposable administrator endpoint; never infer it from the runtime URL or
point tests at retained staging/production. Migration/operator details stay in
[PostgreSQL operations](POSTGRESQL.md#local-setup).

Install/export/generate the implemented foundations once from root:

```powershell
python -m pip install -r requirements-api.txt -r requirements-postgres.txt
python -m tabula_rasa.http.export_openapi --output contracts/http/openapi.json
npm --prefix web ci
npm --prefix web run api:generate
```

Run the API and Vite in separate terminals. Each terminal starts at repository
root. API terminal (activate `.venv` first):

```powershell
$env:TABULA_RASA_ENVIRONMENT = 'development'
$env:TABULA_RASA_PUBLIC_ORIGIN = 'http://127.0.0.1:5173'
$env:TABULA_RASA_DATABASE_URL = 'postgresql+psycopg://tabula_dev@127.0.0.1:55432/tabula_dev'
$env:TABULA_RASA_TRUSTED_ENTITY_ID = 'alpha-synthetic'
python -m tabula_rasa.http.seed_development  # Once, on the blank synthetic development DB.
python -m uvicorn tabula_rasa.http.app:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Browser terminal:

```powershell
npm --prefix web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173`. Vite must proxy `/api` (without stripping the prefix)
to `http://127.0.0.1:8000`; the browser uses relative URLs and has one origin.
Use `127.0.0.1` consistently, rather than mixing it with `localhost` for cookies.
PostgreSQL remains on `127.0.0.1:55432`. Bind all local listeners to loopback.
Health checks can be called directly on API port 8000. Root production routes
serve `/health/live`, `/health/ready` and `/version`; they are not SPA paths.

The default trusted ID is the explicitly seeded `alpha-synthetic` entity; the
seed also creates `beta-synthetic` so the local business selector can exercise
independent contexts. Both are fixed demonstration fixtures, not arbitrary
browser-selected entities. [Core workflows](COMMERCIAL_WORKFLOWS.md) describes
the selection and bookkeeping paths.
The seed command uses the existing entity repository, refuses hosted/non-development
targets, and stops if that ID exists. Other IDs or an unseeded fixture fail
startup. No seeding, recurring
generation or schema migration occurs on ordinary application startup. Before
#222, no local environment variable stands in for commercial membership.

For schema/client checks:

```powershell
python -m tabula_rasa.http.export_openapi --output contracts/http/openapi.json
npm --prefix web run api:generate
git diff --exit-code -- contracts/http/openapi.json web/src/api/schema.d.ts
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
```

API tests call the service boundary with fakes and native PostgreSQL; browser
tests cover visible loading/validation/conflict and entity-cache isolation.
#280 adds the two-loaded-client stale edit/delete and missing-baseline scenarios
against real PostgreSQL. Run affected tests and fast lint/type/style checks before
publishing or pushing review fixes. Repository CI runs the full suite concurrently
with review; its current-revision `Full test suite` check must succeed before
review-loop completion. A full local run is exceptional diagnostic work, not a
publication or terminal-review prerequisite. See [Development](DEVELOPMENT.md#authoritative-ci-and-required-check).

## Hosted environment contract

| Environment | Runtime/data | Exposure and release |
| --- | --- | --- |
| Local | Vite + loopback Uvicorn + existing Docker PostgreSQL 18 | Synthetic fixture context; developer starts each process. |
| Hosted development | Own Render image service + scoped Neon environment/roles | Synthetic data; validated `main` deploys; explicit restricted alpha or named mode. Record selected plan limitations. |
| Retained staging | Separate Render image service + retained Neon environment/roles | Explicit commit/image promotion and access mode; synthetic acceptance data; named-provider transition follows #321. This is the real persistent staging target, not local Compose or a per-test DB. |
| Intended production | Separate Render service + distinct Neon production branch/endpoint and scoped runtime/migration access | Promote the staging-tested image digest only after identity, cutover and operations/recovery gates. Reject trusted alpha context. |

For the current pre-activation stage, the operator has selected Neon Free with
production and retained UAT on distinct branches/endpoints in one project;
[ADR 0002](adr/0002-commercial-web-runtime.md#deployment-decision) records this
amendment. Keep configuration and access scoped to each environment, preserve
the retained UAT database, and use separate isolated recovery targets. A shared
project shares administration and capacity; branch separation does not prove
independent project access. Formal commercial activation still requires the
isolation/protection/objective review under #220/#258/#223 described in
[PostgreSQL recovery](POSTGRESQL_RECOVERY.md). #279/#221/#124 now permit suitable
free tiers for technical dev/staging; record capacity and idle-suspension limits
at the [manual checkpoint](COMMERCIAL_DEPLOYMENT.md#manual-operator-checkpoint).
This does not authorize provisioning, cloning or commercial activation.

GitHub Actions builds the `linux/amd64` image into GHCR; Render image-backed
services (`runtime: image`) consume its immutable digest. CI explicitly triggers
hosted dev after checks; image-backed services do not follow Git pushes on their
own. Render terminates HTTPS and forwards to one Uvicorn port. The image contains
the compiled browser assets and the API, with no Node process. Use one canonical
origin per environment; redirect additional hosts rather than sharing session
cookies across environments. HTTP and static routing/cache policy is owned by
[ADR 0002](adr/0002-commercial-web-runtime.md#deployment-decision).

Neon runtime connections use direct/unpooled TLS URLs with `sslmode=require`,
small SQLAlchemy pools and the existing bounded configuration. Keep the runtime
role free of schema-administration permissions. Environment projects are not
tenant boundaries: authorized membership/entity context still scopes every
bookkeeping operation within a project's database. Do not provision one DB per
client-supplied profile key.

## Configuration and secrets boundary

The HTTP environment/public-origin/release/trusted-entity settings below are
implemented by #277 and read from process environment only. #279 implements the
alpha gate and deployment settings; #222 still owns commercial identity/session
settings. They do not alter Streamlit settings.

| Setting | Owner and visibility |
| --- | --- |
| `TABULA_RASA_ENVIRONMENT` | Server; `development`, `staging` or `production`. Trusted fixture mode explicitly prohibited in production. |
| `TABULA_RASA_ACCESS_MODE` | Server and matching deployment environment variable; explicit `restricted_alpha` or `named_user` on hosted services. Only named mode permits owner/external use. |
| `TABULA_RASA_PUBLIC_ORIGIN` | Server; exact canonical browser origin for Host/Origin/cookie policy; no wildcard. |
| `TABULA_RASA_RELEASE_ID` | Build/deploy metadata; Git SHA or immutable release ID, safe in `/version` and logs. Image digest/schema head recorded with the release. |
| `PORT` | Hosting process; Uvicorn binds the assigned container port. Local command explicitly selects 8000. |
| `TABULA_RASA_DATABASE_URL` and existing pool/timeout settings | Server runtime secrets/config; current `DatabaseSettings` owns validation. URL never enters the browser, image layer, logs, error text or OpenAPI. |
| `TABULA_RASA_MIGRATION_DATABASE_URL` | Deployment job secret only; job maps it to `TABULA_RASA_DATABASE_URL` for the existing CLI. Never injected into the running app. |
| `TABULA_RASA_DEPLOY_DATABASE_SHA256` | Explicit selected Neon endpoint binding, checked by both runtime and migration processes. |
| `TABULA_RASA_TEST_DATABASE_URL` | Explicit test process only; disposable native test administrator endpoint. |
| `TABULA_RASA_TRUSTED_ENTITY_ID` | Local/test synthetic context, or fixed hosted synthetic alpha scope behind the deployment gate. Never accepted from a request; absent in production. |
| `TABULA_RASA_ALPHA_USERNAME` / `TABULA_RASA_ALPHA_PASSWORD_HASH` | Temporary #279 server gate secrets; distinct per hosted non-production environment, never browser build values or commercial roles. |
| Identity/session/OAuth secrets | #222 server secret injection and authorized credential-store binding. Provider-specific names/schema belong to #222, not frontend config. |

The browser has no environment-specific API URL or secrets. Relative API routing
lets the same compiled artifact promote from staging to production. `VITE_*`
values are public build constants; allow only reviewed non-sensitive values such
as build identity, and never copy server environment files into the web build.
Do not introduce frontend environment overrides for entity authorization.

Local `.env.local` remains ignored and is loaded by the existing database
settings only. Export HTTP settings explicitly in the process; its loader does
not read an environment file. Hosted processes receive secrets from the
environment's provider secret store; image builds and schema export have none.
Existing `.streamlit` files/password/Google grants stay with the internal
edition. Commercial per-customer connections are resolved from authorized
context under #222; no fallback to a legacy profile's grant or Drive root.

## Deployment lifecycle and manual checkpoint (#279)

Before provisioning, the operator supplies Render account/project access,
selected stage-appropriate service capacity, GHCR image access, Neon projects/roles,
approved geographically close US regions with PostgreSQL 18, DNS/TLS ownership,
and environment-specific secrets/deploy credentials. Verify provider support, budgets/limits and retained
staging connectivity. These are explicit manual tasks, not completed resources.
The exact setup and hosted evidence checklist lives in [Technical deployment](COMMERCIAL_DEPLOYMENT.md).
An agent must stop at this checkpoint if credentials/provisioning are missing;
do not substitute SQLite, temporary memory, another provider or production data.

#279 implements a reproducible multi-stage image build and explicit promotion:

1. Run required Python/native-PostgreSQL and implemented web/API checks; export
   and verify schema/client drift. Build the image without runtime secrets and
   identify it by commit and immutable digest. Retain rollback digests in GHCR.
   For schema changes, first deploy a tested bridge image declaring both old and
   target schema revisions compatible; otherwise plan explicit maintenance and
   drain. Initially API readiness accepts only the current head. Compatibility
   is declared by tested code, never an operator wildcard/bypass setting.
2. In a serialized environment deployment job with the **migration** credential,
   inspect `current`, apply `upgrade`, then run `health` using the existing CLI.
   Schema changes must remain compatible with the still-running old image.
3. Deploy the image to Render with the **runtime** credential. Require
   `/health/ready` before traffic/promotion; a failed migration or readiness
   step stops the release. Application startup never migrates.
4. Verify version, deep-link/static/API routing, browser -> API -> real
   PostgreSQL synthetic smoke and access restrictions. A post-deploy smoke
   failure stops further promotion. Restricted alpha redeploys the prior compatible
   digest; named mode stops for reviewed operator recovery without automatic rollback.
   Promote the same image only after staging acceptance evidence is recorded.
5. If application code fails, redeploy the prior schema-compatible digest after
   verifying named-auth/configuration compatibility where applicable.
   Incompatible schema failures stop for the operator; no automatic downgrade,
   restore or accounting-data deletion. Recovery is #259/#223.

The implemented temporary alpha HTTP Basic gate covers shell, data, document and schema
routes over TLS. Minimal health probes are exempt for the platform; unsafe
requests still require Origin/CSRF protection. A trusted fixture ID without the
gate must make hosted startup fail closed. #222's implemented named path replaces
both the gate and fixture resolver before owner/external use. Follow
[authenticated rollout](AUTHENTICATED_ROLLOUT.md) for manual configuration,
pending hosted acceptance and named rollback. #279 records the precise
proxy boundary: Uvicorn trusts no forwarded headers; configured Host and Origin
remain authoritative. Spoofed forwarding/Host inputs are covered by tests.

Retain staging across releases and coordinate its separate migration rehearsal
with [the persistent staging checkpoint](SHEETS_POSTGRES_MIGRATION.md#persistent-staging-checkpoint).
The #254 framework drill already passed on the operator-selected Neon UAT
environment on 2026-10-06; #279 must verify authorized reuse of a compatible
retained target or provision a separate commercial staging target. That drill
does not substitute for realistic source reconciliation, whole-profile
acceptance or the browser/API staging smoke. Migrated-profile HTTP composition
must reuse [#258's trusted authority/document binding](BOOKKEEPING_CUTOVER.md)
through `create_application`, rather than bypassing it with the low-level
PostgreSQL factory.
Do not overwrite an existing operator UAT target, stamp a retained old schema,
or claim that a local UUID integration database satisfies this gate. Selection
of this stack does not activate entities or complete migration, exports,
recovery/PITR, commercial auth, beta or Streamlit retirement requirements.

## Browser quality and alpha gate

[Commercial browser quality](COMMERCIAL_BROWSER_QUALITY.md) owns #287's repeatable
Playwright/axe gate, viewport/engine matrix, synthetic fixture cleanup and the
remaining #283/#288 receipt/staging and manual-device acceptance boundaries.
