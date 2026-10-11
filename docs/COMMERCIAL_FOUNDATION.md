# HTTP and browser foundation conventions

Issues [#277](https://github.com/Roklion/Project_Tabula_Rasa/issues/277) and
[#278](https://github.com/Roklion/Project_Tabula_Rasa/issues/278) implement Wave 1
of [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) under
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
[ADR 0002](adr/0002-commercial-web-runtime.md) remains the stack contract;
[Commercial development](COMMERCIAL_WEB.md) owns local and hosted topology.

## Delivered scope and subsequent owners

The runnable foundation includes a responsive shell, history routing, a read-only
accounts view, a representative account-create API, generated transport types,
safe errors, health/version routes, request instrumentation, context seams,
query/mutation conventions and loaded-form primitives.

This is a synthetic local technical-alpha foundation. Domain workflow coverage
belongs to #281–#286, real edit/delete baseline propagation to #280, membership
and session lifecycle to #222, deployment and its temporary hosted gate to #279,
operations to #223, and broader browser/device quality to #287.
[Commercial concurrency](COMMERCIAL_CONCURRENCY.md) documents #280's subsequent
protected edit/delete endpoints and forms, loaded-token enforcement and native
two-client browser validation. [Commercial mileage and receipts](COMMERCIAL_MILEAGE_RECEIPTS.md)
documents #286/#283's subsequent list/create/detail and document-transfer workflows.
Production activation remains separate. Streamlit
remains the internal/reference edition.

## Transport and service composition

- JSON resources use `/api/v1/entities/{entity_id}/{resource}`; commands use an
  explicit action subpath when introduced. IDs are opaque strings. Dates are ISO
  calendar dates; instants are UTC; exact decimal values are strings.
- `GET /api/v1/session` returns safe server-resolved actor, organization, business,
  capabilities, cache scope and CSRF data. This currently describes an explicit
  trusted synthetic context, not commercial login or memberships.
- `GET /api/v1/entities/{entity_id}/accounts?active_only=false` delegates to
  `AccountService.list`. `POST` delegates directly to `AccountService.create`
  and returns 201 only after that service confirms the operation.
- Request/response Pydantic DTOs live in `http/models`. Response mapping
  allowlists fields rather than serializing service dictionaries wholesale.
  Handlers are synchronous, keeping an entire service operation in one worker
  thread. SQL, transaction boundaries and accounting rules remain with their
  existing owners.
- `create_app` owns lifespan startup/shutdown. The default runtime owns one
  PostgreSQL pool, verifies the named synthetic entity without creating it,
  composes each request after context checks, and disposes the pool on shutdown.
  Startup never migrates, seeds or reconciles recurring entries.
- `PostgresRuntime` requires an explicit service factory. The default local
  factory uses the fixed `alpha-synthetic` and `beta-synthetic` demonstration
  fixtures for local functional selection. See [Core workflows](COMMERCIAL_WORKFLOWS.md).
  For migrated entities,
  use `MigratedProfileServices` with a **server-configured** entity-to-profile
  mapping. It calls existing `create_application`, preserving #258 authority,
  environment and document-store binding checks. Its optional legacy provider
  dependencies are installed only for that operator composition; the synthetic
  API and schema exporter do not import Streamlit, Sheets or Google clients.
- `open_migrated_runtime` supplies the shared lifecycle for accepted migrated
  profiles. It validates all server-configured authority/document bindings and
  schema readiness at startup, requires an explicit authorization resolver,
  refuses synthetic contexts and disposes failed pools. Lasting owner use keeps
  the existing non-commercial cutover policy in a normal production app; see the
  [owner-operated procedure](BOOKKEEPING_CUTOVER.md#owner-operated-production-procedure-299).
  This factory does not deliver #222's login/session system or remaining browser
  workflow slices, and its synthetic tests do not authorize live use.

## Identity and request protection seam (#222)

[ADR 0003](adr/0003-commercial-identity-and-tenancy.md) selects the named OIDC
identity, durable session, role and server-membership contract. Follow
[Commercial identity](COMMERCIAL_IDENTITY.md) for its staged implementation,
operator checkpoints and testable threat model. #312 extends session DTOs for
users without an entity; #313 replaces the broad method-based write rule with
explicit action capabilities while retaining Origin/CSRF. Those extensions
remain follow-on work; the behavior below describes today's foundation.

Inject a `runtime_factory(settings)` into `create_app`. Its resolver receives a
Starlette request and returns the immutable `RequestContext`. #222 must resolve
active membership and capabilities server-side on every call before service or
credential binding. Supply a nonsecret cache scope that changes across sessions
and membership contexts, and a session-bound CSRF token. The browser's selected
entity, route/body/profile key, baseline or header never proves authorization.

`resolve_context` checks entity agreement and read/write capabilities; unsafe
operations additionally require the exact configured Origin and
`X-CSRF-Token`. API schema/docs use the same read context guard. An absent
resolver denies access with 401. The default trusted resolver requires a
loopback client and explicit development/test configuration. #279 adds a fixed
hosted synthetic scope behind its environment-specific HTTP Basic gate; public
HTTPS configuration, credentials and bound Neon connectivity fail closed.
Production rejects synthetic context and alpha credentials. [Technical deployment](COMMERCIAL_DEPLOYMENT.md)
owns the operator checkpoint and outstanding real hosted verification. #222 replaces that gate before
external beta/customer data.

HTTP settings are read only from process environment. Database settings retain
their existing loader. `TABULA_RASA_PUBLIC_ORIGIN` is the exact browser origin,
without a trailing slash. Vite forwards the original Host on `/api` calls;
direct data/schema requests to API port 8000 therefore need the configured Host.
Host names are compared case-insensitively. Minimal health and release probes
(`/health/live`, `/health/ready`, `/version`) are exempt from Host checks and
expose no business data.
No CORS or browser API-origin override is enabled.

## Errors, request IDs and operational hooks

Errors have the transport shape:

```json
{
  "error": {"code": "stale", "message": "The record changed since it was loaded. Review the latest record."},
  "request_id": "server-generated-reference"
}
```

`error.fields`, when present, contains declared field names, machine codes and
safe generic instructions. Input values, unexpected field names, SQL, provider
errors, cookies, credentials and draft values never enter errors or request logs.
The code enum is generated into the browser contract.

| HTTP | Machine codes |
| --- | --- |
| 422 | `validation`, `reference`, `invariant`, `required`, `baseline_required`, `baseline_invalid` |
| 404 | `not_found` |
| 409 | `conflict`, `duplicate`, `concurrent_write`, `stale` |
| 401 / 403 | `unauthorized` / `forbidden` |
| 503 / 500 | `unavailable` / `unexpected` |
| 405 | `method_not_allowed` |

Every response gets a generated `X-Request-ID`; supplied request IDs are never
adopted. An optional `X-Correlation-ID` is accepted only as 1–64 ASCII letters,
digits, periods, underscores or hyphens, stored separately, and never used as
identity. The `tabula_rasa.http` logger emits only IDs, method, route template,
status, duration, safe failure code and release. Configure this logger's INFO
sink under #223. Raw Uvicorn access logging is disabled by the factory;
unexpected request exceptions are consumed into generic safe responses.

`/health/live` checks process liveness. `/health/ready` checks the existing
bounded database connectivity probe and exact current Alembic head, returning
503 on unavailable/incompatible schema without migrating. `/version` exposes
only a bounded safe release identifier. Private JSON/schema responses use
`Cache-Control: no-store`; compiled hashed assets use immutable caching, and
the SPA entry uses revalidation. Only GET/HEAD HTML navigation can fall back to
the SPA; unknown API paths, non-HTML requests and missing assets retain errors.

## Browser ownership and form conventions

[Commercial UI foundations](COMMERCIAL_UI_FOUNDATIONS.md) documents #325's
design audit, shared tokens/action/header/table hooks and representative consumers
under #323/#124. These presentation primitives extend the owners below without
replacing form, query, context or workflow state.

`src/api/schema.d.ts` is generated from committed OpenAPI; feature code imports
these types rather than redefining transport records. `createApi` uses relative
same-origin requests, includes credentials, propagates read cancellation and
CSRF, and replaces raw network failures with safe `ApiError` values.

`resourceKey(session, resource)` includes the server session cache scope and
entity ID. `ScopeBoundary` gives each context its own QueryClient and remounts
feature drafts when server session/entity/capabilities change. It cancels reads
and clears old private caches on teardown. #222 will feed refreshed membership
context and unmount this boundary on logout. The visible business label comes
from the server; the shell does not provide a client authorization override.

Reads retry unavailable failures at most once. Mutations never retry
automatically. `useCreateAccount` invalidates only that context's accounts
after confirmed success or failure, including an uncertain network result.
Features should invalidate their known affected resources and stop for explicit
inspection of uncertain writes, rather than using a second client recovery loop.

`useLoadedForm({values, metadata})` initializes React Hook Form's editable
values and a cloned, frozen load-metadata snapshot separately. Rerender/refetch
does not replace either draft or baseline. Its explicit `reload(next)` resets
both together; a feature calls it only after the user chooses to discard or
review changes. Never obtain a fresh baseline during submission. Validation,
conflict or unexpected errors leave the form intact. `UnsavedChanges` blocks
router navigation while dirty with keep/discard actions and requests the
browser's native before-unload confirmation.

Shared loading, empty, validation/conflict/error, success and labeled-field
primitives use semantic roles. Connect a field's input `aria-invalid` and
`aria-describedby="<id>-error"` to the supplied field error. Conflict state
offers an explicit review action; no error generates a success message.

## Validation and generated contract

From root with the development environment active:

```powershell
python -m pytest tests/http tests/postgres/test_http_foundation.py
python -m tabula_rasa.http.export_openapi --output contracts/http/openapi.json
npm --prefix web ci
npm --prefix web run api:generate
git diff --exit-code -- contracts/http/openapi.json web/src/api/schema.d.ts
npm --prefix web run build
npm --prefix web run lint
npm --prefix web test
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
```

Native tests require the explicit disposable `TABULA_RASA_TEST_DATABASE_URL`;
they never infer it from the runtime target. HTTP tests prove service delegation,
stable safe errors, context/capability/Origin/CSRF boundaries, pool lifecycle,
schema access and offline deterministic generation. Native tests cover
read/create/domain failures and two-entity isolation. Browser tests cover
typed requests, mutation retry/invalidation, session/entity cache isolation,
loaded metadata retention, unsaved navigation and reusable states. Playwright
smoke tests use intercepted synthetic responses at 1440, 1200, 900, 390 and
320 CSS-pixel widths. This is Chromium smoke evidence, not real-device or full
cross-browser certification; #287 owns that wider gate.
If a development preview occupies port 5173, set `TABULA_RASA_SMOKE_PORT` to an
unused loopback port before `npm --prefix web run test:e2e`. The smoke runner
starts its own server and does not reuse or stop the existing preview.

[Repository CI](DEVELOPMENT.md#authoritative-ci-and-required-check) exports and
regenerates both contract artifacts, rejects drift, compiles the consumer and
runs the browser foundation checks. Its complete Python job owns API/native
PostgreSQL tests without a duplicate foundation pytest invocation. A dedicated
Windows job covers platform-specific setup tests. The aggregate **Full test
suite** check gates the current PR candidate while CI and advisory review proceed
concurrently; publication and review completion require no ritual full local run.
