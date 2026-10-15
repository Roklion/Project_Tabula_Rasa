# Workspace switching, membership and bootstrap

Issues #314–#316 deliver Wave 3 of [identity EPIC #222](https://github.com/Roklion/Project_Tabula_Rasa/issues/222)
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
They reuse the named-user sessions, current membership policy and canonical
PostgreSQL ledger. No Streamlit profiles, live migration or provider grants are
created by these operations. #317 adds the guided browser onboarding journey;
#318/#319 own connections and existing-profile mapping. Hosted identity evidence
remains #321, adversarial initiative acceptance #320, and external-beta admission
still requires #223/#224's independent gates.

## Switching and access changes

The labeled business selector groups names as workspace / business and lists
only current server-authorized entities. Workspace name and role are displayed
from server claims. Read-only members can switch and sign out. Selection updates
the durable server session after Origin/CSRF and current membership validation;
an arbitrary URL, entity ID or role never grants access.

Confirming a named-user switch immediately unmounts private queries, drafts,
uploads and receipt previews. The existing scope boundary cancels queries and
receipt requests and revokes object URLs. Success loads the new scope and
returns navigation to Dashboard, dropping record-specific URLs. An uncertain
or denied switch shows a safe error with Reload/Sign out and retains no private
view. Restricted synthetic-alpha selection retains its existing failure/draft
behavior. Other tabs receive a data-free scope-change signal and reload authority.

Visible named tabs also check on focus/pageshow/visibility and every 60 seconds.
Committed membership changes affect the next protected server request. Changed
authorization versions replace the browser boundary on its next check; revoked
selected entities fall back only to another currently permitted entity, or to
Workspace setup required. An already authorized in-flight request may finish.
There is no persistent private browser cache or client authorization fallback.

## Members and invitations

Open **Workspace & members**. Owner/Admin members see current membership and
invitation administration for their workspace. Roles apply to every active
business in that workspace. Admins can grant Editor, Accountant and Read-only,
demote or deactivate themselves, and manage non-Owner/non-Admin members. Owners can manage
all roles. Grant ownership is a separate explicitly confirmed Owner action;
Owner grants and removal/demotion require provider authentication within five
minutes. The database rejects removing the last active Owner, including races.
Loaded membership authorization versions reject stale changes.

The approved early restricted-beta delivery is **operator-distributed**, not
outbound email. An authorized administrator enters the recipient email and role.
The creation view displays a cryptographically random 256-bit credential once.
The administrator shares it privately with that recipient, then dismisses it.
It is absent from listing responses, URLs, browser storage, logs and exports.
No sender/domain setup or paid mail provider is required for this delivery mode.
After an uncertain creation response, refresh the invitation inventory and
revoke the pending invitation whose credential was lost before issuing a new
one. The browser refreshes affected lists after confirmed or uncertain commands
and never automatically retries invitation or membership writes.
Automated mail requires the separate sender/domain/provider checkpoint in
[Commercial identity](COMMERCIAL_IDENTITY.md).

The recipient signs in with the intended account and pastes the credential into
**Respond to an invitation**, available in Workspace & members and Workspace
setup required. Acceptance/decline requires verified provider login within five
minutes, with the same bounded 60-second future clock tolerance as verified
OIDC login. The session retains that login's verified email server-side; a browser
email or another session's later email change cannot substitute for it. Email
comparison trims and ignores case without plus-tag or dot rewriting. Stable
issuer/subject mapping remains the identity key; matching emails never link users.

Only the hash is stored with invitation lifecycle/recipient metadata. The native
transaction rechecks recipient, current inviter grant authority, expiry and
pending state, consumes once and creates/reactivates unique membership. An
existing active membership keeps its role. Concurrent/replayed acceptance grants
access once; later requests report already used. Expired (48 hours), revoked,
declined, invalid-recipient and reauthentication-required states offer safe
guidance. On required reauthentication, the form clears the credential; paste it
again after signing in. Pending invitations confer no discovery or ledger access.

## Backend bootstrap and retry contract

Bootstrap is available in the native PostgreSQL runtime. The migrated-profile
runtime rejects workspace and additional-business creation before any records
are written, because it serves only the operator-configured entity/profile
bindings established at startup. Existing bound ledgers, memberships and
invitations remain available there; bootstrap status remains a read-only lookup.

