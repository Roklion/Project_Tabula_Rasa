# External connections and existing entity claims (#318 / #319)

These are slices of [identity EPIC #222](https://github.com/Roklion/Project_Tabula_Rasa/issues/222)
under [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
They preserve accepted PostgreSQL entity/ledger IDs, separate named login from
Google grants and retain the restricted internal Sheets edition. Actual live
claims, grant installation and owner cutover require selected operator approval
under #303; named hosted acceptance remains #321. External beta (#224),
commercial recovery sign-off (#298), object storage selection (#337) and document
byte migration/recovery (#338 under #223) retain their independent gates.

## Ownership, secrets and operations

Forward revision `0009_external_connections` adds `external_connections`
(organization/entity, provider, original profile key/receipt scope, required
scopes, status/revision and opaque secret reference) and `legacy_entity_claims`
(approved source mapping, named owner/identity binding, approval/plan digests).
Composite foreign keys bind these records to persisted entity ownership.
Provider/profile and provider/receipt-scope uniqueness prevent two entities
from sharing one original Drive document namespace.
Neither table contains tokens or bytes. Canonical export v1 still contains
26 bookkeeping collections; control-plane/secret records are excluded.

Google grants live in encrypted Fernet files outside the checkout, image and
database. Deployment injects these independently of ZITADEL login secrets:

| Setting | Operator responsibility |
| --- | --- |
| `TABULA_RASA_CONNECTION_SECRETS_DIR` | Absolute private directory holding encrypted `<opaque-reference>.grant` files. Provision it explicitly; runtime needs read-only access. |
| `TABULA_RASA_CONNECTION_SECRETS_KEY` | Separate environment-specific Fernet key from the deployment secret manager. Never a browser variable, command argument or committed file. |

Generate keys using the approved private secret-management process. File
provisioning uses exclusive creation and mode 0600; on Windows restrict the
directory/file ACL to the provisioning operator and service account. Protect
ciphertext/key custody separately under #223: a database restore alone does not
recover provider access. Rotate by staging grants in a new key/directory,
switching configuration coherently and having Owners reconnect. Retention or
deletion of old recovery material requires separate approval.

New opaque references start with a letter so their filenames can be uploaded
as Render secret files; existing 32-hex references remain readable. Runtime
reads also support mounted symlinks into versioned child directories beneath
the configured secrets root. The resolved target must remain inside that
operator-controlled root and be a regular file. Links escaping the root,
missing targets and non-file targets fail closed. Runtime never writes through
mounted links; operator provisioning still uses exclusive regular-file creation.
The root and its child directories must not be writable by application users
or other untrusted actors. Grant envelope checks still bind each read to its
exact environment, organization, business and provider.

Decrypted envelopes must match environment, organization, entity and provider.
No default profile, fallback grant, browser-selected secret path or identity
provider token supplies Google authority. Access tokens remain in the existing
Drive client's request lifetime. Missing keys/files, wrong envelopes and provider
failures deny bytes with safe unavailable errors. Ordinary ledger reads can
continue when a configured receipt connection is unavailable/disconnected.

## Operator-assisted Google connect and reconnect

The initial scope reuses [Setup](SETUP.md)'s existing loopback-only Google OAuth
and managed-folder tooling. It adds no second hosted callback. ZITADEL named
login and its cookie/session remain separate; Sheets/Drive use only
`https://www.googleapis.com/auth/drive.file`.

1. Obtain explicit owner/operator approval for environment, org/entity, original
   profile, Google account, client, receipt folder and secret custody. Verify
   exact immutable named user/identity binding privately; browser IDs, names
   and emails are selectors, not proof of ownership.
2. In the approved Google Cloud project enable Drive and Sheets APIs, configure
   consent/audience/test users and publishing/verification requirements. Verify
   current provider grant/lifetime restrictions before hosted use. Register the
   exact approved loopback redirect for existing local Google setup, independently
   of the ZITADEL login callback. Use separate staging synthetic resources,
   client secrets/grants/keys and production configuration; no live setup occurs
   from this implementation.
3. Authorize the intended human account through the restricted administrator
   with offline access and `drive.file`. Select/validate the original managed
   storage root, receipt folder and backup folder. Preserve appProperties/profile
   labels, file IDs and accepted receipt scope. Do not retag/move existing bytes.
4. Prepare private JSON with exactly `environment`, `provider`
   (`google_drive`), `organization_id`, `entity_id`, `profile_key`,
   `scope_key` (receipt folder ID), `google_drive_oauth` and `google_drive`.
   The last two use existing validated client/grant formats including the
   refresh token and managed folders. Never send this file to a browser/API,
   log or GitHub. Remove plaintext preparation material through the operator's
   approved custody process after provisioning; retain legacy config as required.
5. Select the exact target database through existing protected environment
   injection. Run the read-only preflight:

   `python -m scripts.manage_identity_bindings connection --input PRIVATE_FILE --environment staging --revision 0`

   It checks active ownership, current revision, retained metadata/cutover
   scope and fresh Google folder/profile ownership. It creates no secret/DB row.
6. Review its private plan and retain owner/operator approval. Repeat with
   `--apply --expect-plan PLAN_DIGEST --approval-sha256 APPROVAL_DIGEST`.
   A new encrypted file is created before the connection is staged as Pending.
   The approval digest identifies a retained private approval record; it is
   not authentication or infrastructure authority. A DB staging failure may
   leave unreferenced ciphertext for operator inspection; receipt bytes are
   never deleted as rollback.
7. The active Owner signs in within five minutes, opens **Data & backup >
   Google Drive connection**, reviews the business and confirms Connect.
   Backend checks current membership/capability, loaded revision, exact
   envelope, scopes and fresh managed-folder ownership before recording success.

For replaced/revoked/missing grants repeat staging with the current revision and
new approved grant, then confirm Connect. An existing valid disconnected grant
can be re-enabled with Reconnect. A stale revision fails without applying to a
replacement grant; commands are not automatically retried. Admin, Editor,
Accountant and Read-only cannot inspect/manage connections; permitted document
readers can still read receipts when connected. All unsafe requests retain
Origin/CSRF checks. Logged-out, removed and foreign members deny before secret
binding. Already-composed byte stores recheck current membership/connection.

Status describes local lifecycle, not a live Google health probe: Not configured,
Pending, Connected, Disconnected or Reconnect required. An observed Google
authorization failure during byte access records Reconnect required and returns
a safe unavailable error. Existing Drive scope/integrity validation remains.
A future managed DocumentStore can replace provider composition without changing
user identity/sessions; #337 owns its selection.

### Disconnect versus Google revocation

A freshly authenticated Owner can confirm Disconnect. This durably blocks later
application access while preserving encrypted grants, files, ledger links and
metadata. It does not claim Google consent was revoked.

Provider revocation is a separate approved operator/Google-account action via
Google account permissions or the existing `GoogleDriveClient.revoke`. First
disconnect, confirm the exact grant's sharing/use and get impact approval.
Copied legacy refresh grants or shared Google client consent can also serve
retained Sheets/backup operations: revocation may interrupt them. Never
automatically revoke or delete files as rollback. If Google cannot confirm,
local disconnection remains effective but provider revocation is unconfirmed;
verify Google's controls before claiming completion.

## Claim accepted existing entities without remigration

Inventory #299/#303's private profile/entity, source workbook/run, accepted
document folder and target DB bindings first. Claims create no ledger entity,
import, authority activation or backup copy.

1. Verify independent operator infrastructure authority and the intended human's
   exact immutable identity binding. The user must already have verified named
   login and active Owner membership in the active target organization.
   Organization provisioning remains #311/#316; there is no browser claim route.
2. Prepare private JSON matching `LegacyClaim`: `entity_id`, `profile_key`,
   `workbook_key`, `organization_id`, `owner_id`, `identity_binding_id`,
   `database_sha256`, `run_id`, `acceptance_sha256`, `document_scope`.
   Read exact values from approved private config and accepted cutover evidence;
   the existing endpoint digest contains no password. Prepared or active
   acceptance, source IDs and original receipt scope must agree.
3. Run `python -m scripts.manage_identity_bindings claim --input PRIVATE_FILE`.
   Read-only preflight verifies target, active Owner/identity and conflicting
   ownership. It grants no access.
4. After exact mapping review and explicit approval, repeat with `--apply
   --expect-plan PLAN_DIGEST --approval-sha256 APPROVAL_DIGEST`. Fresh checks
   and one transaction create org/entity binding and approved claim. The same
   approved apply is idempotent; mismatches and inactive/conflicting ownership
   fail closed instead of inferring an alternate target.
5. Associate the existing document grant through the connection procedure.
   Retained metadata and accepted cutover scope must match. Named migrated
   runtime requires the persisted approved claim, server profile/entity config
   and active PostgreSQL authority. Bytes use tenant connections with no
   legacy-token fallback. Internal legacy composition keeps its profile grant.
6. Under #303/#321's separately authorized execution, restart and verify only
   approved named entity/document access, preserved reports/export and backup/
   cutover records for every selected profile. Tests here use two synthetic
   profiles; #303's actual three-profile owner acceptance remains outstanding.

Exceptions before transaction commit roll back claim and binding together;
dry-run needs no rollback. After a committed claim, do not automatically delete
ownership/replay imports. Suspend access using existing org/member/session
controls, retain evidence and arrange explicitly reviewed correction. This
does not roll back ledger authority: after divergence, the existing controller
still refuses stale Sheets reactivation. Use PostgreSQL/document recovery.

## Retained local administration inventory

| Existing surface/owner | Retained authority/effect |
| --- | --- |
| Business profiles (`local_profile_admin_forms.py`, `local_profile_store.py`) | Local profile registration/edit/removal, workbook IDs, backup paths and ignored JSON authority. |
| Google setup (`google_drive_admin.py`) | Shared client, per-profile offline credentials, managed root/receipt/backup folders, workbook selection/creation and disconnect. |
| Recovery (`local_profile_admin_synology.py`, readiness helpers) | Backup/recovery configuration, Synology metadata/readiness; existing blank-target/backup/restore safeguards remain separate. |
| Security/deployment (`local_profile_admin_security.py`) | Sensitive hosted Secrets export and deployment information; never a commercial DTO/export endpoint. |

These actions require `TABULA_LOCAL_PROFILE_ADMIN=1`, loopback-only Streamlit
binding, application-password authentication and administrator reauthentication.
The renderer rechecks the boundary before configuration access. Unlock is bound
to the current password hash so stale/misbound booleans do not survive rotation.
Commercial membership, claimed IDs and forwarded headers grant no local
authority. Keep the listener out of public proxies and use
`scripts/run_local_profile_admin.ps1`. The legacy application password/shared
OAuth client intentionally remain deployment-wide.

#319/#222 owns retirement once new-stack login, business creation and management
replace the supported functions and verification is accepted. Credentials
transition to #318, privileged recovery/support to #313/#341, live execution to
#303. Do not rebuild this local UI as hosted RBAC or treat Owner as operator.

## Reuse and verification

Reuse: shared membership/action policy, named sessions/freshness/CSRF, existing
cutover acceptance/authority/divergence, Google OAuth/managed folders,
EntityDocumentStore/profile labels and PostgreSQL receipt metadata.
New logic: connection lifecycle/secret resolution and operator claims.
There is no parallel ledger, login, OAuth migration engine or retry framework.

Regressions exercise real PostgreSQL claims, unchanged 26-domain exports and
cutover records, two-org grants, missing/revoked secrets, reconnect, revision/
freshness/CSRF, logged-out bytes and legacy remote/misbound authority. Browser
tests exercise confirmation, safe states, uncertain failure and cancellation.
Hosted provider setup, credentials, live mapping and release acceptance remain
explicit operator checkpoints, not evidence supplied by mocks.
