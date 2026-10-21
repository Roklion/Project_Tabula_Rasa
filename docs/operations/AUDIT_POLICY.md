# Audit retention and access policy

This contract applies to application-mediated PostgreSQL history described in
[the atomic audit contract](JOBS_AND_AUDIT.md#atomic-audit-contract).
It defines retention and operator access; customer closure, erasure, cleanup and
audit export require separate policy and implementation.

## Decision and approval record

On **2026-10-19**, the repository owner explicitly approved the **interim operator
contract** in the implementation chat: indefinite retention, no in-place redaction or
pseudonymization, restricted operator inspection, and no customer audit export. This is
owner approval for the current operating stage, **not legal review, a statutory
retention determination or commercial policy approval**. The implementing PR and audit
retention policy update retain this decision's public reference.

| Decision | Status and responsible action |
| --- | --- |
| Retain audit events, baseline and activation watermark indefinitely; install no pruning | Owner-approved interim contract. Operator monitors growth/capacity; retention changes require a separate reviewed decision. |
| Preserve immutable event IDs, attribution and before/after evidence; minimize before storage | Owner-approved interim contract. No rewrite, actor replacement, re-keying or in-place pseudonymization. |
| Separately provisioned platform operators may inspect one authorized entity | Owner-approved interim contract. Provisioning owner approves exact operator/entity scope and private evidence custody. |
| No customer audit export through ordinary bookkeeping export | Owner-approved interim contract. customer data export must define and implement a separately authorized delivery contract before enabling it. |
| Statutory periods, jurisdictions, hold issuance/release, privacy exceptions and commercial disclosures | **Unresolved: owner/legal review required.** No proposed duration is treated as approved. |
| Finite retention, event destruction or privacy transformation mechanism | **Deferred proposal only.** Requires owner/legal authority, integrity implications, hold checks, archive treatment and separately reviewed tooling before any execution. |

## Retention, holds and privacy requests

Retain all events, `audit_baseline` and `audit_activation`, including evidence
for deleted bookkeeping targets. Time passing, cancellation, unlinking a receipt,
an old recovery point or a storage-capacity warning does not authorize deletion.
No expiry clock, purge endpoint or retention worker exists. An operational hold
cannot expire automatically because nothing is pruned in this version.

Until a legal hold workflow is approved, the owner records notices and their
scope in restricted operator/legal records, preserves relevant source and
recovery artifacts and stops any separately proposed destructive operation.
There is **no implemented hold registry, automated release or legal compliance
certification**. Legal counsel must decide preservation beyond provider history
windows before relying on those windows for a hold. A hold does not make expired
PITR history recoverable.

Minimize fields **before** event persistence. SQL `audit_summary` allowlists
identifiers, dates, amounts, classifications/status and provenance; `_redacted`
means intentional omission, not a later alteration. Names, notes, references,
addresses, filenames, locators, credentials and receipt bytes are excluded.
Financial measures, stable actor IDs, entity/org IDs and operation identifiers
remain sensitive, linkable information. Internal row digests are reconciliation
aids; they are neither anonymization nor cryptographic tamper evidence.

A bookkeeping correction creates new events and does not rewrite the old ones. A privacy
request is referred to the owner/legal decision process; this version cannot promise
event erasure or replacement with pseudonyms. Any future permitted transformation must
account for stable attribution, digest verification, backups, hold restrictions and
truthful historical disclosure. Never silently disable append-only protections or invent
an actor to satisfy a request. the accounting control service's period locks, correction
journals and protected reasons remain independently enforced.

## Readers, exports and operational evidence

`AuditReader` requires **both** `platform:operate` and `audit:inspect`, plus an explicit
server-authorized entity. Ordinary ledger read/export rights grant neither audit
inspection nor audit export. privileged support operations's inspection UI remains
separate; customer data export owns customer export. No customer audit export is
authorized by this policy.

Provision migration/function ownership separately from the ordinary runtime.
Runtime must have no audit DML, DDL, ownership or RLS bypass. Grant audit SELECT
only to the provisioned inspector or trusted API serving separately provisioned,
expiring [support grants](SUPPORT.md); the latter revalidates named
operator, environment and organization on each request. Direct recovery
inspection also needs the canonical SELECT used by its verifier.
RLS scopes non-owner reads; the reader also applies explicit
entity predicates for owner connections. GUC scope and capabilities are trusted
server infrastructure, not browser claims. A DBA can bypass PostgreSQL controls;
the guarantee is application append-only history, not malicious-DBA resistance.

Restricted recovery operators may retain private comparison manifests and
archives for the exact approved drill. These are operational evidence, not a
general customer export permission. Protect them with restricted ACLs/encryption
and approved custody; publish counts, fixed diagnostic codes and evidence
references only. Do not log or commit events, financial contents or credentials.

## Activation, restore and archive interpretation

The original activation watermark and baseline mark pre-audit records as
`pre_activation_unavailable`. Later edits preserve that marker. Imports record
the accepting operation, never fictional original source actors or history.
A point before audit activation has **no audit history available**. Inspect it
with its retained release; do not migrate/stamp it and claim that newly generated
baseline evidence proves historical recovery.

Restore ledger and audit objects **from the same point**, retaining original event IDs,
sequences, actor/scope, schema, triggers/functions/policies, baseline and watermark.
Verify retained history as well as current ledger-to-event consistency using the
companion recovery work tracked in [operational readiness
verification](AUDIT_RECOVERY.md). A mismatched or partial history must stop recovery
acceptance. An old coherent restore lacks its later tail: record requested and actual
points, known missing interval, independently retained evidence and any unresolved
uncertainty. Never reset the watermark or fabricate missing events.

[NAS retention](NAS_BACKUP.md) remains **indefinite with no automatic pruning**.
Restoring an archive copies historical events; it does not authorize rewriting/deleting
the original generation. Preserve manifests, decryption custody and hold-relevant
generations. A restored old generation may contain data later removed from the live
ledger; do not promise immediate erasure across all copies.

[Managed database recovery](DATABASE_RECOVERY.md) retains its independently observed
provider history/capacity limits. This policy does not extend PITR availability, change
snapshot retention or authorize provider/NAS changes. Owner/legal review must reconcile
finite provider windows and indefinite archives before adopting commercial
retention/erasure or hold claims. Actual audit-aware restore evidence belongs to
operational readiness verification; earlier bookkeeping-only drills do not satisfy it.

## Enforced controls and remaining gaps

| Contract | Existing technical enforcement | Remaining responsibility |
| --- | --- | --- |
| No pruning; append-only history | `0012_operations` rejects audit update/delete/truncate and direct event insert; baseline is frozen; no cleanup API/job | Capacity monitoring, correct deployed role grants, owner/legal approval before any change |
| Minimized capture and truthful identity | SQL allowlist; trusted audit context; named membership check; same-transaction triggers | Legal assessment of retained linkable IDs/financial measures; future privacy workflow |
| Authorized inspection | `AuditReader`, separate capabilities, explicit entity predicate and database RLS | Operator/entity provisioning and effective deployed permissions; privileged support operations and customer data export consumers |
| Historical gaps | Immutable activation/baseline and `boundary()`; current-state verifier | Restore evidence, unavailable-tail disclosure and archive comparison under operational readiness verification |
| Holds and erasure | No automatic destruction to override a hold | Restricted manual notice record; legal hold process and approved policy, no automated legal claims |

No new runtime control is necessary to make this bounded interim policy truthful:
it adopts the existing no-delete/no-export boundary and explicitly exposes the
manual and legal gaps. Native audit, authorization and period tests validate the
existing controls; deployment grants still need environment-specific evidence.

Customer account closure, deletion/grace periods, customer export UI, generalized
orphan cleanup and full commercial data lifecycle are outside this interim audit
policy. They require separately specified legal and product decisions. The
current audit contract still requires policy acceptance and actual recovery
evidence for its own supported scope.
