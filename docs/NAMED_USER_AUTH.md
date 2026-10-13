# Named-user authentication and control plane

This implements the #311/#312 foundation within [commercial identity](COMMERCIAL_IDENTITY.md)
and ADR 0003. It does not complete #222, authorize external beta, claim a hosted
provider rehearsal, or enable the separate legacy-profile migration. The
Streamlit administrator remains a loopback-only operator surface. #313 owns
the complete action-policy gate; #314–#321 own the remaining commercial journey
and rollout checks. Do not expose this foundation as a production-ready ledger
before those gates are satisfied.

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

Never set `TABULA_RASA_TRUSTED_ENTITY_ID` or alpha Basic credentials in named
mode. Production and named mode reject injected trusted-development contexts
at the HTTP guard as well as rejecting synthetic configuration. Restricted
alpha remains a separate explicit fixture mode; it grants no named membership.
Use separate provider clients, secrets and databases for each environment.
Register exactly `<public origin>/api/v1/auth/callback` without wildcard URLs.
HTTP settings canonicalize scheme/hostname case and omit default ports before
binding the Host guard, exact browser Origin/CSRF check and OIDC callback.
Non-default ports remain part of the origin; foreign origins are still refused.
Provider accounts, region/plan, MFA/recovery, mail and authorized secret setup
remain operator checkpoints. No provider resource is provisioned by this code.

## Login and browser lifecycle

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
transaction. Return paths are only `/` and `/onboarding`. The code callback
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

The server binds an immutable exact `(issuer, subject)` to a random internal
user ID. Equal or changed email addresses never link accounts. New users receive
no organization membership or preexisting business access automatically.
Ownership associates with existing canonical `business_entities`; it does not
create an alternate ledger, rebaseline records, or change cutover provenance.
Repository operations are internal trusted building blocks, not public
administration endpoints; future callers must enforce #313/#315 action policy.
Forward revision `0008_owner_lock_scope` keeps organization-owner serialization
on user state updates/deletion, not login display-metadata or revocation-epoch
updates. Membership owner locks and deferred last-active-owner checks remain.
It changes no bookkeeping fields or portable-export inventory.

Hosted opaque session/login cookies use `__Host-tabula_session` and
`__Host-tabula_login`: Secure, HttpOnly, SameSite=Lax, Path=/, no Domain. Loopback
HTTP uses distinct `tabula_dev_*` names. A matching HttpOnly host-only CSRF copy
(`__Host-tabula_csrf`) permits Origin/CSRF-valid logout to clear cookies even
when PostgreSQL is unavailable. That copy grants no bookkeeping authority.
Other unsafe routes use the freshly validated session's synchronizer token.
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
requires `max_age=0` rather than silently reusing stale authentication.

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

Issuer, client, client-secret, public-origin or session-generation changes
increment the durable environment epoch on coordinated named-runtime startup.
Drain old workers and restart all workers together with the same new
configuration: old workers cannot validate sessions after rotation, but an
old deployment restarted with old configuration must not be allowed to
reconfigure the environment. Verify that previously issued credentials fail
on every worker before completing the operation. This follows the #310 owner
decision: client-secret rotation revokes sessions, superseding the ADR's former
retain-sessions suggestion.

Recovery/backup/destructive restore/migration authorization is Owner-only;
platform operators execute separately authorized recovery. Do not synthesize
an in-app break-glass identity. Application and provider grants are unrelated
to entity-scoped Google receipt OAuth. Restore identity control-plane recovery
records separately from canonical bookkeeping exports and revoke restored
sessions before bringing a restored environment online (#223 recovery gate).

## Validation and remaining checkpoints

Regression coverage uses signed synthetic RSA tokens, bounded fake provider
responses, disposable native PostgreSQL, real HTTP transport, two users and
organizations, retained canonical entities, owner constraints, transaction
replay, revocation/config rotation, setup/read-only identity management and
private-browser scope cleanup. These are not evidence of a real ZITADEL tenant.
The #321 authorized hosted rehearsal must verify exact callback/PKCE plus
Basic authentication (including bad verifier/secret), Secure cookie flags,
MFA/recovery, multi-worker revoke/rotation and provider/database outages.
Security logs emit only fixed event/failure codes and safe request identifiers;
never log callback queries, provider payloads, emails, credentials or ledger
content. #332 can integrate these allowlisted signals into operational telemetry.
