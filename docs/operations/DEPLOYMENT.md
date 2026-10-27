# Development and staging deployment

The same-origin React/FastAPI image deploys to Render with a scoped Neon database.
This guide owns environment bindings, ordered schema migration, immutable-image
promotion, smoke checks and compatible rollback. [Runtime](../browser/RUNTIME.md)
owns packages and topology; [named-user rollout](../identity/HOSTED_ROLLOUT.md)
owns hosted identity verification. Cutover, disaster recovery and commercial
activation require their separate approvals.

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

Closed [deployment evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/279)
records hosted development/staging acceptance on October 9, 2026, including retained
Neon UAT and successful [staging
promotion](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/37951248477). The
setup instructions below remain the operator contract for new/reconfigured environments.
Local native tests and a local container prove implementation only. Technical-alpha
validation's complete core workflow/real-provider receipt gate, compatible rollback
rehearsal and manual-device evidence remain separate in [Technical
alpha](../browser/RELEASE_VALIDATION.md). On October 8, 2026, the operator approved
reuse of the existing retained UAT database for staging. Confirm its exact endpoint
binding, current forward schema and runtime/migration role custody before connecting the
commercial service; this approval does not authorize overwriting its existing records. A
read-only check of the locally configured direct Neon target on that date confirmed
`0005_bookkeeping_cutover`, matching this release's schema head. Its local URL included
unsupported `channel_binding`; remove that option when copying the URL into deployment
secrets, as documented in PostgreSQL operations. The check normalized the URL in memory
and changed no files or database records. Enable `COMMERCIAL_DEPLOY_ENABLED=true` only
after the checkpoint below. There is no production deployment or entity-authority
activation in these workflows.

## Manual operator checkpoint

Complete this private setup record before enabling deployments; do not paste
secret values into issues, commits, logs or chat. Provider/resource creation,
DNS, secrets and deployment execution require the operator's account access.
No subscription purchase is implied.

