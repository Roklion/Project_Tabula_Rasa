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
| Eligible live bookkeeping/receipt deletion | Owner-selected product policy: eligibility 90 days after confirmed closure, leaving 30 days after ordinary access ends. Eligibility requires resolved holds and legal exceptions, complete inventory and recovery safeguards. No deletion is enabled until legal review, approved tooling and exact-target authorization. |
| Routine backup expiry | Owner-selected product policy: 90 days from creation for future routine generations under an approved replacement schedule. Preserve all existing NAS generations until a separately approved historical-disposal plan. Current indefinite preservation remains effective until legal review and replacement tooling are approved; the policy selection starts no automatic expiry. Holds, frozen sources and recovery evidence remain exceptions. |
| Immutable audit, lifecycle and support history | Preserve audit, lifecycle and support history on an interim basis without a fixed end date pending a legal decision on duration and exceptions. Existing audit no-rewrite protections remain effective. Any transformation or pruning requires separate approval. |
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

## Jurisdiction and legal review

The owner identified businesses in **Delaware, New York and Connecticut, U.S.,
and British Columbia, Canada** for the retention review. External counsel's
approval remains pending. A business's formation or operating location does not
establish every affected individual's residence or all applicable laws. Before
review, privately confirm the contracting service operator, operating locations,
customer/data-subject locations, processing locations, customer sectors and the
operator's role for each purpose. Do not infer a regulated-sector exemption or
that business bookkeeping contains no personal information.

The following primary sources identify questions for counsel, not an approved
schedule or a conclusion that a particular law applies. Recheck effective dates
and amendments for the actual release and review date.

