# Named-user authentication and sessions

Named authentication uses hosted OIDC, server-owned PostgreSQL sessions and
application-owned memberships. [Provider setup](PROVIDER_SETUP.md) and
[ADR 0003](../adr/0003-commercial-identity-and-tenancy.md) define configuration
and security contracts. [Authorization](AUTHORIZATION.md) owns action policy;
[business onboarding](WORKSPACES.md) owns switching and onboarding. The Streamlit
administrator remains a separate loopback-only operator surface.
Provider-hosted acceptance and live migration require their own approved procedures.

## Explicit deployment configuration

Run the normal explicit PostgreSQL migration command before deployment. Startup
never migrates, seeds, assigns old entities, or copies ledger data. Identity
revisions 0006/0007 are forward-only; compatible recovery, not a destructive
downgrade, is the rollback boundary. Entity bookkeeping exports retain the
canonical v1 inventory and exclude identity records, sessions and credentials.

Set `TABULA_RASA_ACCESS_MODE=named_user`, `TABULA_RASA_ENVIRONMENT`,
`TABULA_RASA_PUBLIC_ORIGIN`, the normal database configuration, and:

- `TABULA_RASA_OIDC_ISSUER`: exact HTTPS ZITADEL issuer, without trailing slash.
- `TABULA_RASA_OIDC_CLIENT_ID` and `TABULA_RASA_OIDC_CLIENT_SECRET`: server-side
  confidential Web application configured with Basic Auth and S256 PKCE.
- `TABULA_RASA_SESSION_GENERATION`: random operator-managed value of at least
  32 characters; change it to invalidate all sessions/login attempts for this
  environment (including signing-key/security-policy recovery).

Production requires explicit `TABULA_RASA_ACCESS_MODE=named_user`; missing, unknown or
restricted-alpha mode fails configuration validation before runtime allocation. Never
set `TABULA_RASA_TRUSTED_ENTITY_ID` or alpha Basic credentials in named mode. Production
and named mode reject injected trusted-development contexts at the HTTP guard as well as
rejecting synthetic configuration. Restricted alpha remains a separate explicit fixture
mode; it grants no named membership. The migrated-runtime factory rejects a named
identity resolver unless named-user mode is explicit, before allocating a database. Use
separate provider clients, secrets and databases for each environment. Hosted startup
requires an explicit access mode even for restricted alpha; only loopback
development/test keeps the fixture default. The [authenticated hosted rollout
checklist](HOSTED_ROLLOUT.md) owns exact operator configuration records, promotion smoke
and release-specific verification. Register exactly `<public
origin>/api/v1/auth/callback` without wildcard URLs. HTTP settings canonicalize
scheme/hostname case and omit default ports before binding the Host guard, exact browser
Origin/CSRF check and OIDC callback. Non-default ports remain part of the origin;
foreign origins are still refused. Provider accounts, region/plan, MFA/recovery, mail
and authorized secret setup remain operator checkpoints. No provider resource is
provisioned by this code.

## Login and browser lifecycle

Signed-out, session-unavailable and workspace-setup-required views consume the shared
commercial headers, surfaces and native action controls. They retain the context
boundary's private-view removal, reload and sign-out behavior; workspace selection and
onboarding follow the [business lifecycle contract](WORKSPACES.md).

The infrastructure adapter uses pinned Authlib 1.7.2 (BSD-3-Clause, Python 3.10+)
and its joserfc 1.7.5 JOSE implementation. Authlib owns authorization-code/PKCE
request preparation, client authentication, bearer UserInfo requests and OIDC
claim validation. Each exchange owns a separate client; provider tokens are not
shared between users. The adapter retains bounded transport, issuer-host endpoint
restrictions and the application's freshness, subject and verified-email policy.
PyJWT is a development-only independent signer for synthetic provider tests.

An unauthorized private response clears private browser views but does not delete
shared authentication cookies: a delayed response may belong to a session older
than a login completed in another tab. Explicit login/logout transitions own
cookie replacement and deletion. Retaining a rejected cookie grants no authority;
every later request still validates its durable session.

`GET /api/v1/auth/login` starts a five-minute durable browser-bound one-time
transaction. Return paths are only `/`, `/onboarding` and `/invitations` (after forward migration
`0010_onboarding_routes`). The code callback
consumes it before exchange; failures require starting a new login. The server
prunes expired and consumed login transactions in the same environment when a
new login starts, including clients without a previous login cookie. Active
attempts and other environments are preserved. Successful session issuance also
prunes revoked sessions and sessions at their idle or absolute expiry boundary
in the same environment; active sessions and other environments are preserved.
Expiry and revocation are still enforced on every protected request, independently
of this cleanup. It checks signed RS256 identity,
issuer, audience/authorized party, nonce, fresh
authentication time, expiry and mandatory matching-subject verified-email
UserInfo. Discovery/JWKS/endpoints are restricted to the configured HTTPS issuer
host; response size, network timeouts and unknown-key refresh are bounded.
Provider tokens remain transient server-side and are never app credentials.

