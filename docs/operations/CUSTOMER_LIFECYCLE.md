# Customer retention and closure

This guide owns customer lifecycle behavior and the retention review boundary.
It complements [audit retention](AUDIT_POLICY.md), [NAS recovery](NAS_BACKUP.md),
[receipt recovery](../storage/RECEIPT_RECOVERY.md), and
[customer handoff](../accounting/EXPORT.md). Public Terms/Privacy must describe
implemented behavior after owner and legal review; this guide is not a legal
determination or permission to admit external customers.

## Product policy decisions

The owner selected these product rules in the implementation discussion. They
do not approve destructive execution, statutory periods or public legal claims.

| Decision | Selected rule |
| --- | --- |
| Confirmed business closure | Bookkeeping becomes read-only; the owner retains export and cancellation during the recovery window. |
| Export and recovery window | 60 days after confirmation. |
| End of recovery window | Ordinary customer access ends; data remains preserved pending an explicitly approved deletion review. |
| Reopening within the window | Any current active Owner may cancel after recent sign-in. |
| Personal login closure | Separate from business closure; the last active business Owner cannot close their login. Transfer ownership or resolve the business separately first. |
| Login closure confirmation | Disable the local login and revoke all its sessions immediately; retain identity and history pending reviewed deletion. Provider identity deletion is separate. |
| Privacy erasure | Separate request and case-specific review of jurisdiction, statutory duties, holds and backup limits before erasure. |
| Export before business closure | Require the Owner's acknowledgement that needed bookkeeping and receipt exports were saved. This is an attestation, not proof of successful download. |
| Eligible live bookkeeping/receipt deletion | **Proposal:** 90 days after confirmed closure, leaving 30 days after ordinary access ends. No deletion is enabled until legal review, approved tooling and exact-target authorization. |
| Routine backup expiry | **Proposal:** 90 days from generation creation. Current indefinite NAS preservation remains effective until a separately reviewed replacement policy and tooling are approved. Holds, frozen sources and recovery evidence remain exceptions. |
| Immutable audit and lifecycle history | Finite retention is the desired direction; the duration remains for counsel to determine. Existing indefinite preservation and no-rewrite protections remain effective. |
| Legal holds | Manual restricted procedure; unknown or unresolved status blocks deletion. Formal hold registry/issuance/release tooling remains deferred. |
| Operational/security logs | Duration unresolved until actual provider inventory and legal review; no automatic expiry or claim of provider deletion. |

## Lifecycle stages and authority

| Stage | Access, retention and recovery |
| --- | --- |
| Active | Existing role-derived access and accounting controls; no new expiry clock. Ordinary unlink/delete business actions retain their existing audit and receipt-preservation semantics. |
| Suspended | Existing identity/operator suspension rules deny business access. Suspension is neither billing cancellation nor a deletion request, and starts no retention timer. Recovery/export needs verified support and restoration of appropriate authority. |
| Closure requested | Pending confirmation; normal access remains. The request can be cancelled. |
| Confirmed business closure, before day 60 | Read-only bookkeeping; Owner handoff, scoped connection recovery and recent-sign-in cancellation remain available. Data and background-job history are preserved. |
| Closed and retained, day 60 onward | Ordinary customer access ends without deletion. Late recovery requires support review. Being past day 90 does not itself authorize destruction. |
| Personal login closed | Local identity disabled and sessions revoked immediately; business records and stable historical attribution remain. A closed business whose private container still requires an active Owner can still block login closure until support resolves ownership. |
| Privacy request confirmed | Manual case review; no automatic purge, legal completion claim or statutory response deadline. |
| Destruction approved | Not an implemented state/command. Legal policy, holds, exact targets, recoverability, tooling and separate execution approval must all be resolved first. |

The product owner selected the access/window rules. Legal/privacy review must
determine applicable U.S./Canadian jurisdictions, statutory recordkeeping periods,
erasure exceptions, audit duration and disclosure obligations. Provider/recovery
operators must verify actual expiry/versioning/custody limits before changes. The
product owner separately approves production execution and launch; none of those
approvals is inferred from the product selections above.

