# Authenticated hosted rollout (#321)

This is the integration/handoff procedure for [#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321),
under [identity EPIC #222](https://github.com/Roklion/Project_Tabula_Rasa/issues/222)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Reuse the existing Render/Neon runtime, ZITADEL/Authlib adapter, durable sessions,
membership resolver, tenant connections and browser scope boundary. This adds no
identity system, migration engine, ledger authority mode or recovery backend.

**Current evidence boundary, October 16, 2026:** repository rollout support and
the operator checklist are prepared. The operator reports that the staging
ZITADEL client/fixtures are not configured. No hosted named login, provider
recovery, staging promotion, outage or rollback rehearsal is claimed. #321's
hosted acceptance remains pending; #320's remaining hosted recovery item also
remains pending. Do not mark either complete from the deployment smoke alone.

Reuse map: `http/config.py` owns mode validation; `deployment/release.py` owns
immutable promotion, provider uncertainty and schema compatibility;
`deployment/alpha.py` owns the existing core journey. These owners are extended.
The new anonymous named smoke differs from alpha because its shell is public
and its private requests must deny; it shares the promotion lifecycle and does
not duplicate authentication, accounting, session or recovery logic.

**Login defect follow-up (#395, October 19, 2026):** #321 now records later
operator-hosted results separately from the historical October 16 boundary
above. A retained provider browser profile exposed a silent callback failure
despite clean-profile success. The repository recovery path explicitly requests
provider reauthentication and reports safe failure categories/request references;
[named-user triage and the retained/clean rehearsal](NAMED_USER_AUTH.md#retained-provider-sessions-and-safe-failure-recovery-395)
own the procedure. The original hosted rejection boundary and updated-release
recovery remain unverified. Keep #395 and #321's affected acceptance open until
approved hosted evidence is recorded. Cookie deletion is not rollout acceptance,
and this fix does not satisfy unrelated #321/#222/#224/#124 gates.

## Stage and access policy

| Stage | Required access and ownership |
| --- | --- |
| Restricted technical alpha | Explicit `restricted_alpha`, Basic gate and fixed `alpha-synthetic`; only trusted operators and synthetic data. Existing #288 evidence remains historical evidence for its exact release. |
| Named fixture staging | Explicit `named_user`, separate staging ZITADEL client, durable sessions and freshly authorized membership before ledger/document composition. No Basic credentials, trusted context or legacy alpha document configuration. |
| Lasting owner use | Normal named authorization plus approved existing entity/document bindings from #319. #303 owns all three live profiles, required workflows, source freeze, execution permission and accepted recovery limits. |
| Unrelated external beta / production | Named mode plus #224 admission approval, applicable #222 functionality and #223 recovery/security/legal gates. Production refuses alpha mode. A free provider plan does not relax identity or tenant controls. |

“External” here means admitting unrelated users, not simply having a public
HTTPS endpoint protected for synthetic alpha. Never admit them to an alpha
deployment. Hosted startup and promotion require an explicit access mode; an
absent mode fails before runtime allocation or promotion migration. Named mode
rejects synthetic configuration and cannot fall back when provider settings
are absent. Loopback development/test retains its fixture default.

## Private operator configuration record

Complete one record **per environment** before changing retained staging. Record
exact values privately, with a sanitized reference/digest in the handoff. No
production provider project or callback is selected by this repository change.
Do not substitute example domains for an approved exact callback.

| Record / setting | Custodian and placement |
| --- | --- |
| ZITADEL instance/region/plan, project ID and confidential Web client ID | Identity operator; separate staging and production projects/clients and fixture/customer users. Record administrative MFA, recovery factors/mail, plan limits and service dependency. |
| `TABULA_RASA_OIDC_ISSUER`, `TABULA_RASA_OIDC_CLIENT_ID` | Identity operator -> Render server environment. Exact HTTPS issuer and environment's client. |
| `TABULA_RASA_OIDC_CLIENT_SECRET` | Identity operator -> Render secret injection only. Web application uses `client_secret_basic`, authorization code and S256 PKCE. No browser build or Actions smoke credential. |
| `TABULA_RASA_PUBLIC_ORIGIN`, callback | Deployment operator -> Render and matching GitHub environment variable. Exactly `<canonical HTTPS origin>/api/v1/auth/callback`, no wildcard, alternate host or trailing slash. Record actual DNS/TLS/ingress ownership. |
| `TABULA_RASA_ENVIRONMENT`, `TABULA_RASA_ACCESS_MODE` | Deployment operator -> Render; matching GitHub environment variables for promotion. `staging`/`named_user` for this rehearsal; `production`/`named_user` for separately approved production. |
| `TABULA_RASA_SESSION_GENERATION` | Security operator -> separate random Render secret per environment, at least 32 characters. Cookies are opaque: there is **no cookie signing key**. Generation plus durable configuration epoch is the session-wide rotation boundary. |
| Runtime DB URL / migration DB URL / endpoint fingerprint | Database operator. Render gets only the runtime DML URL; Actions migration step gets only its separate migration secret. Reconfirm retained staging endpoint and roles using #279's binding procedure. Production uses a distinct approved target. |
| Connection directory/key and Google grants | Connection operator -> private runtime mount and `TABULA_RASA_CONNECTION_SECRETS_DIR` / `TABULA_RASA_CONNECTION_SECRETS_KEY`. Separate per environment; follow [tenant connection provisioning](EXTERNAL_CONNECTIONS_AND_LEGACY_CLAIMS.md). ZITADEL tokens are never Google grants. |
| Image/index/runtime digests, schema and CI run | Release operator. Retain a verified named-capable rollback image and compatible configuration/epoch record. Record current release before maintenance. |
| Recovery owner, maintenance window, fixture-write consent, accepted provider limitations | Operator's private execution decision. Restrict ingress while configuring/fault testing. No owner data cutover or beta admission is authorized by this checklist. |

Use [Named-user authentication](NAMED_USER_AUTH.md) for cookie flags, deadlines,
OIDC verification and configuration rotation. Use [Commercial identity](COMMERCIAL_IDENTITY.md)
for the approved provider/threat model. Verify current provider console settings
and limitations at execution time; no provider account, DNS, secrets or paid
features are provisioned by the application.

## Prepare and promote retained staging

1. Pause overlapping automatic promotion and reserve the existing staging
   deployment lock/window. Retain current release/data/receipt references and
   the private configuration record. Do not run ordinary pytest against staging.
   The Blueprint remains a **restricted-alpha template**; do not resync it over
   named settings. Alpha stays available only on separately restricted fixtures
   if the operator elects to retain it.
2. In the selected staging ZITADEL project configure the confidential Web client,
   exact callback, verified-email policy, Basic client authentication and S256
   PKCE. Provision safe named fixture accounts through the provider. Verify MFA
   enrollment, recovery mail/factors and a separately controlled administrator.
   Do not reuse production users, secrets, Google grants or source data.
3. Apply reviewed forward migrations with the existing explicit toolchain and
   separate migration role. Current promotion automation refuses a retained
   schema older than the candidate head. Use #220's maintenance/forward migration
   procedure for that transition, including the first-release procedure below.
   A prior image with an older schema label also stops normal promotion even
   after migration. Never bootstrap/reset/stamp/downgrade retained staging.
4. Set Render's named settings above. Remove `TABULA_RASA_TRUSTED_ENTITY_ID`,
   `TABULA_RASA_ALPHA_USERNAME`, `TABULA_RASA_ALPHA_PASSWORD_HASH` and
   `TABULA_RASA_ALPHA_DOCUMENTS_FILE`; do not transplant its deployment-wide
   document binding. Establish named entity-owned grants through #318 instead.
   Set the GitHub staging variable `TABULA_RASA_ACCESS_MODE=named_user` and
   remove unused staging alpha smoke secrets. Development may remain explicitly
   `restricted_alpha` with independent credentials and its matching variable.
5. For an existing named environment whose issuer/client/secret/origin/generation
   changes, drain workers and perform the documented compare-and-swap
   [configuration-epoch rotation](NAMED_USER_AUTH.md#revocation-and-owner-recovery).
   First named startup initializes only an empty identity environment; it never
   assigns existing entities, seeds a ledger or replaces an existing epoch.
6. After separately authorized publication, choose the immutable image with
   successful **main-push Full test suite** evidence. Dispatch **Promote commercial
   staging** on main. The existing workflow verifies main/image identity, runs
   bound migration, deploys, verifies Render digests and runs mode-specific smoke.
   Named promotion receives no alpha credentials. A missing/unknown mode stops
   in verification before the migration step.
7. Named smoke checks readiness (including PostgreSQL), exact release, denied
   anonymous/forged-Basic private API/schema access, routing and the rendered
   Sign in link. It starts no provider login and reads no private ledger. Its
   `smoke_passed` result includes `access_mode`; **it does not prove successful
   login, membership, documents or provider recovery**. Continue below.
8. Create two synthetic organizations and at least two businesses using the
   existing named onboarding/invitation flow. Use independent fixture Owners,
   an overlapping member and a Read-only member. Unknown first-login users must
   have no access to retained alpha/owner entities. Claim an existing synthetic
   fixture only through #319's separately approved exact binding procedure.
   Stage and confirm each entity's independent Google receipt grant using #318.

### First named release from an older alpha schema

The retained #288 release used schema `0005_bookkeeping_cutover`; named identity
adds forward revisions. Do not expect the ordinary head-only promotion workflow
to bridge that gap: it deliberately rejects both an old live schema and a prior
image whose schema label differs. An already current-schema alpha deployment
can use the ordinary promotion path, with named settings applied in maintenance.

For the older-schema case, the operator must authorize this specific maintenance
transition. Drain the old application/writers and restrict ingress, preserve
the retained database/receipt recovery point, and verify the selected candidate's
main CI and immutable metadata with `deployment.release verify`. In that exact
candidate image, with **only the approved staging migration URL** injected,
validate its endpoint fingerprint using the existing `open_alpha_database`
binding helper before any upgrade. This helper accepts staging and direct Neon
TLS; it does not seed or alter data. Then run the existing CLI, stopping on any
failure:

```text
python -m tabula_rasa.infrastructure.postgres current
python -m tabula_rasa.infrastructure.postgres upgrade
python -m tabula_rasa.infrastructure.postgres health
```

Keep the commands in the bound candidate container, with explicit process
environment and no local `.env.local` fallback. Follow [PostgreSQL migration
policy](POSTGRESQL.md#schema-versions-and-migration-policy) to review the revision
chain, role privileges and recovery plan before execution. Remove the migration
credential from the operator process afterward. Startup cannot perform this work.

Apply the named settings/epoch steps above and manually select the verified
candidate digest in the exact Render staging service. Check its image reference
and resolved runtime SHA against the retained registry metadata, readiness and
version, then run named deployment smoke. Preserve the maintenance result
privately. With the current live image now at the same schema head, run ordinary
**Promote commercial staging** for the candidate to obtain the serialized
registry/Render verification and repeatable promotion record. Keep ingress
restricted until named fixture acceptance succeeds. An older alpha image is no
longer a rollback candidate; the first named release has no prior named-image
rollback until a compatible second named release is retained. Record that
limitation; do not conceal it with a schema downgrade or synthetic access.

The old **Technical alpha staging gate** is restricted to `restricted_alpha` by
a runner preflight before release checkout and by runner configuration. The
environment-specific variable is checked after the job starts, following
[GitHub's environment-variable availability rules](https://docs.github.com/en/actions/reference/workflows-and-actions/variables#configuration-variable-precedence).
Do not feed it named cookies,
remove that guard or re-enable Basic just to obtain a green run. Reuse its
[six-case accounting/document workflow matrix](TECHNICAL_ALPHA.md#exact-default-workflow-matrix)
as the workflow evidence checklist on named fixtures; add the identity cases
below. The existing native identity/workspace/security suites own regression
coverage; this handoff does not introduce a second accounting matrix.

## Hosted rehearsal and expected results

Run in the approved fixture window; retain only sanitized outcomes and private
evidence references. Use isolated browser contexts for users A and B, desktop
and mobile, and the #288 engines/viewports for the retained core workflow matrix.
Keep cookies, HARs, traces, screenshots with personal information, callback URLs,
recovery codes and raw responses out of GitHub and application/request logs.
Use browser developer tools privately when needed, without persistent recordings.

| Check | Expected result / stop condition |
| --- | --- |
| Login and provider contract | Named fixture completes exact callback, code/PKCE/Basic exchange, verified subject/email, MFA and session issuance. Privately verify Secure, HttpOnly, SameSite=Lax, Path=/ and no Domain on `__Host-tabula_*` cookies. No tokens in application URLs or storage. In a provider-approved isolated protocol test, bad verifier/client secret is refused; do not alter retained runtime secrets to perform it. |
| Fresh membership and role binding | A sees only permitted businesses; direct B entity/account/entry/document/export paths deny before private composition. Read-only can read authorized resources and cannot mutate/upload/administer. Forged body/header/cookie/entity choices grant nothing. Use supported financial CSVs; complete export/backup remains separately privileged. |
| Core bookkeeping/documents | Execute #288's existing matrix after named login: accounts, entries, stale forms, reports, upload/link/exact bytes/unlink/relink. Record per engine/viewport. Verify the other organization's records/receipt bytes are unchanged. Unlink retains the Drive file; uncertain operations stop for inspection. |
| Switch and persistence | Switch between A's permitted businesses, reload and restart the application without DB reset. Authorized selection, persisted fixture records and exact receipt bytes survive. Prior business drafts, queries, uploads, record IDs and receipt URLs are cleared; B's session remains independent. |
| Membership change/revoke | Remove a non-last-owner fixture member or change its role through the existing Owner/Admin UI. Subsequent reads/writes/bytes deny or reflect reduced rights; refresh/open tabs clear stale scope. If another permitted business remains, only that authorized scope is selected. Never remove the last active Owner as a test shortcut. |
| Logout / two users | Confirm logout response, then refresh/back and sign in as B in the same browser. No A metadata, drafts, financial rows, downloads or receipt links render. Other open tabs clear A's scope. A copied old session privately replayed after logout must deny. Provider SSO logout is separate; new login requires fresh authentication. |
| Session expiry / revoke-all | Verify idle expiry after 30 minutes without activity and absolute expiry at 12 hours, or retain an authorized time-controlled isolated rehearsal reference. Revoke-all invalidates already-issued copies across tabs/workers/restart; B remains authorized. Never change server clocks on shared staging or claim an unobserved deadline passed. |
| Credential/configuration rotation | Retain an already-issued fixture session, drain workers, rotate generation/configuration epoch through the canonical command, restart all workers. Old sessions fail and old-config workers cannot issue sessions. Pair provider password/MFA reset with app revocation; provider reset alone does not revoke local sessions. |
| Provider failure/recovery | In a controlled isolated staging window, make the provider unreachable through approved network controls. New login fails safely without fallback; no callback/session material in errors. Existing valid durable sessions may continue until local expiry/revocation with fresh membership checks: provider availability is not checked on every request. Restore connectivity and require a new login attempt. Test real recovery mail/factors before sign-off. |
| Database/session-store outage | Separately authorized controlled interruption denies private reads/writes/bytes and removes browser private views. Local logout can clear cookies but reports unavailable when durable revocation is unconfirmed. Restore, reconcile/revoke uncertain sessions and verify recovery. Do not report local clearing as server-wide revocation. |
| Synthetic bypass / missing configuration | Public named API denies anonymous and legacy Basic/synthetic cookies. Missing OIDC setting or unsupported/missing mode fails safely without synthetic fallback. Exercise configuration faults on an isolated process with synthetic settings; do not expose a permissive retained deployment for a negative test. |
| Safe observability | Correlate fixed `login_started`, `login_succeeded`, `login_failed`, `identity_denied`, `authorization_denied`, `logout_succeeded` and `user_sessions_revoked` events with safe request IDs. Verify no emails, provider subject, tokens, cookie values, callback query, raw provider response, SQL, receipt/ledger contents or connection IDs in request logs. Uvicorn access logs remain disabled; verify proxy/provider logging separately. #332 owns sink/retention/alerts. |

Any failed/uncertain mutation is inspected once before a deliberate safe retry;
no blind repeat, broad fixture cleanup, byte deletion or simulated rollback.
Operator/provider outage and multi-worker checks need explicit environment/window
authorization and actual infrastructure evidence. The current Render entrypoint
uses one worker; do not claim multi-worker execution from one-worker restart.

## Compatible application rollback and incidents

Named smoke failure stops promotion with operator guidance and **does not
automatically redeploy an older image**. Matching ledger schema alone cannot
prove auth/configuration-epoch compatibility. Restrict ingress, inspect the
confirmed Render deployment and identity state, and select the retained reviewed
**named-capable** image. Keep named mode and all authorization guards enabled.
Never restore an alpha image or synthetic resolver for owner/external users.

Rehearse rollback in a controlled staging window: retain named fixture session,
records, selected business and receipt byte digest; promote the compatible prior
named image through the existing digest workflow; verify deployment smoke and
the applicable identity/record/byte checks; re-promote the candidate and repeat.
Keep the forward schema and retained data. No schema downgrade, source reload,
database restore or deletion is part of an application-image drill. If auth
configuration changed, follow explicit epoch rotation and expect fresh login;
do not restore old signing/generation material to resurrect sessions. If no
compatible prior named image exists, record that limitation and use reviewed
forward repair rather than claim a rollback rehearsal succeeded.

For a compromised session, revoke the affected user's sessions, suspend affected
membership if needed and confirm copied credentials fail on all workers. For
configuration/provider compromise, drain workers and rotate the environment epoch
and affected secrets, coordinate provider recovery, then verify old/new worker
behavior before reopening. Preserve the last-active-owner/recovery boundary;
there is no synthetic in-app break-glass identity. #223 owns incident custody and
restored-session invalidation; #303/#298 retain independent recovery authority.

## Sanitized acceptance record and handoff

For each executed check record **pass, fail, pending or not applicable with a
reason**, date/tester, exact release SHA, image/index/runtime digests, schema,
main-push CI URL, promotion/restart/rollback references, engine/viewport,
safe request IDs and a digest/reference to private configuration/fixture evidence.
Record actual provider region/plan, suspension/quotas, MFA/recovery/mail limits,
session/connection key custody and currently available recovery. Unknown or
unexecuted checks remain pending. No fixture identity, email, secret, cookie,
grant, financial contents or private evidence file belongs in the public record.

| Handoff owner | Evidence to deliver; boundary preserved |
| --- | --- |
| #288 / #221 | Named access overlay plus original matrix results for the selected candidate. Historical restricted-alpha acceptance is not new named evidence; Streamlit retirement scope is unchanged. |
| #320 / #222 | Actual hosted login/session/membership/recovery/failure and bypass outcomes, unresolved risks, exact revision. Repository/synthetic tests do not complete hosted acceptance. |
| #319 / #303 | Verified normal authorized resolver and fixture entity/document binding contract. No actual owner claim, three-profile migration, authority activation or accepted recovery decision is executed here. |
| #223 / #332 / #337 / #338 / #342 | Safe event observations, provider limits, grant/key custody and outstanding telemetry/byte recovery/capacity evidence. No NAS, monitoring delivery or managed storage recovery is claimed. |
| #224 / #298 | Applicable identity evidence and explicit gaps including #317/#315, operational recovery, legal/privacy, support and provider security/recovery limitations. Only those owners may admit unrelated users or authorize commercial activation. |

Keep #321 open until its hosted criteria have evidence, and #222/#124 open until
their independent exit criteria are satisfied. Publishing this guide or passing
deployment smoke authorizes none of the remaining live operations.

## Repository verification

Run from the repository root in its declared Python 3.12 development environment:

```text
python -m pytest tests/http tests/test_oidc.py tests/tooling/test_named_rollout.py tests/tooling/test_commercial_deployment.py tests/tooling/test_technical_alpha.py tests/tooling/test_release_images.py tests/tooling/test_ci_workflow.py -q
python -m pytest tests/postgres/test_identity_http.py tests/postgres/test_authorization_http.py tests/postgres/test_security_acceptance.py tests/postgres/test_identity_browser.py tests/postgres/test_workspace_browser.py -q
python -m ruff check .
python -m pip check
npm --prefix web run build
git diff --check
```

The second command requires the compiled browser, installed Chromium and an
explicit disposable `TABULA_RASA_TEST_DATABASE_URL`; set
`TABULA_RASA_REQUIRE_BROWSER_TESTS=1` so missing prerequisites cannot skip the
native gate. Never set it to retained staging/production. The named smoke is
exercised against real HTTP guards and the compiled browser/disposable
PostgreSQL; deployment failures use synthetic Render/registry responses.
Current-revision hosted **Full test suite** remains the publication/review gate,
separate from these affected checks and the pending real-provider rehearsal.