The server binds an immutable exact `(issuer, subject)` to a random internal user ID.
Equal or changed email addresses never link accounts. New users receive no organization
membership or preexisting business access automatically. Ownership associates with
existing canonical `business_entities`; it does not create an alternate ledger,
rebaseline records, or change cutover provenance. Repository operations are internal
trusted building blocks, not public administration endpoints. Callers must enforce the
[server action policy](AUTHORIZATION.md) and membership-administration safeguards before
invoking them. Forward revision `0008_owner_lock_scope` keeps organization-owner
serialization on user state updates/deletion, not login display-metadata or
revocation-epoch updates. Membership owner locks and deferred last-active-owner checks
remain. It changes no bookkeeping fields or portable-export inventory.

Hosted opaque session/login cookies use `__Host-tabula_session` and
`__Host-tabula_login`: Secure, HttpOnly, SameSite=Lax, Path=/, no Domain. Loopback
HTTP uses distinct `tabula_dev_*` names. A matching HttpOnly host-only CSRF copy
(`__Host-tabula_csrf`) permits Origin/CSRF-valid logout to clear cookies even
when PostgreSQL is unavailable. That copy grants no bookkeeping authority.
Other unsafe routes use the freshly validated session's synchronizer token.
Passive identity denials return no cookie deletion: a delayed 401 must not erase
a newer session installed by a successful callback. Stale cookies still fail
fresh server validation; explicit logout/revoke-all clear the browser cookies.
The failure screen retains only logout CSRF, not private session/entity data,
and offers Sign out. After an initial reload during an outage, the browser reads
`GET /api/v1/auth/logout-context` with `X-Tabula-Logout: 1` to obtain only this
cookie's logout token without querying authorization storage. This no-store,
same-origin-only read rejects foreign Origin/Fetch-Metadata and grants no access
or renewal; CORS remains disabled. The following logout POST still requires
exact Origin and matching CSRF. A network/server outage that prevents cookie
clearing is reported as unavailable, never as confirmed server revocation.