## Store and retention inventory

Until a reviewed destruction plan is approved, preserve data. A proposed deadline
does not establish a statutory duty or authorize a provider setting change.

| Store | Current retention and lifecycle boundary | Destruction mechanism and limits requiring review |
| --- | --- | --- |
| PostgreSQL bookkeeping, business and membership rows | Authoritative live ledger and authorization records; closure must preserve accounting and cross-business isolation. | Explicit scoped plan must preserve required records, references, ownership and recovery evidence. No blanket cascade or shared-profile purge. |
| Identity sessions and login transactions | Existing environment-scoped expiry/revocation cleanup remains owned by authentication. | Revoking access is distinct from deleting identity-provider accounts or historical actor attribution. |
| Immutable audit, baseline and activation watermark | Indefinite interim retention, pre-storage minimization, no in-place redaction/pseudonymization; restricted operator inspection. | Statutory/privacy reconciliation, formal holds and any transformation require owner/legal approval. Customer bookkeeping export excludes audit contents. |
| Lifecycle and job history | Preserve minimized actor/scope, state and operation evidence. Jobs do not grant authority. | No history pruning is implied by cancellation or account closure. Maintenance must use the existing durable-job owner if selected. |
| Drive receipt bytes, originals, versions and unlinked inventory | Customer-owned Drive is the selected beta provider; unlinking removes references only. Recovery copies and unlinked files are preserved. | Exact document inventory and current authorized folder/grant are required. Unknown outstanding objects block deletion. Trash/version behavior and customer-controlled copies limit purge claims. |
| OAuth grant envelopes and provider authorizations | Business-scoped credentials are separate from login and shared application OAuth client configuration. | Local disconnect does not prove provider revocation. Export/recovery dependencies must be resolved before destroying grant access. Never revoke another business's shared grant implicitly. |
| Managed PostgreSQL snapshots/PITR | Provider configuration and verified recovery windows apply; SQL recovery does not recover receipt bytes. | No immediate erasure promise across historical recovery points. Hold preservation may require an independent retained copy before provider history expires. |
| NAS database and receipt recovery generations | Existing successful NAS generations are retained indefinitely; incomplete/quarantine/evidence obligations remain protected. | No automatic expiry, truncation or pruning. Any change requires an independently reviewed policy and exact-target approval. |
| Frozen Sheets sources and historical recovery artifacts | Source-format retirement and synthetic-resource retirement are separate procedures. | Customer closure never releases source preservation or authorizes rehearsal cleanup. |
| Temporary customer exports | Anonymous temporary files are closed after preparation failure, completed delivery or cancellation; no retained archive/link. | A downloaded customer copy cannot be recalled. Failure/stream interruption cannot prove the customer saved an archive. |
| Retained operator exports, source snapshots and reconciliation oracles | Private recovery/evidence custody and frozen-source obligations continue. These are not alternate live ledgers. | Individually review owner, purpose, hold and preservation obligations; the routine-backup proposal does not silently expire required evidence. |
| Browser/query caches | Session/business scope boundaries own invalidation and private-state clearing. | Revocation cannot erase files already downloaded or screenshots/customer copies. No private content in telemetry. |
| Operational/security logs and error telemetry | Minimized safe codes and request references; actual hosting/provider retention must be inventoried privately. | A product target is not evidence of provider deletion. Hold and incident obligations may override routine expiry. |
| Billing/payment-provider records | No paid provider is selected or activated by customer closure. | Future provider/legal obligations and cancellation/refunds require a separate commercial contract; login or business closure must not invent subscription semantics. |

## Request, confirmation and recovery procedure

Data & backup provides business closure for the selected business's current active
Owner, personal login closure and personal privacy review. Users without a selected
business can inspect their own requests and owned-business closure status from the
setup screen. Admin membership does not authorize business closure. Disabled users
and suspended businesses must use the existing private support channel; a request
reference identifies a case without sending financial contents through public tools.

1. Save the necessary Accountant handoff, with receipt bytes when needed. Resolve
   missing/unverifiable files before attesting that the necessary exports are saved.
