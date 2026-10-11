# Commercial identity: operator gates and implementation handoff (#310)

[ADR 0003](adr/0003-commercial-identity-and-tenancy.md) selects ZITADEL Cloud
hosted OIDC login, server-owned PostgreSQL sessions and application-owned
organization memberships/roles for
[#222](https://github.com/Roklion/Project_Tabula_Rasa/issues/222) under
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Read its role, session and immutable-context contract before implementing a
child ticket. This guide owns the operator checklist, threat acceptance cases
and handoff. **Selection is documented; real identity is not implemented or
hosted-verified by #310.**

## Stages and migration boundary

| Mode | Allowed identity/data boundary | Exit or transition requirement |
| --- | --- | --- |
| Local development/test | Existing explicit loopback synthetic fixtures, or fake OIDC/disposable PostgreSQL tests. Real OIDC development uses a dedicated nonproduction client and separately named non-Secure loopback cookies. | Keep fixture injection unavailable on public hosts; no production secrets or private books. |
| Hosted restricted technical alpha (#279/#288) | Existing TLS Basic gate, fixed synthetic operator/entity and independently authorized synthetic document binding. No unrelated users or live customer/owner books. | Retain [technical-alpha gates](TECHNICAL_ALPHA.md) and [alpha document setup](ALPHA_DOCUMENT_STORAGE.md); no identity prerequisite for this bounded stage. |
| Lasting owner-operated use (#299/#303) | Named verified user, durable session and active Owner membership in explicitly bound existing entities. Normal authorized resolver, accepted authority/document bindings. | #319/#321 as applicable plus #303's own operator acceptance/cutover; no synthetic login or blanket all-profile authority. Invitations/billing/full commercial #298 sign-off need not precede trusted internal use. |
| Unrelated external beta (#224) | Named MFA-protected sessions, server membership enforcement, invitation/onboarding and verified tenant/document/connection isolation. | Applicable #311–#321 evidence, #223 recovery/operations and #224 legal/release approval. Free provider plans never waive these gates. |
| Paid launch | Same named identity/security contract plus accepted customer lifecycle, capacity/support and operational guarantees. | #224/#298's separate launch and recovery agreement; identity completion alone is insufficient. |

Legacy Streamlit remains within its existing restricted deployment-wide-password,
profile-scoped Sheets/Drive boundary. Do not weaken its password, administrator
reauthentication, loopback-only OAuth or backup rules. Do not retrofit a second
Streamlit commercial ACL system for #13. #222 replaces that security model in
the new runtime; disposition of #13 follows verified replacement.

Named login does not migrate books or claim all configured profiles. #319's
explicit dry-run/apply maps an approved internal user/org to existing canonical
entity IDs and authorized document/connection bindings, preserving acceptance,
provenance and rollback boundaries. #303 alone owns actual private/live cutover.
No new session or identity provider can silently activate PostgreSQL authority
or restore stale Sheets after target divergence.

#312/#321 must introduce an explicit access mode contract:
`restricted_alpha` versus `named`; missing/unknown mode denies startup.
Production only permits `named`. Named mode rejects every alpha credential,
trusted entity, synthetic resolver and alpha-only document configuration,
including on hosted development/staging. Existing `HttpSettings` currently
requires alpha configuration on hosted dev/staging: extend that validation for
named mode, rather than relaxing the existing alpha branch or labelling it
commercial login. The settings names below are a **future implementation
contract**, not instructions that make today's runtime authenticate users.

## Manual provider/secret/mail checkpoint (#312/#315/#321)

Preparation of code/tests does not require live credentials. An operator must
authorize provider creation/configuration, secret installation, fixture accounts
and any paid plan before hosted execution. No resources were provisioned by
#310. Record actual settings and recovery custody privately; public evidence
uses synthetic names, safe statuses and release/check IDs only.

1. Verify actual ZITADEL plan/region, available instance/client/admin quotas,
   rate limits, MFA/recovery capabilities and accepted availability.
   [Current pricing detail](https://zitadel.com/pricing/detail) lists one
   Free instance and one administrator. Never assume two free production and
   staging instances or a support SLA. If required isolation/recovery cannot
   fit the account, stop at this setup checkpoint for an owner decision about
   capacity/spend; do not share production configuration or change provider
   silently.
2. Establish distinct **production and nonproduction instances/issuers**,
   administrator credentials, user populations and secrets before lasting
   owner/live use. Nonproduction local/staging may share an instance with
   separate projects/clients and synthetic users. No staging credential, grant,
   callback, fixture user or session database is valid for production.
   Instance separation protects login/recovery policy as well as client secrets.
3. Create a project and **Web OIDC application** for each environment, using
   code flow with S256 PKCE and `client_secret_basic`: choose **Basic Auth**
   for the Web client's authentication method; FastAPI separately sends the S256
   challenge/verifier. Do not choose the public-client **PKCE** (`none`) option.
   Verify the combined exchange and wrong-verifier/wrong-or-missing-secret
   rejection as described in [ADR 0003](adr/0003-commercial-identity-and-tenancy.md).
   Use hosted login rather than operating a custom login service. Verify discovery issuer/JWKS,
   configured signing algorithm support and the mandatory UserInfo request:
   with the default code-flow client, its subject must match the validated ID
   token and its email must be nonempty with boolean `email_verified=true`.
   Do not depend on optional email claims inside the ID token. Do not configure provider organization
   roles as application bookkeeping permissions.
4. Register only exact origins/URLs in the table below. No wildcard callbacks,
   transient preview hosts or forwarded-host construction. Keep same-origin
   browser/API, CORS disabled and narrow server endpoint allowlists. A local
   HTTP callback exception belongs only to its dedicated development client.
5. Use native email/password with verified email and enforced TOTP/WebAuthn
   MFA policy for named hosted users. Exercise enrollment, verification,
   lockout, lost-factor and password-reset flows with synthetic accounts.
   Social/enterprise identity, SMS recovery and app-stored passwords are outside
   this first release. Keep at least one independent recovery factor for the
   operator, with recovery material in the approved private vault.
6. Configure and verify a mail sender/domain/provider for production identity
   verification and password recovery, with separate staging delivery and
   recipient restrictions. ZITADEL's built-in SMTP is evaluation-only; test
   mail is not production recovery evidence.
   [Provider mail and security settings](https://zitadel.com/docs/guides/manage/console/default-settings).
   Test domain verification/delivery and failure handling before lasting owner
   use/external beta. Mail credentials remain in provider/server secret stores.
7. Install approved OIDC settings/secrets through Render/environment secret
   injection. Keep them out of image builds, `VITE_*`, source, OpenAPI, query
   state, telemetry, shell history and PR/test artifacts. Verify host-only
   Secure/HttpOnly/Lax session/login cookies and all unsafe Origin/CSRF checks.
8. Rehearse local session revoke/user suspend and provider recovery together.
   Document who holds provider admin access and how it is recovered within the
   actual plan's administrator limits. A provider admin is not automatically a
   Tabula Rasa Owner. No shared-password or synthetic break-glass login to books.
9. #321 runs synthetic hosted login/logout/revoke/switch/document/export tests,
   records exact release, schema and sanitized outcomes, and coordinates #288.
   Follow [deployment promotion](COMMERCIAL_DEPLOYMENT.md) for immutable image,
   compatible rollback and secret custody. No schema downgrade, live migration
   or external admission is implied by that rehearsal.

| Future setting / registration | Contract and owner |
| --- | --- |
| `TABULA_RASA_ACCESS_MODE` | #312/#321: explicit `named` or `restricted_alpha`, with the fail-closed stage rules above. |
| `TABULA_RASA_PUBLIC_ORIGIN` | Existing exact origin, e.g. synthetic `https://stage.example.test`; loopback development uses `http://127.0.0.1:5173`. No path/trailing slash. |
| `TABULA_RASA_OIDC_ISSUER` | #312: exact operator-approved environment issuer; use its verified discovery endpoints, never a browser-selected URL. |
| `TABULA_RASA_OIDC_CLIENT_ID` / `TABULA_RASA_OIDC_CLIENT_SECRET` | #312: dedicated environment Web client; secret is server-only and hidden in settings repr/errors. |
| Registered callback | `PUBLIC_ORIGIN + /api/v1/auth/callback`; local callback goes through Vite's `/api` proxy. |
| Registered post-logout URI | `PUBLIC_ORIGIN + /signed-out`; optional provider logout uses client ID/state, not a token URL. |
| Session/login persistence | #311/#312: environment's existing PostgreSQL database, opaque credential hashes and durable login transactions. No session signing key, refresh token or new credential database is needed. |
| Mail/recovery custody | Provider-admin-owned SMTP credentials and factor recovery; #315 owns application invitation delivery, #223 owns operational secret rotation/incident evidence. |
| Google/document secrets | #318: authorized organization/entity connection secret reference, independent of OIDC settings. Existing alpha document secret files remain synthetic-alpha-only. |

These names must be validated and documented as implemented in #312/#321,
rather than silently becoming optional fallbacks. Provider client-secret
rotation interrupts new logins until configured coherently; verified app
sessions retain their ordinary deadlines unless explicitly revoked.
Issuer/client changes require reauthentication and explicit binding migration;
never remap existing users by email. Restoring PostgreSQL/control-plane state
must invalidate restored sessions/login transactions before ingress reopens
(#223): restored revoked credentials must not become live again.

## Invitation and ownership policy (#315/#316)

For the first restricted beta, select **operator-distributed invitations**:
an authorized Owner/Admin creates a recipient-bound, single-use, 256-bit
invitation credential with a 48-hour expiry; an authorized management view
displays it once. The inviter delivers it privately to the intended recipient,
who signs in and pastes it into an authenticated acceptance form. Do not put
the credential in a URL, provider `state`, browser storage or logs. This keeps
the first app slice independent of an outbound email service; it does not
replace production identity verification/recovery mail. Automated invitation
email can be added by #315 after its own sender/delivery checkpoint.

Store only the invitation credential hash, organization, recipient email,
role, inviter and lifecycle. Acceptance requires a freshly provider-verified
email from login within five minutes matching the intended address; never a
client-supplied email. Define email comparison as trimmed, case-insensitive
comparison with **no** plus-tag/dot rewriting. It is an invitation recipient
check, not user identity or automatic account linking. If fresh authentication
is needed, discard the submitted invitation credential and ask the recipient
to paste it again after login. Do not retain the raw credential in process
memory, login transactions, cookies or other pending workflow state; the
durable invitation record retains only its hash and lifecycle.

Transactionally check current inviter/acceptor authority, invitation expiry/
revocation and permitted role, consume once and create/reactivate the unique
membership. If the inviter lost invitation/grant authority, deny acceptance.
Existing active membership acceptance is idempotent and never silently
upgrades a role. Owners may issue Admin invitations; Admins may issue only
Editor/Accountant/Read-only, and Owner assignment uses the separate ownership
action. Deny replay and cross-organization use. Pending invites grant no
discovery/document access. Preserve last-owner rules and safe 403 responses.

First-use workspace creation binds the signed-in internal user as Owner.
#316 reuses LedgerSetupService/#252 defaults within the supported database
transaction/idempotent bootstrap; #317 shows start-fresh versus the explicitly
separate #258/#303 operator migration. Account creation alone confers no access
to any preexisting workspace. A user with no memberships remains in the
authenticated `needs_setup` state, able to log out, accept an invitation or
create their own workspace.

## Threat model and required acceptance cases

Trust boundaries are browser → same-origin API → control-plane/ledger database;
API → configured identity issuer; and authorized entity → DocumentStore/
external secret store. Assume attacker-controlled URLs, bodies, headers,
cookies, localStorage, client roles, known foreign IDs and old valid sessions.
Provider, host/operator secret compromise and browser XSS remain real
operational risks: HttpOnly does not stop malicious same-origin code issuing
requests. Preserve #223 secret/logging controls and #287 browser hygiene;
do not claim this ADR proves those mitigations.

Use at least two independent organizations/users, two entities, a multi-org
accountant, all five roles and retained preexisting entities. The cases below
are requirements for downstream executable tests, **not tests delivered in #310**.

| ID / attack | Required observable result | Primary owner |
| --- | --- | --- |
| T01: anonymous, forged/tampered, expired, revoked or wrong-environment cookie | Private APIs/bytes deny 401 before any ledger/document/secret composition; safe request ID, no credential/private echo. Valid fresh login succeeds and persists across worker/restart. | #312/#320 |
| T02: wrong issuer/audience/algorithm/signature/nonce/state, reused code, unverified email or stale auth_time | No app session/membership created; concurrent callbacks consume at most once. Default code-flow login succeeds using mandatory UserInfo with matching subject and verified email; missing/malformed email claims, false email_verified, subject mismatch or UserInfo failure deny login. Changed email never takes over an existing internal identity. | #311/#312 |
| T03: forged entity in route/body/header/selection cookie | Uniform safe 403 for foreign/missing/inactive ownership; no existence leak, services or grants bound. An authorized selector succeeds only after server validation. | #313/#320 |
| T04: role value or provider role claim changed by client | Server's current role matrix wins. Read-only cannot mutate/upload/import/export; it can read permitted receipts, inspect session, switch and log out. Unknown action/role denies. | #313/#314 |
| T05: member demoted/removed, user disabled or org suspended with an open session | Next protected request after committed change denies/reduces authority. Version changes replace browser scope on its next check; visible tabs recheck within 60 seconds/focus. Other authorized orgs remain independently accessible. | #313/#315/#314 |
| T06: foreign document ID/store key, unlinked receipt, import/export/job target | Every metadata/byte/connection access qualifies the authorized entity; no ID-only byte path or global credential fallback. Test permitted upload/download/export as well as denials. Jobs recheck scope at execution. | #313/#318/#320/#223 |
| T07: session fixation, stolen old cookie or callback replay | Login replaces/revokes old session, new CSRF/cache ID; single-use login transaction. Copy of revoked cookie denies on another worker after restart. | #312 |
| T08: missing/foreign/null Origin, missing/wrong CSRF, redirect/forwarded-Host spoof | Every unsafe command denies before effects, including logout/switch/bootstrap/invite; only state/nonce-bound callback is exempt. No open redirect, wildcard client, token URL or caller-selected issuer fetch. | #312/#313 |
| T09: provider timeout/unknown JWKS key/mail failure | No new/unverified login, silent fallback or bypass of idle/absolute expiry. Valid existing local session follows ADR deadlines and fresh local authorization; provider-only recovery does not claim app revocation. | #312/#321 |
| T10: database/authorization outage or uncertain logout | Safe 503 and private view unmounted; no cached allow/fixture fallback. Origin/CSRF-valid logout clears the local cookie even on DB failure; a copied cookie is not claimed revoked until DB confirmation. Fresh login and authenticated revoke-all/operator recovery succeed when service returns. | #312/#313/#321 |
| T11: Admin self-promotion, owner removal/demotion races or provider-admin claim | Admin grant limits enforced; at least one active Owner or explicitly suspended org. Test concurrent last-owner changes and user-disable effects in real PostgreSQL. | #311/#315 |
| T12: replayed/expired/revoked/wrong-recipient invite or inviter loses authority | No unauthorized activation/role escalation. Correct verified recipient accepts once, duplicate submission creates no duplicate membership. Existing-member acceptance does not promote. Stale authentication requires fresh login and credential re-entry, including when a different worker handles acceptance; no pending raw credential is retained. | #315 |
| T13: bootstrap retry/foreign org, arbitrary claim of old profile/entity | Acting user owns only their new workspace; no duplicate defaults/org or unauthorized legacy claim. #319 explicit mapping preserves original entity/book IDs and independent grants after restart. | #316/#319 |
| T14: account/entity switch, revoked tab, slow prior-scope response, logout → another login | Cancel queries/unmount drafts/uploads, revoke object URLs, clear selections; old responses never populate a new ScopeBoundary. No private persistent browser cache. Successful permitted multi-org switching remains usable. | #312/#314/#317/#320 |
| T15: production/external accidentally configured alpha; restored session replay; unsafe rollback | Reject synthetic/Basic/development cookie configuration, reject restored sessions before ingress, and never roll external deployment back to an alpha bypass image. Safe schema-compatible named-session rollback is rehearsed. | #312/#321/#223 |
| T16: private route added without policy; privileged valid request bypasses baseline/accounting checks | Route inventory test requires declared identity/capability policy before composition on every private route/byte/export family. Authorized stale edits still fail; valid bookkeeping retains invariants. | #313/#320 |

Denials and assertions must use synthetic data. Captured logs/HTTP errors must
exclude email, authorization codes, cookies, provider tokens, invitation
credentials, connection secrets, SQL and bookkeeping contents. No live
provider credentials are required for CI. Provider-backed staging tests are
separate operator-authorized evidence, not mocked proof.

## Implementation handoff matrix

| Ticket | Consume/reuse | Deliver / dependency and evidence |
| --- | --- | --- |
| [#311](https://github.com/Roklion/Project_Tabula_Rasa/issues/311) | ADR identity, five roles and org-wide entity ownership; canonical business_entities and forward Alembic migrations | User/binding/org/member/entity association repository and lifecycle constraints; coordinate shared session/transaction persistence fields with #312. Native retained-data upgrades, uniqueness, isolation, last-owner tests. Can start alongside #312. |
| [#312](https://github.com/Roklion/Project_Tabula_Rasa/issues/312) | ADR provider, callback, cookie, 30-minute/12-hour lifetime; existing app/runtime/context/session/ScopeBoundary seams | Provider adapter, durable transactions/sessions and revoke, safe needs_setup/ready DTO/client generation, login/logout UX and named-mode validation. One shared session validator; no entity needed to authenticate. Integrate #311 mappings; tests T01/T02/T07/T08/T09/T10. |
| [#313](https://github.com/Roklion/Project_Tabula_Rasa/issues/313) | #311/#312 and central context/service binding | Explicit action policy covering all API/document/import/export/admin families; fresh membership-derived RequestContext, uniform denials, route guard and baseline compatibility. Core external-beta security gate; start #320 scaffolding here. |
| [#314](https://github.com/Roklion/Project_Tabula_Rasa/issues/314) | #312/#313, ContextBoundary/ScopeBoundary and entity query keys | Authorized org/entity discovery/selection, identity-operation CSRF, revocation/focus checks and cross-tab cleanup. Test slow old-scope results and Read-only switching. |
| [#315](https://github.com/Roklion/Project_Tabula_Rasa/issues/315) | #311/#313 role/last-owner contract; #312 fresh login/session revocation | Recipient-bound operator-distributed invites, lifecycle/role administration, local suspend/revoke recovery procedure. Separate mail checkpoint if automating invitations; native concurrent tests. |
| [#316](https://github.com/Roklion/Project_Tabula_Rasa/issues/316) | #311/#313 authenticated bootstrap; #252 LedgerSetupService/defaults | Idempotent workspace/first-entity creation by acting user, additional entity:manage check, no copied ledger default logic. Success/failure/retry/isolation native tests. |
| [#317](https://github.com/Roklion/Project_Tabula_Rasa/issues/317) | #312/#316 and #314 shell; #315 acceptance when available | needs_setup to first ledger journey; start-fresh separated from operator migration. Optional invite/connection steps only when ready. Browser recovery/accessibility/cache evidence. |
| [#318](https://github.com/Roklion/Project_Tabula_Rasa/issues/318) | #311/#313 connection capability; existing profile-scoped Google OAuth and DocumentStore | Authorized org/entity metadata + protected secret references, bind before bytes, safe connect/status/revoke. Login tokens never replace Google grants; object-store selection/recovery stays #223. |
| [#319](https://github.com/Roklion/Project_Tabula_Rasa/issues/319) | #311/#313 and #318 as relevant; existing migrated authority/entity-profile binding | Explicit approved legacy ownership dry-run/idempotent mapping with two-profile/native restart evidence. No remigration or live execution; #303 consumes result. |
| [#320](https://github.com/Roklion/Project_Tabula_Rasa/issues/320) | Start with #313 policy; complete alongside covered slices | Execute T01–T16 with real disposable PostgreSQL + HTTP/browser, route inventory, synthetic safe evidence/gap register. Provider-hosted cases require #321 checkpoint; #224 decides beta. |
| [#321](https://github.com/Roklion/Project_Tabula_Rasa/issues/321) | #312–#314/#320 plus stage/provider checklist, Render/Neon release path | Named synthetic-user staging, cookie/login/logout/revoke/switch/bytes/export/outage and compatible rollback evidence. Reject alpha in named mode; coordinate #288/#303/#223/#224 without authorizing their unfinished gates. |

The safe order is decision → #311/#312 → #313 → independent #314/#315/#316/
#318/#319 slices → #317 and integrated #320/#321. Backend/schema analysis and
test scaffolding can overlap; not every Wave 3 ticket blocks beginning staging
integration. No child invents a different cookie, role or authorization model.

## Evidence and outstanding decisions

#310 supplies the ADR, capability policy, executable-test requirements and
operator/handoff contract. Local documentation/link validation and regression
checks verify consistency with existing seams, not real authentication or
tenant safety. Normal affected-check and current-revision CI/review policy
remains in [Development](DEVELOPMENT.md).

Outstanding operator work is explicit: provider accounts/region/plan and
separate instances, approved secrets/callbacks, verified MFA/recovery/mail,
fixture users and #321 hosted rehearsal. Maintainer review accepts the role
distinctions, org-wide membership and bounded session policy before downstream
merge. #223 still owns document durability, secret/incident operations and
revocation after recovery restores; #224/#298 still own external release,
privacy/legal and recovery guarantees. None are marked completed by this ADR.