Authenticated named users, including users without any memberships, can call
`POST /api/v1/workspaces/bootstrap` with `request_id` (16–128 characters),
`workspace_name` and `business_name` (required, trimmed, at most 160 characters).
The acting internal user becomes Owner. No caller-supplied owner/entity IDs or
legal/tax fields are accepted. Books use the existing standard chart of accounts
and Income/Expense category defaults from `LedgerSetupService`; no second default
inventory or new currency/tax setup is introduced.

`POST /api/v1/workspaces/{organization_id}/businesses` uses the same body and
bootstrap owner, requiring current Owner `entity:manage` authority in that
organization. There is no commercial entitlement/billing policy yet; #224 owns
that future boundary. Admin and ordinary memberships confer no creation right.
The workspace name in this shared request does not rename an existing workspace.

One database transaction creates organization, Owner membership, canonical
business entity, ownership binding, default records and an idempotency receipt.
Failures roll everything back. Concurrent submissions with the same acting user
and request ID serialize and return the same result. Reusing that ID with a
different normalized payload returns conflict; distinct IDs deliberately create
distinct workspaces/businesses. Preserve the request ID when retrying an uncertain
response. `GET /api/v1/workspaces/bootstrap/{request_id}` returns `ready` with
authorized result IDs or `not_started` for no committed receipt. Another user
cannot inspect the receipt. There is no half-created/incomplete durable state:
resume means retrying the same request. Receipts and ledger defaults survive
pool/worker restart. Session inspection then discovers the first available entity.

## Browser onboarding (#317)

Sign in (or register with the configured hosted identity provider), then choose
**Start fresh**, **Join an invited workspace**, or **Move existing Sheets books**.
Fresh setup collects workspace/business names and offers the currently supported
standard basic bookkeeping defaults. Back preserves names before submission.
Create ledger uses the existing atomic bootstrap, then selects the authorized
business and opens Dashboard with account, first-transaction and ledger actions.
Repeat visits open the existing ledger; they do not create another workspace.
Owners can add another business in Workspace & members using the same setup flow.

The tab stores only an opaque request ID keyed by authenticated user and target
workspace in session storage. Names, invitation credentials, sessions and ledger
contents are not persisted there. After refresh, choose Start fresh again to
resume: a committed receipt opens its authorized business; otherwise re-enter
the original names. After an uncertain create, one status readback can confirm
completion. Explicit Retry same setup retains the original request and payload;
there is no automatic create retry. Browser storage must be available before
creation. Closing the tab ends this browser resume handle; server receipts and
any created ledger remain durable and discoverable through authenticated login.

Privately distributed invitations are supported now: share the app's
`/invitations` route separately from the credential. That route returns to
acceptance after login for both new and existing members, without creating an
organization. Credentials must be pasted after login and never enter URLs.
Connections remain optional and deferred to #318; invites are optional and can
be sent later. Existing live Sheets migration remains the explicit #258/#303
operator process, with no browser import or authority switch during setup.

Apply forward migration `0010_onboarding_routes` before this browser revision.
It extends the exact server/database login return-path allowlist with
`/invitations`, preserving all existing sessions, login attempts and bookkeeping
records. External URLs and query-bearing return paths remain forbidden. Native
browser tests cover desktop/mobile setup, failures, lost responses, refresh,
repeat visits, invitations, two-business switching and foreign-entity denial.
This is local/CI evidence; #320/#321 and #223/#224 still own adversarial hosted
acceptance, operations/legal and external-beta admission under #222/#124.

## Migration and validation

Apply forward revision `0009_workspace_lifecycle` using the existing explicit
deployment migration command. It adds invitation/idempotency tables and the
server-only verified session email; existing sessions may keep bookkeeping access
but must sign in again for invitation acceptance/ownership changes. It does not
rewrite ledger records or export format v1. Identity/session/invitation/bootstrap
records are excluded from entity bookkeeping exports and recovery comparisons.
Restored sessions still require #223's existing revocation procedure.

`tests/postgres/test_workspaces.py` covers native concurrency, rollback after
default seeding, retry/restart, two-org isolation, multiple owned workspaces,
verified-recipient/freshness/replay, lifecycle, role escalation, stale edits and
HTTP/CSRF/secret-safe denials. `test_workspace_browser.py` exercises two users at
desktop/mobile widths, switching, membership administration, revocation, logout
and accessibility using the compiled app and disposable PostgreSQL. These are
synthetic local/CI checks, not hosted-provider or external-beta approval.
