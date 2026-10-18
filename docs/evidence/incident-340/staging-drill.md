# #340 authorized staging rollback evidence

Runbook version 1; execution date **October 17, 2026 America/New_York**
(October 18 UTC below). Scope: #340 implementation under #223/#124. The user
explicitly authorized a non-destructive synthetic staging rollback drill in the
implementation chat. Codex executed it using existing operator tooling. No
production, credential, provider-plan or data-deletion action was authorized or
performed. This is a sanitized observed record, not #298 commercial sign-off.

## Selected releases and preflight

Staging was independently observed healthy on the original release, with GitHub's
staging access mode `named_user`, no queued/in-progress staging promotion and
schema `0012_operations` verified by its prior successful promotion. The exercise
retained that exact original image as the return target. Runtime credential and
endpoint bindings stayed with the existing staging workflow; no secret values
were retrieved or copied into the record.

| Field | Original / rollback target | Comparison release |
| --- | --- | --- |
| Image release SHA | `685c44c62d79430d5db349afedea73b0fa47c4f2` | `5f9cc400b876f6658518a1d9ce654d12ec8a6a42` |
| Repository | `ghcr.io/roklion/project_tabula_rasa/commercial` | Same |
| Requested index digest | `sha256:90e051ac2744b752a62fbd8d586a86bf06aa81284f9a60e58b169099fffeccb3` | `sha256:66655dd6192f7eabd18b7f199f1feb0777517745fc522a7f3f040514b716769e` |
| Verified linux/amd64 manifest | `sha256:8639f516dae994c6e2fcb44bd091648963774b48cce2d926071a05a7d3ec3a66` | `sha256:8d0f31cd35d85899b28b0f328e382cb07b6df553ad90100e0a6722d02f1f1268` |
| Image schema head | `0012_operations` | `0012_operations` |
| Main-push Full test suite | [38991408454](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38991408454), success for this SHA | [39000393829](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39000393829), success for this SHA |

Both releases were retained main ancestors. The named session repository, OIDC
adapter and control-plane repository had no changes between them. HTTP changes
were inspected: explicit hosted access-mode handling and safe telemetry did not
change the session configuration hash/epoch contract. Staging mode was already
explicit. No schema transition, identity configuration change or restored-session
state was part of this code-only rollback.

The workflow source SHA for **both** new runs was
`ed10277a9a72733cbbcac0afaa6aba7bf1c9c401`, distinct from the image SHAs.
The existing workflow executes the selected immutable image's bound head-only
database check. Both confirmed the retained 0012 schema; the newer workflow
source does not mean staging upgraded to 0013. No latest-main image was deployed.

## Executed timeline (UTC)

| Checkpoint | Observed instant / evidence |
| --- | --- |
| Comparison promotion dispatch | `2026-10-18T01:02:43Z`; [run 39085020469](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39085020469) |
| Comparison named deploy/smoke completed | `2026-10-18T01:04:54Z`; workflow succeeded at `01:04:57Z` |
| Independent comparison baseline | `/version` matched `5f9cc40…`, readiness 200; no queued/in-progress staging promotion before rollback dispatch |
| Simulated regression / rollback declaration | `2026-10-18T01:06:00.3677046Z`; deliberate SEV2 operator decision, no real outage induced |
| Rollback dispatch | `2026-10-18T01:06:01Z`; [run 39085228542](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39085228542) |
| Rollback job start | `2026-10-18T01:06:06Z` |
| Rollback image verification | Completed `2026-10-18T01:06:26Z`, success |
| Rollback bound database check | Completed `2026-10-18T01:06:35Z`, success |
| Rollback named deploy/smoke | Completed `2026-10-18T01:08:01Z`, success |
| Rollback workflow complete | `2026-10-18T01:08:05Z`, success |
| Independent final boundary verification | `2026-10-18T01:08:36.5422022Z`: original release `685c44c…`, live 200, ready 200 |
| Window completion check | No queued/in-progress staging promotions; GitHub staging mode remained `named_user` |

Conservative declaration-to-independent-boundary recovery: **157 seconds**
(156.175 seconds rounded up), including dispatch/queue and verification delay.
The two-dispatch execution span was **354 seconds rounded up**, excluding earlier
preflight. These are controlled deployment-boundary timings, not database/full-service
RTO, an availability SLO or compliance with unapproved #298 proposals. No data
loss was induced and **RPO was not measured**. There was no real code failure,
injected outage, alert-delivery or automatic incident-detection measurement.

## Results and explicit limits

| Check | Outcome / scope |
| --- | --- |
| Distinct images, real promotion and return | Pass; both workflows succeeded, original release restored. No same-image redeploy or mocked rollback. |
| Immutable index/runtime integrity | Pass in both existing registry/Render deployment checks. |
| Bound schema/connectivity | Pass in both image-specific database checks and readiness; no bootstrap/downgrade/restore performed. |
| Named access boundary | Pass in both existing browser smokes: public sign-in shell, expected release/readiness, denied anonymous/forged-Basic private paths and routing. |
| Final state | Pass; independent live/ready 200, original release and named mode, no outstanding drill deploy. |
| Logged-in session/role/two-business fixture | Pending actual hosted fixture access/acceptance under #321/#320. Anonymous smoke does not prove named login or issued-session continuity. |
| Retained bookkeeping and exact receipt bytes | Pending independent authorized fixture reads/digests. The drill performed no ledger/document writes, but content preservation is not inferred from readiness. |
| Secret rotation / copied-session revocation | Not performed in this image-only drill; use [secret operations](../../SECRETS_OPERATIONS.md). |
| Human technical handoff | Accepted with listed gaps by the requesting human in the implementation chat on October 17, 2026 America/New_York. Alternate recovery access/usability remains pending. |
| New-endpoint active-authority rebinding | Not exercised; no generic safe command exists. Preserve the [service-binding stop](../../INCIDENT_RESPONSE.md#database-recovery-and-safe-service-binding). |

No credentials, cookies, private bodies, raw logs, fixture IDs, exports or bytes
are retained here. Workflow links and minimal public probes support the stated
scope; no private artifact or human attestation is fabricated.

## Cross-initiative handoff

| Owner | Deliverable / outstanding decision |
| --- | --- |
| #340 / #223 | [Incident response](../../INCIDENT_RESPONSE.md), [secret custody/rotation](../../SECRETS_OPERATIONS.md), [repeatable drill](../../INCIDENT_DRILL.md), existing-tool reuse and this hosted rollback record delivered. No automatic reset/recovery subsystem added. |
| #223 / #342 | Consume the measured deployment boundary; retain full-service/control-plane/audit/job/period recovery and reviewed new-endpoint rebind follow-ups. No unsupported authority rewrite. |
| #222 / #321 / #320 | Named hosted fixture/provider/session/isolation acceptance remains independent; #385–#388 business-centric authorization remains the approved beta direction. |
| #294 / #337 / #338 | NAS device/archive evidence and entity-owned byte recovery remain with their owners. No retention, grant, byte-archive or NAS setup is claimed. |
| #224 / #298 | **Technical handoff accepted with listed gaps.** The requesting human explicitly selected “Accept technical handoff with listed gaps” in the implementation chat. Commercial recovery agreement, alternate-operator verification, release admission and activation remain unapproved by this work. |

The remaining alternate-operator review must establish whether they can locate
the private inventory, obtain approved access, choose the incident branch and
run linked commands without the original implementer. Request improvements
where they cannot. This technical acceptance does not attest completion of that
exercise, sign the commercial recovery agreement or authorize production
activation. Do not close #298 or describe #223/#124 as complete from this record.
