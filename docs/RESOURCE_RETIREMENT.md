# Resource inventory and approved retirement

[#339](https://github.com/Roklion/Project_Tabula_Rasa/issues/339) owns exact-target
resource disposition under [operations #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
This is one-time operator housekeeping. It adds no alpha/owner-cutover activation
gate and no automatic purge. #221/#377 own code/test retirement; #342 owns
operational replacement evidence; #224/#298 retain customer retention, commercial
recovery acceptance and production activation authority.

## Status and policy

The offline inventory validator, exact-target preview and manual execution
procedure are implemented. **No resource deletion or retention change is approved
or executed.** The [inventory and disposition table](operations/RESOURCE_INVENTORY.md)
and [machine inventory](operations/resource-inventory.json) cover the relevant
resource families and known safe identifiers as of October 19, 2026 Eastern.
They are a desk inventory from tracked configuration and issue evidence, not a
complete live provider enumeration. Unknown IDs, endpoints, current authority,
last backups, ownership acceptance and consumer checks remain explicit gaps.
Do not close the actual-resource inventory/approval acceptance on that basis.

Preserve frozen Sheets sources, last verified legacy snapshots, complete exports,
checksums, receipts/document bytes, audit history, production/staging/UAT, recovery
evidence and deployed forward Alembic history. #261 retired format compatibility;
it did not authorize deleting files or records. #294 retains every successful NAS
generation indefinitely, including mislabeled and drill generations. Capacity
pressure triggers an operator decision, never implicit pruning. The tool refuses
NAS generations, Sheets workbooks and schema history even if mislabeled disposable.

A future retention proposal must state exact scope, current obligations, remaining
verified recovery points, legal/hold/customer effects, new duration, custody,
capacity and recovery risks. Obtain separate #223 policy and #224/#298 decisions,
update canonical runbooks and tooling, then seek exact-target deletion approval.
This issue does not change the existing Sheets/Drive backup policies in
[Backup and recovery](BACKUP_RECOVERY.md), or authorize using them to purge a
protected final source/last snapshot.

## Prepare an operator inventory

Work outside Git in protected operator storage. Copy the machine inventory and
inspect the applicable provider consoles/read-only APIs, NAS and configuration
for the **selected stage**: `technical_alpha`, `owner_operated`, `external_beta`
or `commercial`. The seed uses owner-operated scope; it asserts no current live
authority switch. No whole-EPIC completion is required to begin inventory.

1. Enumerate exact Neon project/branch/database/endpoint IDs, parent/child
   branches, managed snapshots and restore state; distinguish Production, UAT,
   development, shared test and isolated recovery targets. Display names alone
   are insufficient. Enumerate local/CI fixture databases through their existing
   harness, rather than widening its teardown privileges.
2. Inspect Render bindings, GitHub environment/workflow references and secret
   **names**, deploy/CLI/operator scripts, scheduled jobs, test callers and
   retained migration rehearsals. Inspect effective bindings privately; never
   dump environment variables or secret values. Inventory every endpoint and
   dependent DB/file/binding affected by a provider's parent deletion.
3. Reconcile protected NAS complete/incomplete/quarantined generations, Sheets
   source profiles, Drive folders/backups/receipts, historical artifacts and
   private exports/manifests/oracles with #259/#294/#338/#342 evidence. Record
   existence, custody, retention reason and evidence handle, never ledger rows,
   document names/bytes, private exports or credentials.
4. Obtain the environment owner's disposition: retained source/last verified
   snapshot (`retained_source`); active or recoverable target
   (`active_recoverable`); required drill evidence (`required_evidence`);
   disposable synthetic target (`disposable_synthetic`); or unresolved/needs
   approval (`unresolved`). A completed migration or closed ticket cannot supply
   disposition. Keep deferred resources unresolved or retained with a named
   owner and re-review condition in the protected operator record.
5. For each candidate, confirm synthetic-only contents and no active, CLI, CI,
   staging, rollback, audit/retention or recovery consumer. Obtain #377 D4/D7's
   owner/evidence reference for this exact capability; #342 must establish the
   selected stage's replacement recovery guarantee where relevant. Database
   dumps do not protect document bytes. Link the accepted evidence with `handoff`.

Use only reviewed safe handles in the JSON. Its strict schema rejects unknown
fields, URLs, paths, duplicate keys/IDs/identities and dangling resource edges.
Handles can still encode sensitive information: manual sanitation is required.
Use opaque references to private evidence, not personal/business names. Untrusted
input is rejected before any contents are printed; fixed error codes omit paths
and raw parser/provider errors.

Every resource has a local `id`, `kind`, exact `scope` (provider project/container),
`provider_id`, `environment`, `owner`, `disposition`, `authority`, `protections`,
`references`, `depends_on`, `last_backup`, `handoff`, `rollback`, `evidence` and
`effects`. A family row with a null provider ID is an inventory gap; split it into
exact rows before proposing disposal. `last_backup` links a verified preserved
backup; for reproducible empty fixtures it may link a reviewed recreation/absence
record. `rollback` links the tested recovery/recreation procedure.

`references` lists live/retained consumer handles; any entry blocks disposal.
`depends_on` lists resource IDs consumed by this resource (e.g. a database depends
on its parent branch). `effects` lists **every exact resource affected by deletion**,
including itself. An empty list means unreviewed effects. Add affected endpoints,
children, branch-local roles, files and config references as separate inventory rows; no cascaded
effect may be silently omitted. All effects must be selected and independently
eligible, and any consumer outside the set blocks the operation. Do not clear
references without inspecting/removing obsolete bindings through their normal
reviewed workflow and then rechecking effective configuration.

The top-level `observed_at` is the UTC instant when the whole scoped inventory
and its references/effects were inspected. Set `coverage: operator_verified`
only after complete enumeration of those dependencies and owner review. This is
an attestation, not automatic cloud discovery or authorization. Missing resources
cannot be detected by an offline tool; retain `unverified` if access is incomplete.

## Preview and manual approval

From the repository root, using the active Python development environment:

```powershell
python scripts/preview_resource_retirement.py --inventory docs/operations/resource-inventory.json --target recovery-259-snapshot
```

The seed intentionally returns exit 1, `blocked`, `applied: false`. For a privately
verified disposable set, repeat `--target` for **each** exact target. There is no
wildcard, default-all, execute, force or approval switch. Exit 2 is invalid input;
exit 0 means `requires_manual_approval`, never deletion authorization. All modes
only read the inventory; no provider/network/database/filesystem mutations occur.

The preview lists exact scoped identities, deletion effects, incoming consumers,
references, authority, last backup, D4/D7 handoff, rollback/evidence and blockers.
It hashes the entire inventory and selected plan for the approval/audit record.
Changing any inventory fact changes the plan. Observation must be no older than
24 hours and not future-dated. That bound does not eliminate stale state: inspect
the actual provider/reference state again immediately before manual execution.

An authorized human operator must approve the concrete set **after** reading the
preview and evidence. In protected custody record:

| Approval field | Required content |
| --- | --- |
| Scope | Stage, owner, exact scoped provider IDs, complete cascade/effects set |
| Plan | Inventory and plan SHA-256, observation instant, reviewed evidence |
| Decision | Explicit delete approval for this set, human operator, UTC time and validity window |
| Preservation | Last backup/recreation evidence, retained live/source/evidence checks, D4/D7 handoff |
| Authority | Current authority and retention/customer-hold review, separate policy decision if needed |
| Recovery | Recovery route and irreversible limitations; no promise that deleted provider IDs can be restored |
| Execution | Authorized executor, method, immediate preflight and planned post-checks |

Ticket creation, a passing preview, a checkbox, #377 closure or approval for
another set never satisfies this approval. Keep blocked targets retained; a
generic confirmation cannot override a blocker.

## Execute only a separately approved set

1. Capture sanitized prechecks plus private independent verification baselines
   for retained production/staging/UAT: exact bindings/authority, health/schema,
   full relevant content/integrity and audit state, frozen source/export/checksum
   inventories, NAS generations and document bytes/links. Use existing
   [PostgreSQL recovery](POSTGRESQL_RECOVERY.md), [audit recovery](AUDIT_RECOVERY.md),
   [NAS](NAS_POSTGRESQL_BACKUP.md), [document recovery](DOCUMENT_STORAGE_RECOVERY.md)
   and [cutover](BOOKKEEPING_CUTOVER.md) tools in their authorized read-only modes.
   Preserve per-profile/entity identity; never compare only local IDs or rebind a
   verifier to a fallback environment. Do not put private manifests in GitHub.
2. Immediately re-read provider IDs, parents/cascades and effective references.
   Regenerate the preview if any fact changes; obtain fresh approval for its new
   hash. Stop on uncertainty, active references, retained consumers or unmet
   retention/recovery needs. Do not interrupt live systems to make them eligible.
3. With the approved provider's normal operator console, delete only the exact
   reviewed disposable set. No blanket SQL, schema reset, recursive artifact
   purge, branch-name pattern or automatic retry after an uncertain result.
   If status is uncertain, inspect read-only and stop for operator reconciliation.
   Existing #244 test-harness teardown remains independently scoped to its own
   newly created fixtures; this procedure grants no extra harness authority.
4. Read back absence of exact approved targets and compare retained baselines.
   Verify unchanged live/staging/UAT bindings, authority, data/integrity/audit,
   document bytes/links, final source/exports/checksums, required recovery
   branches/snapshots/NAS generations and deployed migration files/revisions.
   Record each as observed pass, fail or unverified; commands/tests alone do not
   establish actual provider postconditions. Stop and invoke incident response
   on a mismatch. Do not claim success with missing postchecks.

For an inadvertent **config/reference removal**, suspend the cleanup and use
[deployment rollback](COMMERCIAL_DEPLOYMENT.md) / [incident response](INCIDENT_RESPONSE.md)
to restore the exact reviewed config/secret-store binding and compatible image.
Recheck health, identity, authority, schema and authorized access before resuming.
Never print secret values or auto-activate writers. For a deleted DB/artifact,
configuration rollback cannot recover data: escalate to the existing isolated
restore/recreation runbook, preserve incident evidence and seek authorization
before any live rebinding. Keep migrations forward-only; never squash deployed
history or overwrite the retained source as a cleanup repair.

Retain a sanitized audit record with target/plan hashes, owner approval reference,
UTC start/end, exact operation/result, pre/post-check outcomes, retained inventory
hashes, recovery limitations and remaining owner/re-review conditions. Keep
private results separately protected. If no set is approved (the current state),
record **retained; no deletion executed** and leave actual-resource acceptance
pending. #342 consumes the evidence; #224/#298 decide stage/release acceptance.

## Developer validation

```powershell
python -m pytest -q tests/tooling/test_resource_retirement.py
python -m ruff check tabula_rasa/deployment/resource_retirement.py scripts/preview_resource_retirement.py tests/tooling/test_resource_retirement.py
git diff --check
```

Synthetic tests cover eligible preview, retained/live/ambiguous targets, cascade
effects and consumers, two-scope isolation, stale inventory, malformed/unsafe
inputs, retention invariants, deterministic plan hashes and read-only CLI results.
They do not establish live inventory completeness, operator approval or successful
cleanup. Current-head CI remains the full-suite publication/merge gate.
