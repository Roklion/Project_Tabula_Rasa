# Business tenancy and forward rollout

Each business has its own private backing organization. A user can be Owner of
one business, Admin of another and Read-only in a third. Membership versions,
invitations and last-active-owner protection apply independently to each
business. My Businesses is a derived authorized list, not a tenant record.

The previous interface grouped businesses under a selected workspace and implied
one shared role. Current business-first navigation is flat: the same verified
identity can select A as Owner and B as Admin or Read-only. Member/invitation APIs
take a business ID and resolve its private container server-side. The compatibility
organization APIs remain deprecated; they do not authorize another business.
No table deletion, identity/session rewrite or automatic grant conversion follows
the presentation change.

The retained `organization_entities` mapping (not a new ledger table) associates
the immutable canonical `business_entities.id` with its authorization container.
Revision `0016_business_tenancy` adds `UNIQUE (organization_id)` alongside the
existing entity primary key, composite foreign keys and ownership-update guard.
Inactive bindings also occupy their container. Empty organizations remain valid
for explicitly approved historical claims; they grant no business access.

## Creation and authorization

The existing bootstrap transaction creates a new organization, only the acting
user's Owner membership, one canonical business, standard ledger defaults and
the durable actor/request receipt. It never copies another business's members.
The compatibility `POST /api/v1/workspaces/bootstrap` retains its existing
request/result contract. New calls to
`POST /api/v1/workspaces/{organization_id}/businesses` are forbidden, including
Owner and concurrent calls. An exact authorized historical receipt may still
be replayed; replay creates no rows. Business-first presentation and thin
business-only transport adapters build on this same bootstrap owner.

Ledger, privileged import/export/recovery and receipt operations retain their
explicit entity guards and server-resolved membership. Compatibility member
and invitation routes resolve the supplied container through its unique active
business and current membership. A client organization ID/name never grants
authority. Ambiguous containers fail closed even on the prior schema. A role
change or removal in A changes only A's authorization version; B's role,
membership, selected scope and provider binding remain independent.

Legacy claim previews reject a container occupied by any other entity, just as
apply does. The database constraint also protects direct SQL and races between
claims, bindings and bootstrap. Approved claim hashes, document/grant scopes,
membership freshness, recipient verification, sole-owner succession and
server-side Origin/CSRF/session checks retain their existing owners.

## Read-only inventory

Against the exact intended database, using approved secret injection:

```powershell
python -m scripts.inspect_business_tenancy
```

This opens one read-only snapshot and returns database fingerprint, schema
revision, counts of containers/bindings, memberships, invitations, bootstrap
receipts, claims, provider connections, sessions and support grants, plus empty
and multi-business container counts. Exit 0 means no conflicting mappings, 2
means reconciliation is required, and 1 means preflight was unavailable.
Readiness is a structural observation, not migration approval. Repeat it after
any approved changes and compare the exact database fingerprint. It emits no
names, emails, subjects, token hashes, provider references or bookkeeping data.

An operator must inspect detailed mappings only in approved private custody.
Inventory **all states**, not just active rows:

| Existing owner | Required private inventory and decision |
| --- | --- |
| `organization_entities`, `organizations` | Each immutable entity/container ID and state; identify every container with more than one retained binding. |
| `memberships`, `identity_users`, `identity_bindings` | Each current role/state/version and verified user binding; decide the exact per-business grants and an active Owner/succession for each resulting boundary. Never infer intent from an old shared role. |
| `workspace_invitations` | Pending/accepted/expired/revoked invitations, inviter and intended business. Pending ambiguous invitations must be explicitly revoked/reissued for a chosen business; never clone them. |
| `workspace_bootstraps`, `identity_sessions` | Historical receipt payload/result and selected entity/container. Preserve authorized receipt recovery; plan explicit session revocation/reselection if any approved mapping changes. |
| `legacy_entity_claims`, `bookkeeping_cutovers`, migration provenance | Exact approved entity/profile/source/owner/binding hashes and authority. A new container invalidates the old approval context; obtain a new explicit claim decision without changing ledger identity or activating authority. |
| `external_connections`, document metadata/locations and private secret custody | Exact entity/container/profile/provider/folder/grant relationship. Preserve bytes and original scopes. A shared or unclear grant blocks conversion until its owner chooses a supported isolated binding. Never copy a refresh token or broaden receipt access. |
| `support_grants`, `support_actions` | Organization/entity/environment scope and retained privileged history. Revoke or explicitly reapprove access rather than carrying shared administrative authority into a new business. |