| Review area | Source and decision needed |
| --- | --- |
| U.S. federal business records | [IRS recordkeeping periods](https://www.irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records) vary with the record and circumstances. Determine the customer's duties, any independent operator duties, state-specific duties and the records needed for property, disputes or other exceptions. Do not equate the proposed service-copy deletion date with the customer's lawful record-destruction date. |
| Canadian business records | [CRA keeping records](https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/rc188/keeping-records.html) generally requires six years from the end of the relevant tax year, with exceptions; outsourcing does not remove the record keeper's responsibility. Review readable customer exports, receipt originals, access and cross-border storage, and whether the service has separate retention duties. |
| British Columbia personal information | [PIPA sections 3, 23 and 35](https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/03063_01) require applicability, access and retention analysis. Section 35 includes a one-year minimum for information used to make a decision directly affecting an individual and destruction/de-identification conditions when purposes end. Determine which identity, access, support and ledger records fall within these rules before accepting a 90-day schedule or indefinite audit retention. |
| Canadian federal/interprovincial processing | [PIPEDA retention guidance](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/p_principle/principles/p_use/) calls for purpose-based retention and documented minimum/maximum periods. Counsel must resolve its interaction with provincial law, cross-border processing and the actual operator/customer roles. |
| Delaware personal data | Review [Title 6, chapter 12D](https://delcode.delaware.gov/title6/c012d/index.html), including current and future effective versions, covered-consumer definitions, applicability thresholds, controller/processor contracts, deletion rights and exceptions. A small business cohort alone does not establish the number or status of individuals represented in receipts and ledgers. |
| Connecticut personal data | Review the [Attorney General's CTDPA guidance](https://portal.ct.gov/ag/sections/privacy/the-connecticut-data-privacy-act) and applicable amended law for the release date: coverage, business-context exclusions, controller/processor responsibilities, rights handling and exceptions. Determine whether any recorded data triggers additional rules; excluded product workloads are not evidence that prohibited data can never be submitted. |
| New York private information | Review [SHIELD Act safeguards and disposal guidance](https://ag.ny.gov/resources/organizations/data-breach-reporting/shield-act), applicable tax/recordkeeping rules and any sector-specific obligations. Identify protected fields, service-provider responsibilities and disposal safeguards; no universal New York retention period is selected here. |

### Decision package and approval evidence

Supply counsel with this guide's product rules and store matrix, the implemented
[export contract](../accounting/EXPORT.md), [audit policy](AUDIT_POLICY.md),
[receipt recovery](../storage/RECEIPT_RECOVERY.md),
[observability inventory](OBSERVABILITY.md), and the proposed customer disclosures.
The existing public Terms/Privacy describe internal/private use; they are not
evidence of approval for unrelated customers or the proposed deletion schedule.
Use synthetic examples. Hold notices, personal data, provider account details,
legal advice and exact execution targets stay in restricted custody.

| Required decision | Evidence needed before acceptance |
| --- | --- |
| Applicable duties and roles | Counsel identifies covered jurisdictions, purposes, data categories, controller/processor or equivalent roles, exclusions and record-specific statutory/contractual duties. Confirm the service operator and authorized privacy contact privately. |
| Live data and receipts at day 90 | Legally approve, revise or reject the owner-selected eligibility by store/category, with the clock's start, minimum/maximum periods, customer export responsibilities and longer-duty exceptions. An owner's saved-export acknowledgement does not discharge a statutory duty or prove a readable complete copy. |
| Audit, lifecycle and support evidence | Decide a finite duration or a justified interim exception for stable actor IDs, financial measures, access decisions and case history. Assess immutable rows and digests, access rights, erasure exceptions and any permitted transformation. No audit rewrite/pruning is enabled by review preparation. |
| Routine backups at 90 days | Legally review the owner-selected future-generation schedule against actual managed PITR/snapshot windows, receipt-byte copies, credential/key custody, frozen sources and holds. Existing NAS generations remain preserved; any historical disposal needs a separate reviewed plan. Define the activation boundary for future generations before enabling expiry. A future expiry policy cannot silently dispose of historical evidence. |
| Operational/security logs | Inventory actual Render, Better Stack, identity-provider, database, NAS, Actions and support/incident copies that exist. Record fields, purpose, geography, access, configured retention, exported copies and incident/hold exceptions. Published plan limits and older staging evidence are not current account readback or a legally approved duration. |
| Individual-rights requests | Define verified intake, responsible reviewer, received date, applicable response/extension/appeal deadlines, authority to act for a business or another individual, permitted refusals and private decision evidence. A manual workflow or an unapproved erasure mechanism does not suspend a legally applicable response deadline. Escalate promptly rather than waiting for day 60 or 90. |
| Holds and destruction | Identify who may issue/release a restricted manual hold, the evidence required for a known-clear decision, exceptions and preservation beyond provider windows. Approve exact-store destruction methods, verification limits, shared-resource isolation and the treatment of later restores. Unknown status still blocks destruction. |
| Customer disclosures | Owner and counsel reconcile retention, access expiry, export limits, provider/customer-held copies, residual backups, support and rights handling with the actual Terms/Privacy. Approval of wording, publication, customer admission and production execution are separate decisions. |

For each accepted decision, retain the reviewer and authority, review date,
policy revision, applicable scope, decision/rationale, private advice reference,
exceptions, expiry/review trigger and owner approval. Public evidence contains
only a sanitized decision and approval reference. Do not mark legal review
complete from a prepared package, a proposed duration or an implementation merge.

### Applying an approved schedule

After counsel and owner approve the policy, the engineering owner maps every
approved category to its actual storage and recovery copies and implements the
required mechanism through the normal reviewed change process. Verify denial
for missing approvals, unknown holds, unavailable recovery, incomplete document
inventory and another business's data; verify the approved success path,
interruption/restart and later-restore behavior on synthetic resources. A passing
deletion test does not authorize a real target. Separately record operator
approval, exact scope and irreversible step before any production operation or
provider setting change. Until these gates pass, current preservation applies.

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
| Support correspondence and privacy case records | Preserve relevant case history in approved restricted custody pending a legal decision on duration and exceptions. | Inventory the actual support channels, custody locations and retained copies privately. |
| Operational/security logs and error telemetry | Minimized safe codes and request references; actual hosting/provider retention must be inventoried privately. | A product target is not evidence of provider deletion. Hold and incident obligations may override routine expiry. |
| Billing/payment-provider records | No paid provider is selected or activated by customer closure. | Future provider/legal obligations and cancellation/refunds require a separate commercial contract; login or business closure must not invent subscription semantics. |

For each provider, distinguish the retrievable history window from underlying
storage retention, exported copies and verified destruction. For example,
[ZITADEL audit history](https://help.zitadel.com/audit-trail-history-events)
describes events retrievable through its API or GUI, subject to subscription
limits. Its [cloud log guidance](https://help.zitadel.com/access-and-runtime-logs)
also separates log availability from retrieval limits. A query window or an
unavailable console view does not establish that older provider-held data was
purged. Record unresolved provider preservation/deletion limits explicitly.

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

## Manual privacy-request handling

The service owner is the primary privacy reviewer. This manual responsibility
does not grant additional application, database or provider access. Use approved
restricted case custody for requests received through the private support path
or the lifecycle review queue; neither GitHub issues nor application telemetry
is a case store. A disabled login or expired business-access window must not
prevent the reviewer from accepting a request through that support path.

1. Record the received date/time in UTC or with an explicit time zone offset,
   along with the private case reference, assigned reviewer, requested right and
   scope. Preserve the original receipt date when linking
   repeated submissions or an application request; confirmation, verification
   or a restart does not silently replace it.
2. Verify the requester's identity and authority for the requested scope through
   the approved private channel, collecting only necessary evidence. Business
   ownership and an individual's rights require separate analysis; a business
   role alone does not resolve every personal-information request. Do not request
   passwords, session cookies or provider tokens as verification evidence.
3. Obtain legal determination of applicable duties and response, extension and
   appeal deadlines, and track them with the responsible reviewer. Escalate an
   unknown deadline promptly for legal review; do not wait for closure day 60 or
   90 or for deletion tooling. Manual review does not suspend applicable clocks.
4. Review the relevant stores, provider/customer-held copies, holds, required
   preservation and supported export/recovery limits. Require legal review
   before denying rights or releasing a legal hold. No request, cancellation,
   product retention selection or case decision substitutes for approved
   destruction tooling and exact-target execution authority.
5. Keep the verification outcome, legal decision reference, authorized response,
   actual actions, unresolved limits and completion date in restricted custody.
   Disclose effects and limits through the verified private channel. Record any
   legally required extension or appeal handling; do not mark a case fulfilled
   merely because it was queued, access was revoked or a query window expired.

This procedure establishes manual ownership and handling, not a deployed case
management system, an automated deadline scheduler, a legal applicability
decision or approved public rights wording. Counsel's jurisdiction/category
decisions, approved custody/contact arrangements and disclosure review remain
required before claiming commercial rights-handling readiness.

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

Provision runtime privileges separately from migration ownership. Named-session
readers need SELECT on `customer_lifecycle_requests` because access resolution
checks closure expiry and lifecycle version even when serving other workflows.
Ledger-writer and worker roles also need that SELECT for the SQL closure guard.
The lifecycle command adapter additionally needs INSERT/UPDATE on that request
table, SELECT/INSERT on `customer_lifecycle_events` and USAGE on its identity
sequence, alongside its existing scoped identity/session privileges. It needs no
DELETE/TRUNCATE or table ownership. A support-only adapter does not need these
lifecycle mutation/event grants. The migration grants none automatically; verify
the approved runtime role with synthetic sessions before exposing the feature.

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
