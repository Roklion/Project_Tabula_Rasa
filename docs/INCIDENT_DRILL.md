# Controlled staging incident drill

Runbook version 1 for #340. The [incident guide](INCIDENT_RESPONSE.md) owns triage,
[deployment guide](COMMERCIAL_DEPLOYMENT.md#promotion-failure-and-rollback) owns
promotion, and [named rollout](AUTHENTICATED_ROLLOUT.md#compatible-application-rollback-and-incidents)
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

Prepare safe public probes and the applicable deployment browser smoke. Privately
retain an existing synthetic named session, selected business, record/report
checks and receipt digest **only when approved fixture access exists**. Verify a
second business remains isolated. Never create a live identity, grant, receipt or
ledger entry to make this drill green. Missing fixture access means narrower
deployment-boundary evidence and pending full named/data/byte coverage.

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
Deployment-boundary recovery duration is not full-service or database-restore
RTO. Do not compare it to unapproved #298 proposals. The controlled operator
decision is the exercise signal; it does not prove alert delivery, automatic
failure detection, a real code fault or a provider outage.

## Evidence and follow-up

Use the [redacted incident format](INCIDENT_RESPONSE.md#timeline-evidence-and-closure).
Retain release/schema/index/runtime digests, CI/promotion links, UTC checkpoints,
fixed probe/smoke outcomes, observed duration, private evidence reference and
limitations. Exclude credentials, cookies, emails, tenant/record/provider IDs,
response bodies, raw logs, receipt bytes and private exports. A separate operator
should be able to repeat this runbook from approved access; their actual review
is still required, not inferred from an assistant's execution.

The [recorded #340 staging exercise](evidence/incident-340/staging-drill.md)
records only observed results. #223/#342 consume the engineering evidence and
gaps. #298 must review the handoff and record human acceptance or requested
improvements privately; #224 controls external release. Hosted login, session
revocation, document-byte recovery and an alternate operator remain independently
verified requirements wherever the selected stage needs them. This exercise
does not close those tickets or authorize their execution.