## Multi-business reconciliation

There is deliberately no automatic splitter. A failed preflight or constraint
upgrade leaves the old data and revision intact; repeated attempts have the
same result until an independently authorized operator resolves the conflict.
The migration locks the binding table before checking, so no concurrent writer
can slip a second binding between preflight and constraint installation.

1. Preserve a verified database/document recovery point and read-only private
   inventory of the exact environment. Pause relevant writers before planning
   the final change. Keep canonical entity IDs, accounting rows, document bytes,
   provenance, grants and current ownership unchanged during inventory.
2. Obtain explicit per-business owner approval for each membership, role,
   invitation, sole-owner succession, provider/receipt binding and session
   decision above. If intent or grant ownership cannot be disambiguated, stop;
   retain the source unchanged and keep the affected conversion blocked.
3. Prepare a narrowly scoped, forward-only operator migration with exact old
   and intended mappings, expected-state guards, recovery checkpoint and
   approval reference. Existing ownership-update and composite foreign-key
   guards intentionally prohibit casual reparenting. This needs a separately
   reviewed migration for the approved case, including receipts, claims,
   connections and support references; disabling triggers or deleting bindings
   to make this migration pass is not a supported reconciliation procedure.
   Do not merge tenants, clone shared memberships, choose a new Owner, reset a
   database or delete an entity as an implicit implementation choice.
4. Rehearse that explicit plan on an isolated authorized copy. Verify identical
   canonical exports/IDs, document metadata and bytes, provenance, grants,
   per-business roles, invitations, last-owner constraints and session/receipt
   behavior. Retain detailed evidence privately; publish only sanitized counts,
   fingerprints, revision and approved outcome. Execute on a live target only
   after separate exact-target operator authorization.
5. Repeat inventory and the constraint upgrade. Verify the expected schema and
   independent access for at least two businesses. Keep the preserved source
   and recovery material; no automatic cleanup or downgrade follows success.

### Bounded synthetic two-business reconciliation

`python -m tabula_rasa.deployment.tenancy_reconciliation` is a separately invoked operator
tool for the reviewed source shape: schema `0015_support_controls`, two private
containers/three active business bindings, with two businesses in the source
container. That source has exactly one active Owner, one inactive Read-only
member, one accepted invitation and no support grant. The moved business must
have exactly one bootstrap receipt belonging to the Owner and no selected-session,
external-connection or legacy-claim reference. Other shapes stop for a separate
review; this is not a general tenant splitter. Production/development CLI
targets are refused, and the database must contain only the staging identity
environment. The migration credential must own the existing guard, while the
known `tabula_staging_runtime` login role must not share that ownership.

