# Controlled staging incident drill

Runbook version 1. The [incident guide](INCIDENT_RESPONSE.md) owns triage,
[deployment guide](DEPLOYMENT.md#promotion-failure-and-rollback) owns
promotion, and [named rollout](../identity/HOSTED_ROLLOUT.md#compatible-application-rollback-and-incidents)
owns auth compatibility. Reuse their tools; no failure endpoint, broad data reset,
extra deploy workflow or automatic credential revocation is introduced.

## Scope and authorization record

Choose a controlled compatible-image rollback on synthetic staging. Obtain
explicit authorization for the exact staging scope/window and retained images;
record primary/alternate and accepted limits privately. No production cutover,
provider purchase, data deletion, schema change or credential modification is
part of this drill. Reserve the existing promotion concurrency group; check for
queued/running promotion and coordinate other operators before each dispatch.
Unexpected external changes stop the exercise for inspection.

Select two different immutable releases with the **same deployed schema**, both
reachable from main with successful main-push `Full test suite` evidence. Record
requested index and verified runtime-manifest digests. For named mode compare
identity configuration/epoch and authorization semantics as well as schema.
Retain the initial live digest and a procedure to return to it. If only one
compatible named image exists, record a blocked preflight; neither an older alpha
image nor a repeated same-image deploy counts as a rollback.

Prepare safe public probes and the applicable deployment browser smoke. Privately retain
an existing synthetic named session, selected business, record/report checks and receipt
digest **only when approved fixture access exists**. Verify a second business remains
isolated. Never create a live identity, grant, receipt or ledger entry to make this
drill green. Missing fixture access means narrower Deployment-boundary evidence and
pending full named/data/byte coverage.

## Execution and measurable outcomes

1. Record UTC preflight start, initial `/version`, live/ready status, access mode,
   endpoint binding reference, image/schema and CI links. Capture only minimal
   public probe fields. Confirm the staging window and retained return image.
2. If needed to establish two live candidates, promote the compatible comparison
   image through the existing staging workflow on main. Record workflow source
   SHA separately from selected image SHA. Wait for completion; inspect every
   schema/registry/Render/smoke step. On failure stop and follow incident recovery;
   an uncertain POST/poll is not permission to issue a compensating deploy.
3. After that release is confirmed healthy, declare a **simulated code-regression
   rollback decision** (not a real outage). Record declaration UTC, severity,
   signal/diagnosis and selected retained return image. This exercises deliberate
   operator rollback without corrupting data or disrupting credentials. Start
   observed response/recovery timing here, including dispatch/queue time.
4. Dispatch the retained compatible return digest through the same workflow.
   Record dispatch/queue/start/completion times and run URL. Require bound schema,
   immutable registry/Render identity, readiness and mode-specific smoke success.
   Independent `/version` must match the return release and readiness must be 200.
5. Run available authorized fixture checks: fresh membership, prior session's
   expected validity (unless a separately approved rotation occurred), allowed/
   denied business access, retained record/report/export and exact receipt bytes.
   Confirm no new schema/data/authority/secret mutation occurred as part of the
   exercise. Describe pending checks truthfully; no fixture access means no
   claim that data/receipt preservation was independently observed.
6. Record verified UTC, observed declaration-to-boundary recovery duration,
   total exercise duration and each pass/fail/pending result. Leave staging on
   its initial live digest, verify no drill deploy remains queued/in progress,
   and release the window. If the drill stopped after step 2, retain restricted
   service state and an explicit follow-up owner; never claim initial state was
   restored without observing it.

No actual data loss is induced; observed RPO is **not measured**, not zero.
Deployment-boundary recovery duration is not full-service or database-restore RTO. Do
not compare it to unapproved commercial recovery agreement proposals. The controlled
operator decision is the exercise signal; it does not prove alert delivery, automatic
failure detection, a real code fault or a provider outage.

## Evidence and follow-up

Use the [redacted incident format](INCIDENT_RESPONSE.md#timeline-evidence-and-closure).
Retain release/schema/index/runtime digests, CI/promotion links, UTC checkpoints,
fixed probe/smoke outcomes, observed duration, private evidence reference and
limitations. Exclude credentials, cookies, emails, tenant/record/provider IDs,
response bodies, raw logs, receipt bytes and private exports. A separate operator
should be able to repeat this runbook from approved access; their actual review
is still required, not inferred from an assistant's execution.

The [recorded staging
exercise](https://github.com/Roklion/Project_Tabula_Rasa/issues/340#issuecomment-6303989966)
records only observed results. platform operations and operational readiness
verification consume the engineering evidence and gaps. commercial recovery agreement
must review the handoff and record human acceptance or requested improvements privately;
external release and customer lifecycle controls external release. Hosted login, session
revocation, document-byte recovery and an alternate operator remain independently
verified requirements wherever the selected stage needs them. This exercise does not
close those tickets or authorize their execution.

## Dependency and job drill preflight

Use the existing identity, job, document, support and recovery tools; this
procedure introduces no failure endpoint or automatic fault injector. Before
execution the operator approves an exact isolated synthetic target, release and
schema/topology, fixture scope, window, permitted faults/mutations and restoration
plan. Record an incident commander, dependency/recovery owners, private evidence
custody, alert recipient and stop/escalation conditions. Confirm no competing
operators or writers. A general request for operational readiness does not select
an outage target or approve changing live secrets, grants or infrastructure.

Choose isolation that cannot affect the working owner service or a shared
provider. A dedicated application-side egress rule may isolate a dependency only
if its scope and removal are explicitly approved and supported. If the provider
or hosting tier cannot safely isolate the selected target, retain the drill as
unperformed and request a suitable executor. Never disable a shared provider,
exhaust shared quotas, rotate live credentials or stop a production database as
a simulation. Keep configuration faults on an isolated synthetic process.

Record baseline release/readiness, named fixture access, selected-business
isolation and applicable DB/document integrity. Obtain the required exact-image
promotion approval before using a newer release; do not silently promote main.
Use the existing deployment concurrency window for staging, and separately
coordinate job operators not controlled by that lock. Retain original settings,
compatible rollback image and a bounded return procedure. Restoring connectivity
must not revive an obsolete configuration epoch or divergent Sheets writer.

| Drill | Required observed sequence and evidence | Independent boundary |
| --- | --- | --- |
| Identity provider unavailable | Prove approved app-side unreachability; start a fresh named login; observe safe failure with no synthetic/Basic fallback; correlate safe identity event and delivered incident; remove isolation and complete a new successful login; verify recovery notification | Existing valid durable sessions may continue with fresh membership until expiry/revocation. This is not successful password/mail/factor or administrator recovery. |
| DB/session-store unavailable | Under approved isolated interruption, protected reads/writes/receipt bytes deny and private browser views clear; record durable logout/revocation uncertainty; restore connectivity, reconcile/revoke uncertain sessions and verify fresh login plus scoped access | Cookie clearing is not durable server-wide revocation. Readiness alone does not establish bookkeeping or receipt integrity. |
| Configuration epoch/session topology | Follow the canonical generation/epoch rotation with drained isolated workers; retained old-session copies and old-configuration workers must fail; restart selected workers and verify new login and independent-user behavior | Secret/epoch changes need explicit approval. Prove the selected worker topology; single-worker proof does not attest multiple workers. Never roll back to old generation material. |
| Document provider unavailable | Use approved isolated provider unreachability and an existing synthetic document operation; verify safe unavailable classification, preserved original bytes/links, delivered document incident, then restored exact-byte access and incident recovery | Permission denial, revoked consent, quota failure and unavailable are distinct outcomes. Do not delete/reupload receipts or rebind existing grants to manufacture recovery. |
| Recurring/job failure and remediation | Select one approved synthetic workload and permitted reversible cause; inspect durable attention/attempts and actual failure class; verify eligible retry or terminal-failure incident as applicable; correct the cause, deliberately retry when safe, verify one effect/no duplicate and retained history, then resolve only after successful remediation | A successful ledger probe is not recurring scheduling or financial generation. A transient queued attempt is not a terminal failure. No timer or real financial writes are authorized by this guide. |
| Scoped privileged denial | Use a normal authorized synthetic client with in-memory cookie/CSRF handling and valid Origin/CSRF; select a registered read-only support action for approved scope without a support grant; require handler-level `privileged_denied`, correlated release/request and the stage-approved alert/notification | CSRF `authorization_denied` does not prove privileged denial. Do not extract browser secrets, create a grant, brute force or flood the endpoint to satisfy an alert threshold. |
| Notification delivery | Correlate the actual incident, safe event, recipient receipt/acknowledgment and recovery; restore any explicitly approved temporary threshold and retain timestamps | For GitHub failure email, use an applicable genuine failed run and recipient evidence. Do not induce an unrelated failure or infer delivery from an enabled toggle. |

Follow [hosted identity rehearsal](../identity/HOSTED_ROLLOUT.md#hosted-rehearsal-and-expected-results)
and [epoch recovery](../identity/AUTHENTICATION.md#revocation-and-owner-recovery),
[job inspection/retry](JOBS_AND_AUDIT.md),
[document recovery](../storage/RECEIPT_RECOVERY.md),
[support authorization](SUPPORT.md) and
[alert predicates](OBSERVABILITY.md#metrics-alerts-and-first-triage).
If no approved normal-client route or safe isolation exists, stop that drill and
record the exact missing route/access/approval. Do not substitute fabricated
events, direct database tampering or source tests for hosted evidence.

After each drill, remove only its approved fault, verify release/topology and
scope, inspect uncertain mutations before retry, and confirm original bytes and
unaffected-business state remain intact. Check no fault control, competing job
or pending deploy remains, and record any unresolved condition with its owner.
For DB-plus-bytes restore, use the canonical independent
[database](DATABASE_RECOVERY.md), [audit](AUDIT_RECOVERY.md) and
[receipt](../storage/RECEIPT_RECOVERY.md) verifiers on new isolated targets;
preserve capture/restore lineage and mismatched-point limitations. No restore
onto retained staging/production or service rebinding is implied.

Keep per-step pass/fail/unperformed outcomes, observed UTC times, safe codes,
release/schema/topology, workflow links and opaque private evidence references
in the operational discussion. Record provider/logging/custody/retention gaps
and stage-specific acceptance separately. Reuse earlier evidence only within its
recorded release and scope; a new plan or successful local test is not a new
hosted pass. Human admission, production activation and paid-release decisions
remain separate from this technical evidence handoff.