For owner-operated migrated profiles, the standard image additionally accepts
`TABULA_RASA_MIGRATED_BINDINGS_FILE`, pointing to private server-mounted binding
metadata. Follow [the owner runtime configuration](../accounting/CUTOVER.md#container-configuration-for-migrated-owner-profiles)
and the existing named-user/tenant-grant setup. Use the explicit migrated binding
path for owner-operated migrations; the ordinary native workspace runtime does not establish their
source/authority/document acceptance. This configuration changes neither the
separate staging service nor the commercial activation policy.

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
   `sslmode=require`. Follow [PostgreSQL operations](../database/POSTGRESQL.md) for runtime
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
[Hosted synthetic receipt storage](../storage/STAGING_RECEIPTS.md) for the exact
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

## Named identity rollout

[ADR 0003](../adr/0003-commercial-identity-and-tenancy.md) selects ZITADEL hosted OIDC
plus durable opaque PostgreSQL sessions. [Commercial
identity](../identity/PROVIDER_SETUP.md) owns the approved
provider/callback/mail/recovery contract. Named login, membership enforcement, switching
and entity-owned connections are implemented. [Authenticated
rollout](../identity/HOSTED_ROLLOUT.md) owns the operator setup, retained-staging
rehearsal, named-image rollback and cross-handoff. [hosted identity
rollout](../identity/HOSTED_ROLLOUT.md) records current hosted provider results and
outstanding acceptance. The setup and Blueprint above describe restricted synthetic
alpha; they remain supported with explicit `TABULA_RASA_ACCESS_MODE=restricted_alpha` in
Render and GitHub. Named promotion uses `named_user` in both and injects no Basic
credentials. Follow the rollout checklist to remove synthetic settings and provision
separate named credentials and grants. Lasting owner use and external beta retain their
independent gates.

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

This temporary gate uses browser HTTP Basic authentication and a process-lived synthetic
CSRF context. It issues no commercial session cookie. identity and tenancy owns the
ADR's host-only HttpOnly/Secure/SameSite cookie, durable sessions, memberships and
revocation, now implemented by named-user authentication and existing entity claims and
local administration; production rejects alpha credentials/context entirely. Restrict
the temporary runtime to trusted synthetic use. Hosted mode must be explicit; missing
named configuration never falls back.

## Promotion, failure and rollback

[incident response](INCIDENT_RESPONSE.md) provides severity/ownership, containment, safe
diagnostics and cross-provider recovery decisions. Its [controlled staging
drill](INCIDENT_DRILLS.md) reuses this lifecycle and preserves the named-mode, schema
and uncertain-deployment boundaries below.

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

Current automation supports releases whose deployed schema is already the image's head.
Unknown/old revisions stop before migration; there is no stamp, reconsolidation or
automatic downgrade. A future schema-changing release must first implement/test a
compatibility bridge (old and target revisions), or use a reviewed maintenance/drain
runbook. The bridge cannot be enabled by a wildcard environment variable. Ordinary
`upgrade` remains the PostgreSQL persistence forward-migration owner, and
startup/readiness never run it. Bootstrap is manual and initial only.

### Retired staging bridge: 0012 to 0014

The one-time retained-staging bridge completed its approved forward upgrade and
compatible-image promotion. The [protected maintenance run](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39187928399)
and [staging handoff evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/321)
preserve the source/target revisions, immutable image and recovery-checkpoint
reference. The dedicated `commercial-staging-maintenance.yml` workflow and
`staging_maintenance` command are retired. Do not dispatch or reuse historical
revisions for another upgrade; each new transition requires a reviewed procedure.
Canonical Alembic revisions and the ordinary forward-upgrade CLI remain intact.

The support-schema command below owns its recovery-checkpoint and suspended-service
guards. Migration tests independently preserve two-business ledger/isolation and
disabled-accounting-policy checks from `0012_operations` to the current head.
Bridge-specific pinned-image and workflow tests retired with the single-use entry point.

Restricted-alpha routes, synthetic contexts and their deployment/tests remain
supported independently. A named staging handoff does not retire those callers.
Streamlit/Sheets writers and owner migration, conversion and recovery paths retain
[controlled cutover](../accounting/CUTOVER.md) and capability-specific retirement
conditions. Bridge cleanup supplies no live-cutover or deletion authority.

### Reviewed support-schema maintenance: 0014 to 0015

The manual **Support schema 0014 to 0015 maintenance** workflow supplies the
missing transition for the existing development and staging services. Ordinary
deployment still refuses old schemas, even when a service is stopped. API startup
never migrates. Suspending Render alone therefore does not unblock a failed run.
The workflow reuses the canonical forward migration; it introduces no new schema,
support grants, bookkeeping writers, scheduler, production target or downgrade.

First publish/review this procedure through the normal current-revision CI gate.
Use an immutable image from its successful main-push CI and image-build job,
containing this maintenance module and schema `0015_support_controls`. Its release
must equal the main revision on which the maintenance workflow is dispatched.
An overall release workflow may have a successful build and a later development
migration failure; inspect the separate jobs rather than treating that as a failed
image build. Do not rerun an old release or use a tag-only reference.

1. Select **development** first for the reported failed automatic deployment.
   Run the manual workflow with operation **inspect**, approval **not_approved**,
   and that exact image. This connects through the existing environment-scoped
   migration secret, checks the bound target and reports only the schema.
   It performs no upgrade and does not require suspending the service.
   Production is excluded; repeat separately for staging when ready.
2. If the result is `0014_document_locations`, reserve the exact environment's
   maintenance window. Privately verify a current recovery checkpoint for that
   target, its source/time/retention and the retained runtime/identity/connection
   configuration. Record the recovery evidence SHA-256. This is operator
   attestation, not automatic proof the provider can restore it.
3. Suspend/drain that exact Render service in Settings. Stop other approved
   writers or provider changes to the same target for the window. Keep the
   service suspended and avoid changes outside the shared deployment lock.
4. Dispatch operation **upgrade**, approval **0014_to_0015**, with the same
   verified image and recovery-record hash. Preflight refuses a running service
   or pending deployment. The database container receives only its own bound
   migration credential, not the Render/GitHub access tokens. It requires source
   exactly 0014, runs the canonical locked forward upgrade and confirms 0015.
   Already-upgraded, unknown or failed/unconfirmed outcomes stop for inspection;
   do not repeat blindly or resume the old app.
5. Have the database administrator verify the existing runtime role's effective
   grants described in [Support operations](SUPPORT.md): SELECT on
   support_grants/support_actions and INSERT on support_actions, with no grant
   administration, audit mutation or table ownership. The new workflow does not
   broaden role permissions or create a support operator.
6. While suspended, select the same tested schema-0015 image in Render, preserving
   existing mode, runtime secrets and connection files. Resume/deploy it; verify
   both provider digest metadata and public version/readiness. This first image
   selection is manual because ordinary promotion deliberately rejects a
   schema-0014 prior image as rollback-incompatible. Never resume/revert to that
   old image after upgrading the database.
7. Once the compatible image is live, rerun the ordinary latest-main development
   release deployment, or **Promote commercial staging** for staging, to obtain
   its guarded deployment and mode-specific smoke record. Do not use an obsolete
   failed main release if main has advanced. Recheck named-user/security events
   and retained synthetic data through the existing hosted identity rollout and operational observability checks.

If a step fails, preserve the checkpoint and logs, leave an incompatible service
suspended and inspect the exact state before deciding on forward repair or an
isolated recovery. No automatic rollback to schema 0014 is supported. The workflow
does not suspend, resume, deploy or change secrets itself; its default inspection
can be performed while the current app is running. Upgrade execution, downtime,
recovery attestation and provider image selection remain explicit operator steps.

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
auth implementation automatically. Follow the [named-mode rollback checklist](../identity/HOSTED_ROLLOUT.md#compatible-application-rollback-and-incidents),
keeping named access and forward schema throughout.

### Index and runtime digest verification

An OCI image index and its selected platform runtime manifest can have distinct digests.
Validate the registry index-to-platform relationship and compare the provider's resolved
runtime image as well as its requested reference. Accept only that proven relationship;
unrelated and attestation digests must still fail. Keep the exact
index/runtime/release/schema evidence for each promotion. [deployment
evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/279) records the
original diagnosis and completed hosted promotion; old image IDs or a local readiness
observation cannot validate a new release.

For manual recovery of bad application code, inspect the exact service's current
deploy/status, select its retained schema-compatible image and dispatch that digest
through the staging workflow. Development automation deliberately refuses superseded
main images; a manual development rollback instead selects the exact retained compatible
digest in the Render Dashboard, after pausing automatic development promotion. Verify
readiness/release and run `python -m tabula_rasa.deployment.smoke --release
EXPECTED_SHA` with this environment's explicit access mode and origin exported privately
(alpha smoke also needs its credentials). Named rollback additionally requires the
reviewed auth/epoch compatibility checklist above. Resume automatic development
promotion only after a validated corrective main release exists. Do not change/delete
bookkeeping records as rollback. If the schema is incompatible, stop, restrict
traffic/drain writers and use PostgreSQL persistence's reviewed forward repair or
[recovery guide](DATABASE_RECOVERY.md). Database restore/PITR and commercial recovery
acceptance stay with platform operations and commercial recovery agreement.

## Hosted evidence and technical-alpha handoff

After operator setup and explicitly authorized publishing/deployment, record safe
dev/staging origins, target fingerprint references, image digest/SHA/head, successful
ordered migration and browser smoke runs, repeated promotion, and a controlled
compatible application rollback under the selected hosted rollout procedure. Verify
runtime DML versus migration-role privilege separation and actual provider ingress/gate behavior.
Keep target credentials and private evidence private. Free-tier limits must be part of
that record. deployment's reachable dev/staging, retained PostgreSQL and hosted smoke
acceptance are recorded in its closed issue. Use
[Release validation](../browser/RELEASE_VALIDATION.md) for the preserved workflow matrix and automated journey boundaries, and [named-user hosted
rollout](../identity/HOSTED_ROLLOUT.md) for current provider, rollback and manual
acceptance. The synthetic hosted acceptance runner is retired; development promotion,
authenticated read-only smoke, target binding, migrations and image verification remain
supported.
deployment's completion does not complete technical-alpha validation, retire Streamlit
or activate commercial production.

## Operational telemetry

[Operational observability](OBSERVABILITY.md) owns the sanitized telemetry contract,
optional collection setup, tier/retention/access checkpoint, alert thresholds, staging
smoke and platform operations integration responsibilities.

## Stage-specific operational readiness

The release operator assembles an evidence matrix before changing the supported
stage. Keep dated results, acceptance checkboxes and approval references in the
owning operational discussion, not in this guide. Record the exact selected
release, schema, topology, target binding and observation time for every result.
Main CI, an image build, a deployment record and an observed running service are
distinct evidence. A later main commit does not refresh an earlier live drill.

| Minimum | Restricted synthetic technical alpha | Trusted owner-operated bookkeeping | Unrelated external beta / commercial production |
| --- | --- | --- | --- |
| Access and scope | Explicit synthetic scope and protected ingress; named mode or the supported restricted gate; no unrelated customer admission | Named owner, exact authorized business/document bindings, fresh membership and cross-business denial; preserve divergent PostgreSQL authority | Selected-release named identity, business roles, revocation and browser isolation; usable account/admin recovery before admission |
| Recovery | Explicitly accepted synthetic loss/availability limits; distinguish DB and document-byte coverage and disclose unperformed checks | Achieved PostgreSQL protection plus separate byte archives, compatible metadata/links, retained source/history, owner custody and a usable recovery procedure | Accepted stage RPO/RTO, retention, capacity, recovery points, full-service boundaries and operator/escalation coverage, with independent alternate recovery when commercially required |
| Jobs | No timer is implied by a successful manual probe; approve each synthetic mutation/window separately | Exact business/time zone, bounded durable worker, observed scheduled execution and failure/remediation, missed-run/terminal monitoring and retained attempts | Representative selected-cohort operation, retry/deduplication and delivered incidents meeting accepted cadence/capacity; separately approved activation |
| Provider limits and privacy | Inspect effective region/tier/headroom/shared consumption, idle behavior, logging and grant limits; accept bounded technical gaps explicitly | Recheck those limits against actual owner workload, secret/key custody, alert recipient and backup-health responsibilities | Inspect selected provider and downstream/proxy/sink access/retention, usage eligibility, quota/cost headroom and incident response; free tiers pass only if achieved outcomes meet the accepted stage |
| Validation and approval | Current-revision authoritative CI/review plus applicable synthetic checks; no automatic release from a repository pass | Consume exact owner-cutover evidence and approved protection limits; operations work must not disturb the working owner service | Consume security and operations evidence; separate beta admission, commercial authority activation and paid-release decisions remain with their human release owners |

For each minimum, record: acceptance item; pass/fail/unperformed/not applicable;
immutable evidence URL and tested revision; actual resource/topology reference;
remaining work and dependency; responsible human/component owner; and explicit
stage approval or the exact missing decision. An owner named as the requested
approver is not evidence that they have accepted. Deferrals require scope, a
specific owning issue, responsible owner and completion/reconsideration trigger.
Do not waive an essential protection by labeling it cosmetic or deferring it to
paid launch when beta already needs it.

Inspect actual Render/Neon region, compute/tier, project-wide consumption,
connection budget, suspension/history and remaining capacity. Inspect selected
document storage headroom, effective Cloud project quota, grant lifecycle and
shared account/client failure boundary. Console values, operator attestations and
published limits must be identified separately; templates and account locality
do not establish effective settings. Provider purchases and configuration changes
retain their separate approval checkpoints.

Use [controlled drills](INCIDENT_DRILLS.md#dependency-and-job-drill-preflight)
for execution and [incident evidence](INCIDENT_RESPONSE.md#timeline-evidence-and-closure)
for sanitized handoff. Consume [hosted rollout](../identity/HOSTED_ROLLOUT.md#hosted-rehearsal-and-expected-results),
[observability](OBSERVABILITY.md#metrics-alerts-and-first-triage),
[job operation](JOBS_AND_AUDIT.md#operator-entrypoints-and-manual-hosted-checkpoint)
and [support](SUPPORT.md) at their proven scope. A configured alert is not a
delivered incident; email settings are not delivered email. Verify recipient
acknowledgment and actual recovery separately, including manually resolved job
incidents. Keep a real provider fault distinct from source tests or simulated logs.

### Recovery replacement and handoff

Before retiring a recovery capability, inventory its live, manual, test and
operator consumers. Classify each as retained, replaced and eligible, or deferred
to a specific issue with owner and trigger. Reuse the
[resource retirement procedure](RESOURCE_RETIREMENT.md); replacement evidence
must match the selected stage's guarantee, not just share a backup label.

Verify the [database restore](DATABASE_RECOVERY.md),
[audit history/protections](AUDIT_RECOVERY.md), and separate
[receipt archive/restore](../storage/RECEIPT_RECOVERY.md), including compatible
metadata/link identities, available recovery points, scoped credentials and key
custody. Database archives do not contain external receipt bytes. A manual byte
archive does not establish a document NAS scheduler, continuous protection or
alternate-operator recovery. Record the DB/bytes capture boundaries and any
unrecoverable interval; do not combine unrelated historical passes into a new
whole-service pass. Verify restored state before forward migration and apply the
canonical return-to-service/authority rules before any separately approved rebind.

Preserve archived divergent Sheets sources and disabled old writers, receipt
bytes, NAS generations/checksums and deployed schema history. Never reactivate
stale Sheets after PostgreSQL divergence. Capability retirement provides no data
disposal authority: each resource deletion needs its own exact-target approval.
Issue closure, technical handoff and recovery verification supply no beta,
commercial cutover or charging approval.