Approval must specify which business retains the source container, the new
container's preallocated ID, the same existing Owner, continued inactive access,
retained invitation history, and the historical-replay contract in
[workspace retry behavior](WORKSPACES.md#backend-bootstrap-and-retry-contract).
The operational receipt's organization reference changes; its original result
is retained in the private plan/checkpoint. Do not claim byte-identical original
operational receipt results. This compatibility decision needs explicit approval.

Before any hosted use, obtain independent review/current-revision CI, exact
database/service and window approval, a verified independent DB/document
recovery checkpoint and private custody. Rehearse first on a separately approved
isolated copy. Suspend the exact staging service and pause **all** other
application, job, migration and operator writers. Keep it suspended through
reconciliation, outcome inspection, forward migration and compatible backend
deployment. The tool does not suspend/resume Render, stop jobs, create backups,
rotate secrets, deploy, upgrade the schema or grant runtime privileges.

Use the reviewed immutable commercial image (which includes this module) in a dedicated operator process. Inject only
the separately held migration URL, `TABULA_RASA_ENVIRONMENT=staging` and the exact
`TABULA_RASA_DEPLOY_DATABASE_SHA256` binding through approved private custody.
Hosted binding requires a direct Neon TLS URL. Do not pass Render/API tokens,
runtime grants, OAuth material or passwords as command-line arguments. Place the
plan in an absolute operator-private directory with access restricted by the
operator (including Windows ACLs); never commit it, publish its JSON or upload it
to reviewer/CI logs. It contains private identities and original bootstrap records,
but only hashes for financial, audit, session and provider tables. It is provenance,
not a replacement database/document backup.

```powershell
python -m tabula_rasa.deployment.tenancy_reconciliation prepare --plan $privatePlanPath --source-org $sourceOrg --retained-entity $retainedBusiness --moved-entity $movedBusiness --owner $existingOwner --destination-org $allocatedContainer --recovery-sha256 $verifiedRecoveryRecordHash
# Inspect the original record privately and approve the exact printed plan hash.
python -m tabula_rasa.deployment.tenancy_reconciliation apply --plan $privatePlanPath --approval-sha256 $approvedPlanHash --writers-drained
```

All variables above are operator-selected non-secret references, not example
approvals. `--writers-drained` is the operator's attestation of the independently
verified service/writer pause; it does not perform or prove the provider action.
Execution also refuses any connected session using the known runtime login role.
The source is checked again under exclusive public-table locks and the existing
migration advisory lock. State drift, changed guard/FK definitions, unexpected
dependencies or a wrong target stop before the move. Preparation is read-only and
creates a new file exclusively; it never overwrites the original provenance.

One database transaction creates only the new private container and Owner
membership and amends the chosen binding/receipt container references. The
ownership guard gets an exact-tuple, migration-role-only exception inside that
transaction; every unrelated move remains prohibited. Only the receipt FK is
temporarily deferred, then all constraints are validated immediately. Its
original definition and the full original guard definition are restored and
verified before commit. A failed transaction restores rows and DDL together.
No trigger is disabled and no reusable transfer function/permission is left.
Unchanged-table hashes preserve the other business, ledger/audit, invitation,
inactive membership, sessions, provider references and document metadata/links;
the tool does not access receipt bytes or grant files.

Success means the database transaction returned confirmation. If that response
is lost, keep every writer paused and perform one fresh outcome inspection:

```powershell
python -m tabula_rasa.deployment.tenancy_reconciliation readback --plan $privatePlanPath --approval-sha256 $approvedPlanHash
```

`applied` confirms the exact expected state; `not_applied` confirms the unchanged
source. Any other state or inspection failure stops for private investigation.
Do not rerun `apply` blindly: an already-applied or changed source is rejected.
Keep the plan and checkpoint. Readback is for schema 0015 before any subsequent
upgrade/resumption; later activity deliberately invalidates its frozen-state
comparison. After confirmed reconciliation, repeat tenancy inventory, then run
the unchanged canonical forward upgrade in the separately approved maintenance
sequence below. Never edit/stamp deployed migrations or weaken the uniqueness
check. Any next image, hosted smoke, fault drill or stage acceptance remains a
separate authorized operation.

## Deploy and rollback sequencing

For named-user staging and owner migration, inspect the exact schema and
read-only inventory first. If ambiguous, stop rollout and use the process
above. Do not treat staging fixtures or existing owner data as disposable.

Pause application and operator writers for the approved migration window. Apply
the explicit normal PostgreSQL forward upgrade through `0016_business_tenancy`,
then deploy this compatible backend before enabling business-first clients.
The old bootstrap contract remains callable; old additional-business controls
receive a safe forbidden response. The replacement onboarding uses a fresh
container for every business. This does not require identity/provider rotation
or rewrite valid sessions, grants, claims, ledger data or default records.

Smoke-test named login, existing selected entity, independent roles, read/write
and denied operations, invitation acceptance, receipt scope, fresh creation and
exact retry. Compare schema, canonical export and document recovery evidence
with the preserved baseline. The migration is forward-only. Roll back only to
an independently verified image that supports the retained new schema and
denies additions; a pre-pivot image is not automatically compatible. If no such
image exists, stop writers and deploy a compatible forward fix or use the
approved isolated database/document recovery procedure. Never drop the unique
constraint, reset data or reactivate stale Sheets as routine rollback.

The final browser revision additionally needs business-member and invitation review
APIs before its assets are promoted. Verify Owner A/Admin B and a Read-only recipient
shared by two independent Owners, flat list selection/refresh, role change and
revocation, peer-tab drafts/uploads/receipt cleanup, forged private requests and
long names at desktop/390px/320px. Retain revision, schema, route, browser, viewport,
safe timing/status and current-head required CI/review references in the owning
release discussion. Prior workspace/shared-role evidence does not establish this
model. Hosted provider recovery/rollback and owner binding/authority activation
remain separate; this UI neither changes approved historical entity/claim IDs nor
executes the owner cutover.

The existing narrowly scoped hosted support-schema maintenance command targets
its original transition; it is not approval to upgrade business tenancy. Use
an explicitly reviewed deployment migration for this revision. Owner source
claims and production authority still require their separate exact-target
cutover and connection approvals. This foundation supplies no alpha bypass,
live conversion, external-beta admission or commercial launch authorization.
