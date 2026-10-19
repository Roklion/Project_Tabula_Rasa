# Technical development and staging deployment (#279)

This is the deployment implementation for [#279](https://github.com/Roklion/Project_Tabula_Rasa/issues/279),
under [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It consumes #276's same-origin Render/Neon decision, #277's thin API and #278's
browser shell. #220 owns schema/adapter/migration semantics; #222 replaces the
temporary gate with membership and durable sessions; #223 owns broader operations.
#280, core domain slices and #287/#288 still own concurrency and technical-alpha
integration. #298 recovery agreement/paid-launch activation is a separate gate.

## Implemented repository path and evidence boundary

`deploy/commercial/Dockerfile` builds the browser with Node 24 and runs Python
3.12 as a non-root user. One Uvicorn worker serves browser assets, `/api/v1`,
`/health/live`, `/health/ready` and `/version`. `.dockerignore` allows only the
required sources/dependency manifests; settings, local credentials and ledger
artifacts cannot enter the build context. Server secrets are never build args.
The release SHA is visible at `/version`; OCI labels record SHA and Alembic head.
The browser uses relative API URLs and requires no per-environment build.

`commercial-image.yml` follows successful **push-to-main Repository CI** and
builds/publishes a `linux/amd64` GHCR image tagged by SHA. Its summary records the
immutable digest and expected schema head. Repository CI also builds/imports
the container without credentials. `commercial-promote.yml` serializes the
whole deployment per GitHub environment with cancellation disabled. Development
follows the validated image; `commercial-staging.yml` accepts an explicit digest
from main. Promotion checks the image's repository, OS/architecture, release
metadata, main ancestry and latest matching main-push CI success. Keep SHA tags
and associated digests needed for rollback; never prune active/rollback releases.

Closed [#279](https://github.com/Roklion/Project_Tabula_Rasa/issues/279) records
hosted development/staging acceptance on October 9, 2026, including retained
Neon UAT and successful [staging promotion](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/37951248477).
The setup instructions below remain the operator contract for new/reconfigured
environments. Local native tests and a local container prove implementation only.
#288's complete core workflow/real-provider receipt gate, compatible rollback
rehearsal and manual-device evidence remain separate in [Technical alpha](TECHNICAL_ALPHA.md).
On October 8, 2026, the operator approved reuse of the existing retained UAT
database for staging. Confirm its exact endpoint binding, current forward schema
and runtime/migration role custody before connecting the commercial service;
this approval does not authorize overwriting its existing records.
A read-only check of the locally configured direct Neon target on that date
confirmed `0005_bookkeeping_cutover`, matching this release's schema head.
Its local URL included unsupported `channel_binding`; remove that option when
copying the URL into deployment secrets, as documented in PostgreSQL operations.
The check normalized the URL in memory and changed no files or database records.
Enable `COMMERCIAL_DEPLOY_ENABLED=true` only after the checkpoint below. There
is no production deployment or entity-authority activation in these workflows.

## Manual operator checkpoint

Complete this private setup record before enabling deployments; do not paste
secret values into issues, commits, logs or chat. Provider/resource creation,
DNS, secrets and deployment execution require the operator's account access.
No subscription purchase is implied.

1. Select two independently configured Render image web services and their
   canonical HTTPS origins. Review `deploy/commercial/render.yaml` as an operator
   template, replace its bootstrap image tags with a tested immutable digest,
   and configure a Render private-GHCR credential with `read:packages` access.
   Validate the edited Blueprint through Render before syncing it. Disable
   Blueprint auto-sync; future syncs must preserve the selected release digest.
   Confirm geographically close Render/Neon regions and PostgreSQL 18 support.
2. Select a distinct Neon development endpoint and confirm the exact binding of
   the retained UAT endpoint approved above for staging.
   Preserve its deployed forward revision chain and existing synthetic UAT
   records. Production/recovery endpoints are excluded. Separate roles/secrets
   are required for each environment; shared Neon project administration/capacity
   remains a documented stage limitation. Use direct, unpooled URLs with
   `sslmode=require`. Follow [PostgreSQL operations](POSTGRESQL.md) for runtime
   DML privileges versus a separately held migration role with schema ownership.
3. Record each endpoint fingerprint using the existing opaque identity contract
   (`host`, port and database; credentials do not participate). Set the matching
   `TABULA_RASA_DEPLOY_DATABASE_SHA256` in both Render and the GitHub environment.
   This binds the intended target and does not prove provider isolation. Do not
   infer a target from a filename, production branch name or legacy profile.
4. For a new **blank** endpoint only, run the image's explicit migration command
   with `--bootstrap`. It refuses a database containing public tables or an
   unknown retained revision. Current retained endpoints use `migrate` without
   this flag. Run `seed` once to add `alpha-synthetic` and its zero-balance
   `Deployment connectivity` account. The seed uses the existing entity/account
   services in one transaction and refuses an existing fixture; inspect rather
   than delete/reset an existing fixture. Nothing seeds/migrates on API startup.
5. Generate a separate nonempty operator password hash per environment with
   `python -m tabula_rasa.http.alpha` (hidden password prompt). In each Render
   service set the runtime URL, endpoint fingerprint, public origin, environment,
   fixed trusted entity, username and hash. Use a small pool (template: two
   connections, zero overflow) and account for both services, tests/migrators and
   provider connection limits. Never inject the migration-role URL into Render.
6. Create GitHub environments named `development` and `staging`, restrict their
   deployment branches to main, and use reviewer protection where available.
   Configure the following separately in each environment. The repository-wide
   `COMMERCIAL_DEPLOY_ENABLED` variable stays unset/false until both are ready.
7. Record the selected plan/capacity, cold-start/idle-suspension behavior, monthly
   limits and billing headroom. Free tiers are permitted for this technical
   stage when the real persistent topology fits those limitations; they do not
   promise continuous availability or commercial recovery. Use continuously
   available capacity when the intended usage requires it. Provider selection
   remains Render/Neon; no SQLite or in-memory staging substitution is supported.

| GitHub environment variable | Value |
| --- | --- |
| `RENDER_SERVICE_ID` | Exact service ID for this environment |
| `TABULA_RASA_PUBLIC_ORIGIN` | Exact canonical HTTPS origin, no trailing slash |
| `TABULA_RASA_ACCESS_MODE` | Explicit `restricted_alpha` or `named_user`, matching Render; missing/unknown stops verification before migration |
| `TABULA_RASA_DEPLOY_DATABASE_SHA256` | Approved target fingerprint |

| GitHub environment secret | Custody/use |
| --- | --- |
| `TABULA_RASA_MIGRATION_DATABASE_URL` | Migration container step only |
| `RENDER_API_KEY` | Render deployment API step only; authorized workspace access |
| `TABULA_RASA_ALPHA_USERNAME` | This environment's temporary operator gate |
| `TABULA_RASA_ALPHA_PASSWORD` | Smoke runner only; Render receives its scrypt hash |

The workflow's short-lived `GITHUB_TOKEN` pulls the private package and reads CI
evidence. Render keeps a separately configured registry read credential. Render
stores `TABULA_RASA_ALPHA_PASSWORD_HASH`, never a browser build constant.

Essential receipts additionally require a service-specific secret file at runtime,
selected through `TABULA_RASA_ALPHA_DOCUMENTS_FILE`. Follow
[Hosted synthetic receipt storage](ALPHA_DOCUMENT_STORAGE.md) for the exact
TOML contract, independent staging grant/root and read-only preflight. The API
image includes the existing Drive client's `requests` dependency and runs in
group 1000 to read Render's runtime secret mount. Keep Drive grants out of
GitHub deployment/gate credentials and browser assets. This optional binding
does not alter database promotion or authority policy; configured invalid
bindings stop startup, while absent bindings leave receipts unavailable.

To compute the non-secret binding from an explicitly exported URL (without
loading `.env.local`), run from root:

```powershell
python -c "import os; from tabula_rasa.infrastructure.postgres.config import DatabaseSettings; from tabula_rasa.infrastructure.postgres.runtime import Database; from tabula_rasa.infrastructure.postgres.identity import database_identity; db=Database(DatabaseSettings.from_environment(dict(os.environ),required=True)); print(database_identity(db)); db.dispose()"
```

For initial operator setup, export the migration URL as
`TABULA_RASA_DATABASE_URL`, the approved fingerprint and the environment into
the process. Run the exact tested image (represented by `$releaseImage`):

```powershell
docker run --rm -e TABULA_RASA_DATABASE_URL -e TABULA_RASA_ENVIRONMENT -e TABULA_RASA_DEPLOY_DATABASE_SHA256 $releaseImage python -m tabula_rasa.deployment.database migrate --bootstrap
docker run --rm -e TABULA_RASA_DATABASE_URL -e TABULA_RASA_ENVIRONMENT -e TABULA_RASA_DEPLOY_DATABASE_SHA256 $releaseImage python -m tabula_rasa.deployment.database seed
```

Omit `--bootstrap` for retained current-schema targets. Remove the migration
credential from the operator shell after setup. Ordinary pytest requires its
separate disposable administrator URL; never point the test suite at retained
Neon staging/production. The one-time fixture is synthetic and deployment-wide,
not a migrated business or an authority switch.

## Named identity rollout (#321)

[ADR 0003](adr/0003-commercial-identity-and-tenancy.md) selects ZITADEL hosted
OIDC plus durable opaque PostgreSQL sessions. [Commercial identity](COMMERCIAL_IDENTITY.md)
owns the approved provider/callback/mail/recovery contract. Named login,
membership enforcement, switching and entity-owned connections are implemented.
[Authenticated rollout](AUTHENTICATED_ROLLOUT.md) owns the operator setup,
retained-staging rehearsal, named-image rollback and cross-EPIC handoff.
[#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321) records current
hosted provider results and outstanding acceptance. The setup and Blueprint above
describe restricted synthetic alpha; they remain supported with explicit
`TABULA_RASA_ACCESS_MODE=restricted_alpha` in Render and GitHub. Named promotion
uses `named_user` in both and injects no Basic credentials. Follow the rollout
checklist to remove synthetic settings and provision separate named credentials
and grants. Lasting owner use and external beta retain their independent gates.

## Ingress, alpha access and session boundary

Render terminates HTTPS and owns external HTTP-to-HTTPS routing. Confirm that
boundary at setup, including custom DNS/TLS and canonical Host handling. The
container port is reachable through Render ingress; do not expose an additional
public bypass listener. Uvicorn has `proxy_headers=False`: X-Forwarded-For,
X-Forwarded-Host and X-Forwarded-Proto never grant authorization, change trusted
scope or relax Host/Origin checks. The application uses configured HTTPS origin
for policy, not the internal hop's scheme. Its minimal probes accept internal
health-check Hosts; private paths require the exact configured Host.

Restricted-alpha hosted development/staging refuses startup without explicit HTTPS,
`alpha-synthetic`, an operator username, a valid scrypt password hash, direct
TLS database URL and matching endpoint binding. HTTP Basic protects shell,
assets, API, documents and schema paths; only minimal health/version probes are
public. Hosted responses, including compiled assets, use `Cache-Control: no-store`
so shared caches cannot bypass the gate. Empty passwords are rejected by both
the hash generator and authentication boundary. Password verification runs
outside the async request loop with at most two gate workers per process;
public probes bypass those workers. Unsafe requests still require
exact Origin and the shared context's
CSRF token. The browser receives the fixed synthetic entity, never a scope
override. Different environment credentials and connections remain independent.
Secrets and private request/draft data never enter safe HTTP error/log output.

This temporary gate uses browser HTTP Basic authentication and a process-lived
synthetic CSRF context. It issues no commercial session cookie. #222 owns the
ADR's host-only HttpOnly/Secure/SameSite cookie, durable sessions, memberships
and revocation, now implemented by #312–#319; production rejects alpha
credentials/context entirely. Restrict the temporary runtime to trusted synthetic
use. Hosted mode must be explicit; missing named configuration never falls back.

## Promotion, failure and rollback

[#340 incident response](INCIDENT_RESPONSE.md) provides severity/ownership,
containment, safe diagnostics and cross-provider recovery decisions. Its
[controlled staging drill](INCIDENT_DRILL.md) reuses this lifecycle and preserves
the named-mode, schema and uncertain-deployment boundaries below.

The ordered lifecycle is mode/image verification -> bound `current`/`upgrade`/`health`
in a separate migration container -> Render digest deployment -> readiness ->
real browser smoke. Restricted-alpha smoke checks gate restrictions, release identity,
deep-link/static/error routing, session scope and the rendered synthetic account
read from PostgreSQL. It creates no new records, retains no traces/screenshots,
and records only safe release metadata. Repeat a successful staging promotion
and retain both workflow-run/digest references as repeatability evidence.
Named smoke instead verifies the public sign-in shell and anonymous/forged-Basic
denial without provider login or private reads; readiness verifies DB connectivity.
It does not complete the named hosted rehearsal. Results identify `access_mode`.

Current automation supports releases whose deployed schema is already the
image's head. Unknown/old revisions stop before migration; there is no stamp,
reconsolidation or automatic downgrade. A future schema-changing release must
first implement/test a compatibility bridge (old and target revisions), or use
a reviewed maintenance/drain runbook. The bridge cannot be enabled by a wildcard
environment variable. Ordinary `upgrade` remains the #220 forward-migration
owner, and startup/readiness never run it. Bootstrap is manual and initial only.

### Reviewed staging bridge: 0012 to 0014 (#321)

The manual **Staging 0012 to 0014 maintenance** workflow is a narrowly scoped
exception for the reviewed retained-staging transition. It does not change
ordinary promotion's head-only rules. Its image is pinned to release
`ea8c2de39a171a4010c821edc8648dbf241cd3dd`, index
`sha256:4bb275f4dc8475bc08ee45d32b3648d4fc33f03c823e3cf3a0c001a9a9bf0c3d`.
It cannot select another image, environment, source revision or target schema.

1. Obtain explicit maintenance approval. Privately verify an isolated staging
   recovery checkpoint, its source, time and retention, and preserve Google-grant
   and identity configuration custody separately. Record its SHA-256 for the
   workflow. The hash records operator attestation; it does not independently
   verify provider recoverability. Reconfirm checkpoint currency before execution.
2. Reserve the staging window and suspend/drain the exact Render staging service.
   Keep it suspended through migration and first-image selection. Do not allow
   concurrent provider changes outside the shared deployment lock.
3. Dispatch the maintenance workflow on `main` with approval `0012_to_0014` and
   the private checkpoint record's SHA-256. Preflight verifies the exact tested
   main release/schema, approved staging binding, suspended service and absence
   of in-progress deployments. The migration step alone receives the existing
   GitHub staging migration secret; the Render/GitHub tokens are not passed into
   that container. No credential is extracted to an operator workstation.
4. The approved immutable container checks the source is exactly
   `0012_operations` and reuses the canonical locked forward upgrade to
   `0014_document_locations`. An unexpected or already-upgraded source stops;
   inspect state before any retry. It does not reset, stamp, seed, downgrade,
   enable accounting policies or activate connections. Both revisions are
   forward-only. A failure leaves service state untouched and requires inspection.
5. After successful schema health, manually select the same approved digest and
   resume/deploy it using the retained named-user settings. Verify provider index
   and runtime digest, readiness, version and named anonymous smoke. Do not resume
   the old schema-0012 image or attempt an incompatible rollback.
6. With a compatible image live, run ordinary **Promote commercial staging** for
   its serialized verification record, then continue named-user acceptance.
   Maintenance success alone is not login, receipt, recovery or #321 acceptance.

This workflow does not suspend, resume or deploy services and does not fetch
private business data. It must run only within the separately approved operator
window. A new schema transition requires its own reviewed procedure.

Image verification uses authenticated Buildx registry descriptors to distinguish
the requested OCI index (or Docker manifest list) from its single `linux/amd64`
runtime manifest. It pulls and inspects that immutable platform manifest for
release/schema labels and OS/architecture; attestation and other-platform
digests do not qualify. A direct image manifest is also supported. Promotion
continues to submit the operator's original immutable digest to Render.
Both Render `image.ref` and `image.sha` must identify that digest or its verified
runtime manifest in the configured repository. A SHA is accepted only as
`sha256:` plus 64 lowercase hexadecimal characters or the same 64 characters
without the prefix. Missing, malformed or unrelated metadata stops before smoke
or automatic recovery; a Live status or matching `/version` alone is insufficient.

Before deployment, the tool finds the current live Render image and verifies
its immutable `image.ref`, its registry relationship to `image.sha`, pullability
and matching schema head. Rollback retains this verified reference instead of
constructing a pull reference from Render's SHA. A prior tag-only or unverifiable
deployment stops before a new deploy: inspect it and pin the verified retained
release by immutable digest through the operator procedure first.
A live restricted-alpha candidate whose smoke fails is replaced by that prior compatible digest
and checked with the same registry/Render integrity comparison before smoke.
The workflow still fails, preventing claims of promotion
success. An initial deploy with no prior image stops for operator inspection.
Render terminal deployment failure stops; inspect the retained previous live
deployment. An uncertain POST, poll failure or timeout stops for inspection
without retrying the deploy or racing it with rollback.
Named smoke failure stops for operator inspection rather than restoring an older
auth implementation automatically. Follow the [named-mode rollback checklist](AUTHENTICATED_ROLLOUT.md#compatible-application-rollback-and-incidents),
keeping named access and forward schema throughout.

### Index and runtime digest verification

An OCI image index and its selected platform runtime manifest can have distinct
digests. Validate the registry index-to-platform relationship and compare the
provider's resolved runtime image as well as its requested reference. Accept only
that proven relationship; unrelated and attestation digests must still fail.
Keep the exact index/runtime/release/schema evidence for each promotion.
[#279](https://github.com/Roklion/Project_Tabula_Rasa/issues/279) records the
original diagnosis and completed hosted promotion; old image IDs or a local
readiness observation cannot validate a new release.

For manual recovery of bad application code, inspect the exact service's current
deploy/status, select its retained schema-compatible image and dispatch that
digest through the staging workflow. Development automation deliberately refuses
superseded main images; a manual development rollback instead selects the exact
retained compatible digest in the Render Dashboard, after pausing automatic
development promotion. Verify readiness/release and run
`python -m tabula_rasa.deployment.smoke --release EXPECTED_SHA` with this
environment's explicit access mode and origin exported privately (alpha smoke
also needs its credentials). Named rollback additionally requires the reviewed
auth/epoch compatibility checklist above. Resume automatic
development promotion only after a validated corrective main release exists.
Do not change/delete bookkeeping records as rollback. If the
schema is incompatible, stop, restrict traffic/drain writers and use #220's
reviewed forward repair or [recovery guide](POSTGRESQL_RECOVERY.md). Database
restore/PITR and commercial recovery acceptance stay with #223/#298.

## Hosted evidence and technical-alpha handoff

After operator setup and explicitly authorized publishing/deployment, record
safe dev/staging origins, target fingerprint references, image digest/SHA/head,
successful ordered migration and browser smoke runs, repeated promotion,
and a controlled compatible application rollback under #288. Verify runtime DML versus
migration-role privilege separation and actual provider ingress/gate behavior.
Keep target credentials and private evidence private. Free-tier limits must be
part of that record. #279's reachable dev/staging, retained PostgreSQL and hosted
smoke acceptance are recorded in its closed issue. Refresh the selected alpha
candidate's evidence and use [#288's release contract](TECHNICAL_ALPHA.md) for the
complete workflow suite, real document binding, rollback rehearsal and manual
acceptance. #279's completion does not complete #288, retire Streamlit or activate
commercial production.

## Operational telemetry

[Operational observability](OBSERVABILITY.md) owns #332's sanitized contract,
optional collection setup, tier/retention/access checkpoint, alert thresholds,
staging smoke and #223 integration responsibilities.