Only session credential hashes are stored. Sessions survive worker restarts,
expire after 30 minutes idle or 12 hours absolute, and are freshly checked on
each protected request. Background session checks do not extend idle lifetime.
Visible foreground pointer/keyboard activity sends a throttled CSRF-protected
activity request. Local logout does not terminate provider SSO; fresh login
requires `max_age=0` and explicit `prompt=login`. ZITADEL documents `login` as
requiring reauthentication / a user name in its
[authorization endpoint contract](https://zitadel.com/docs/apis/openidoauth/endpoints#authorization_endpoint).
The signed-token freshness policy remains unchanged: `auth_time` must be within
the preceding five minutes, with at most 60 seconds of future clock skew.
Provider reauthentication is requested on every new application login, including
the deliberate restart action; no provider cookie deletion or silent retry is
part of the normal flow.

### Retained provider sessions and safe failure recovery

An existing provider SSO session must satisfy the same state/nonce/PKCE, signed
token, freshness and matching verified-email UserInfo checks as a fresh browser.
An old provider session is not an application session. A failed callback returns
to the signed-out screen with a fixed category, a server-generated callback
request reference and **Sign in** to start a new transaction. No callback code
is exchanged twice; the screen never restarts login automatically. If the new
attempt also fails, contact the operator with that reference. An ordinary
`/signed-out` visit shows no spurious login-failure warning.

The safe `security_reason` categories distinguish the boundary that failed:

| Category | Operator investigation boundary |
| --- | --- |
| `login_start` | Transaction creation or provider discovery / authorization URL preparation |
| `login_transaction` | Missing, unmatched, expired, consumed or configuration-invalid browser transaction |
| `provider_authorization` | Provider returned an authorization error after transaction validation |
| `token_exchange` | Authorization code / confidential-client / PKCE exchange |
| `token_validation` | Missing/malformed token or signature, issuer, audience, nonce or claim validation |
| `login_freshness` | Verified signed authentication time outside the accepted window |
| `userinfo_validation` | UserInfo transport, subject or verified account details |
| `session_issue` | Local user resolution or durable session issuance |

Unavailable failures retain `failure_code=unavailable`; the screen explains the
temporary service failure. Categories identify rejection boundaries, not a
diagnosis of provider fault. Raw provider error names/descriptions are never
displayed, logged or reflected into the clean redirect.

Triage by the screen's request reference in the private application log sink,
then match stage, release, operation, failure code and `security_reason`.
`login_ref` correlates `begin_login` with `complete_login` when the existing
telemetry scope key is configured. Its source is a separate five-minute,
HttpOnly, host-only diagnostic reference cookie with the login cookie's flags;
the log contains only a domain-separated HMAC pseudonym. This reference grants
no authority and is cleared with the transaction cookie. A missing/altered
reference can affect diagnostics only, never transaction validation. Never
record cookies, codes, token/claim values, email, provider subject, callback
queries or screenshots/network exports containing them. Keep operational
incident notes and provider-specific investigation in approved private custody.

### Provider-backed verification

Signed synthetic provider, disposable PostgreSQL and compiled-browser tests cover
stale/fresh responses, one-shot failure, explicit recovery and two-user isolation. They
do not establish real provider SSO behavior.

For each selected hosted release, use authorized synthetic staging users to verify fresh
login and retained-session reauthentication, a controlled failed attempt followed by
explicit recovery, sign-out, session expiry and revocation. Test retained and clean
browser profiles without clearing site data. Record the exact release, safe request
references, failure categories and observed outcomes. If a check fails, inspect the
classified boundary privately; do not replay a callback or weaken validation. Deployment
and external admission require separate approval. The [login recovery
record](https://github.com/Roklion/Project_Tabula_Rasa/issues/395) contains historical
diagnosis, remediation and acceptance evidence.

`GET /api/v1/session` reports `ready` or authenticated `needs_setup`, without
composing ledger services for an unscoped user. Inspection, authorized entity
selection, activity, logout and revoke-all do not require bookkeeping-write
permission. The React boundary shows pending/sign-in/setup/failure states,
rechecks visible identity at least every 60 seconds and on focus/visibility/
pageshow, and unmounts private caches/drafts on authoritative loss or outage.
Confirmed scope changes remount the existing private query boundary; logout is
broadcast across same-origin tabs without private payloads. A received sign-out
invalidates pending session responses as well as an already loaded private scope,
so a late initial response cannot reopen a signed-out tab. Failed logout clears
the local cookie but reports 503 if durable revocation cannot be confirmed;
it does not claim a copied credential was revoked.

## Revocation and owner recovery

[Security incident
response](../operations/INCIDENT_RESPONSE.md#security-and-identity-incidents) defines
immediate-revocation incident classes; [secret
operations](../operations/SECRETS.md#named-identity-and-restored-session-revocation)
coordinates custody, worker drain, this epoch command and restored-session invalidation.
Provider recovery and local app revocation remain separate.

Membership roles are Owner, Admin, Editor, Accountant and Read-only. Role/state
changes increment the authorization version. Missing/inactive membership,
suspended organizations, inactive ownership, disabled users and unknown roles
grant no entity context for that business. If the selected business loses access
but another authorized business remains, validation persists an available
authorized selection and the browser replaces its private scope. Only users
with no available business receive needs_setup. Active organizations require an active Owner; native
deferred constraints and serialized organization locks protect role changes,
membership removals, user disable and reactivation. Transfer ownership first,
or explicitly suspend the organization before removing its last active Owner.

User disable changes that user's session epoch across every organization.
Credential changes/forced resets must call the trusted
`revoke_user_sessions(user_id)` operation before declaring local recovery
complete. An authenticated user can use CSRF-protected
`POST /api/v1/auth/revoke-all`; others' sessions are unaffected. Provider-only
password/MFA resets do not notify this app automatically. Coordinate local
revocation with provider recovery and verify that copied credentials fail;
ordinary session deadlines are not a substitute. If an external change cannot
be reconciled safely, suspend affected access until revocation is confirmed.

Issuer, client, client-secret, public-origin or session-generation changes require
explicit operator rotation of the durable environment epoch. Startup initializes an
empty environment or validates its existing configuration; a mismatch fails closed and
cannot replace the durable hash. Drain all workers, read the current epoch for the
selected environment from `identity_environments` through the authorized operator
database connection, and supply the new named-user settings and database URL in the
process environment. Run `python scripts/rotate_identity_configuration.py
--expected-epoch N` with that observed epoch, then restart all workers with the new
configuration. The command bypasses `.env.local` database fallback and refuses stale
epochs, unchanged configurations and uninitialized environments. A restarted old release
cannot reconfigure the environment or issue sessions. Verify previously issued
credentials fail on every worker before completing the operation. Client-secret rotation
revokes existing sessions; retaining sessions across a configuration-secret change is
unsupported.

The [server action matrix and exposed-route inventory](AUTHORIZATION.md) enforce
role-specific authority before private service/document binding. Production/migrated
HTTP uses the named membership resolver, and identity/ledger database and environment
bindings must agree before profile grants are bound. Recovery/backup/destructive
restore/migration authorization is Owner-only; platform operators execute separately
authorized recovery. Do not synthesize an in-app break-glass identity. Application and
provider grants are unrelated to entity-scoped Google receipt OAuth. Restore identity
control-plane recovery records separately from canonical bookkeeping exports and revoke
restored sessions before bringing a restored environment online (platform operations
recovery gate).

## Validation and remaining checkpoints

Regression coverage uses signed synthetic RSA tokens, bounded fake provider responses,
disposable native PostgreSQL, real HTTP transport, two users and organizations, retained
canonical entities, owner constraints, transaction replay, revocation/config rotation,
setup/read-only identity management and private-browser scope cleanup. These are not
evidence of a real ZITADEL tenant. The authorized hosted rehearsal must verify exact
callback/PKCE plus Basic authentication (including bad verifier/secret), Secure cookie
flags, MFA/recovery, multi-worker revoke/rotation and provider/database outages.
Security logs emit only fixed event/failure codes and safe request identifiers; never
log callback queries, provider payloads, emails, credentials or ledger content.
[Operational telemetry](../operations/OBSERVABILITY.md) consumes only these allowlisted
diagnostic signals.