2. Create a request. `pending` changes no ledger permissions. Review the exact
   business reference and effects before confirming. Confirm/cancel requires a
   verified sign-in within five minutes and the loaded request version.
3. Confirmed business closure starts 60 days of read-only access. Owner export and
   connection recovery remain available. PostgreSQL also blocks bookkeeping writes,
   including recurring workers and imports. Membership/ownership security
   administration retains its existing rules. Existing job histories/queued work are
   retained; no deletion job is scheduled. Cancelling closure does not change the
   recurring authority or promise replay of every missed occurrence; inspect the
   existing bounded job/reconciliation workflow before resuming it.
4. Any current active Owner may cancel within the window. Normal membership-derived
   access resumes. Lost/revoked ownership never grants cancellation authority. At
   expiry the business leaves ordinary discovery/selection and all entity reads,
   downloads and mutations require the usual active authorized context. Lifecycle
   status still shows `closed_retained`; self-service reopening has ended. An
   operator must review late recovery rather than changing dates or deleting rows.
5. Personal login confirmation independently disables the local identity and revokes
   every retained session. Last-owner safety is checked again in the transaction;
   this can stop confirmation after an ownership change. Identity, memberships,
   businesses and history remain retained. Provider login/account deletion and local
   reactivation require separate verified support/operator procedures. Reactivation
   must not revive old revoked sessions or cancel a business closure implicitly.
6. Confirmed privacy requests await case-specific review. No erasure or response
   deadline is automatically promised. The requesting actor may cancel while their
   account remains active; cancellation does not release a hold or erase the request's
   minimized audit evidence.

The narrow named APIs are `GET/POST /api/v1/customer-lifecycle` and
`POST /api/v1/customer-lifecycle/{request_id}`. Stable client request IDs, loaded
versions and idempotent repeated transitions handle uncertain HTTP results and
restart. Status reports state, policy version, recovery expiry, deletion blockers
and minimized transition history only; it is not a bookkeeping audit export or a
claim that backups/provider objects have been inventoried. A separate immutable
control-plane event table records actor, request, transition and timestamp in the
same transaction as each state change. Retain it with the database backup, including
identity/membership context; canonical bookkeeping exports deliberately exclude it.
Fresh account disablement can make an uncertain confirmation response unrecoverable
through the same login. Support must inspect the retained case; do not re-enable
identity merely to retry confirmation.

## Hold and destruction review

The operator keeps hold notices and scope in restricted legal/operator custody.
Do not put legal notices, reasons or customer contents into lifecycle events,
logs or public issues. Record the responsible reviewer, scope and private evidence
reference, any required preservation beyond provider windows, and counsel/owner
authority for release. Unknown or conflicting status remains blocked; there is no
automatic hold expiry or implemented formal hold registry.

Before approving deletion, inventory the exact business, authorization bindings,
live rows, canonical and unlinked document IDs, provider files/versions, grants,
jobs, caches, temporary files, logs, payment records and every applicable recovery
generation. Check current backup availability and document-byte recoverability,
retention exceptions, frozen-source duties and shared-resource effects. Record
what cannot be removed and how a later restore will preserve closure/hold decisions
instead of reopening access or silently resurrecting erased data. Restores to a
point before closure do not contain that later decision: reapply independently
retained closure/hold decisions under controlled operator review before exposure.
No purge executor exists, so incomplete inventory or unavailable recovery cannot
accidentally fall through to removal.

## Production and release approval

No real production deletion, provider retention change, archive disposal or legal
publication is authorized by implementation or migration. Before enabling such
an operation, the owner and appropriate legal reviewer must approve the applicable
jurisdictions/statutory duties, retained exceptions, customer disclosures, hold
handling, exact stores and targets, backup/byte recoverability and irreversible
step. Unavailable backups, unknown objects or unresolved holds block execution.
Never promise immediate destruction from all backup generations.

External beta and paid launch retain separate human release decisions. Internal
owner-operated authority and a successful synthetic test are not customer-release
or commercial-retention approval.
