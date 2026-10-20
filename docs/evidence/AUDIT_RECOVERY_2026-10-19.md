# Audit recovery evidence — 2026-10-19

Scope: #335's audit-policy/#346 and recovery/#342 requirements only. No production
database, NAS generation, provider configuration or retention setting was changed.
The owner approved the interim no-prune/no-rewrite/operator-only/no-customer-export
contract in the implementation chat; statutory/legal/commercial approval remains
unresolved. Policy delivery is [PR #402](https://github.com/Roklion/Project_Tabula_Rasa/pull/402).

## Environment and reproducibility

Windows Python 3.12 repository development environment; new local container
`tabula-335-audit-tests`, PostgreSQL 18.6, trust authentication for disposable
synthetic fixtures only, port bound to `127.0.0.1:55442`. Each pytest fixture
creates its own random database and removes only its own fixture. The archive
test creates a separate new empty random target and uses real PostgreSQL clients.
There are no application URL fallbacks, live financial records or provider grants.

The exact affected-suite command is in
[Audit recovery](../AUDIT_RECOVERY.md#reproducible-synthetic-checks).
Set the test database URL privately to the synthetic service and set
`TABULA_RASA_TEST_PG_CONTAINER=tabula-335-audit-tests` before that command.
Local test output is disposable validation output; do not commit JUnit payloads.
The current PR's CI preserves JUnit as its normal private Actions artifact.

Pre-publication affected validation: **264 passed in 111.34 seconds**, no skips/failures.
Repository `ruff check --no-cache .`, compilation and `git diff --check` passed.
The policy PR separately ran 45 native audit/period/authorization checks and 394
support-control/CLI/authorization checks. Review remediation also exercises a
non-owner restored inspector under RLS, equivalent explicit/default sequence
ACLs, weakened source policies/capture triggers and reversed PITR controls.
The final focused recovery/CLI/CI-policy remediation run passed **70 tests in
34.86 seconds**, with no skips/failures; repository Ruff and diff checks passed.
The initial publication exposed an invalid job-level service context in CI;
moving that binding to the pytest step fixed workflow evaluation. The failed
initial run is not passing evidence for the corrected head.

The owner subsequently paused **all real provider/NAS drill work** for another
agent and requested completion of implementation and the PR feedback loop only.
No Neon authentication, cloud restore or retained NAS operation was performed.
The real-drill rows below are therefore also **user-paused**, with their original
prerequisites retained for handoff; they are not passing evidence.

Final source-function remediation: **106 affected audit/recovery/migration/CLI/
CI-policy tests passed in 51.20 seconds**, with no skips/failures; Ruff/diff passed.
The source oracle rejects changed audit function bodies and search paths by
comparing the five required functions against the frozen migration definitions,
including a same-name weakened immutability function with an older event removed.

## Test and evidence matrix

| Check | Execution/result | Evidence and limit |
| --- | --- | --- |
| Schema/tables/functions/constraints/indexes/triggers/RLS/policies/sequences/ACLs | Executed: PASS | Native snapshot clones and real dump/restore compare complete audit inventory; deliberately disabled trigger, dropped policy/PK, changed minimizer and reset sequence are rejected. |
| Counts, stable event UUIDs, all retained history fields and ordering | Executed: PASS | Both entities match source event rows after restore; deleting an older event is rejected even though latest-state integrity still passes. Exact numeric JSON comparison is preserved. |
| Ledger/event consistency; actor/entity isolation; #336 periods | Executed: PASS | Overlapping local IDs, operator attribution, closed-period rejection, named authorization and two-entity audits; changed ledger/actor/entity snapshots rejected. |
| Before/after atomic ledger/event commit; later-state exclusion | Executed: PASS | Isolated committed snapshot clones on either side of the mutation; earlier point accepts its oracle and rejects the later one. This is not WAL/provider PITR evidence. |
| Commit with lost response; duplicate retry | Executed: PASS | Commit response is lost after success; restored state contains one event set; stable-ID retry conflicts without duplicating history. |
| Partial imports and independent worker replay | Executed: PASS | Failed chunk remains unconfirmed, earlier chunk retained, replay after restore adds no event; beta has no alpha chunk evidence. |
| Activation watermark, baseline and pre-audit history | Executed: PASS | Pre-activation clone explicitly reports unavailable; immutable original baseline/watermark persist across restore and forward migration. No invented actors/events. |
| Schema compatibility and archived history | Executed: PASS | Archived 0013 is verified before forward upgrade to current 0015; events/boundary unchanged; original-revision comparison rejects an already upgraded target. |
| Real local logical archive recovery | Executed: PASS | PostgreSQL 18.6 `pg_dump -Fc` and `pg_restore --single-transaction --exit-on-error` into a new database; two-entity audit manifests/identities match. No provider or NAS provenance claimed. |
| Existing NAS client TLS/encryption/restore/failure harness | Executed: PASS | Reviewed NAS Dockerfile built; `nas_backup_smoke.py` returned `status=passed`, `scope=synthetic_client_roundtrip`, TLS true, two entities/overlapping IDs. Client fixture is not canonical audit-history evidence. |
| Real managed snapshot with audit verification | **BLOCKED / not executed** | Need approved source and new isolated provider target, frozen independent audit oracles, retained actual snapshot/lineage and secret injection. #259's older drill predates audit. |
| Real requested-point managed PITR with audit verification | **BLOCKED / not executed** | Need current recoverable point/LSN, before/later oracles and independently recorded included/excluded commits, spare isolated target and provider operation evidence. |
| Retained physical NAS generation with audit verification | **BLOCKED / not executed** | #294's completed real restore is supporting lineage/schema evidence, but did not capture/compare this audit oracle. Owner must select an actual correctly bound generation and private evidence, decrypt/restore into approved isolation and run the audit checks. |

Required GitHub `Full test suite` and current-head reviews remain independent
publication gates. A local passing matrix is not a claim that CI or actual
managed/NAS audit-aware acceptance passed.

## Existing real evidence and exact remaining blockers

- [#259 supplementary NAS evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/259#issuecomment-6273560371)
  identifies a genuine retained UAT generation and isolated Neon restore at
  `0014_document_locations`. It explicitly distinguishes later source changes
  from capture-instant comparisons and records provider ACL exceptions. No
  post-hoc current-source audit manifest can be substituted for a frozen oracle.
- [#294 technical closure](https://github.com/Roklion/Project_Tabula_Rasa/issues/294#issuecomment-6274013043)
  establishes owner-operated NAS backup/recovery evidence, not these new
  audit-aware comparisons or commercial RPO/RTO/alternate-operator acceptance.
- **Owner/operator action:** designate exact safe source/isolated targets, current
  managed recovery points and correctly bound NAS generation; inject restricted
  credentials off-chat and retain private oracles/archives/lineage. Follow the
  [runbook](../AUDIT_RECOVERY.md#authorized-operator-procedure), record every
  entity and history gap and link sanitized results. No such bindings or
  credentials were supplied to this implementation run. Do not use existing
  retained UAT/production as a target or alter a NAS generation.
- **Owner/legal action:** resolve statutory retention/hold/privacy obligations
  and record the required policy acceptance. Interim owner approval does not
  claim legal review. No automatic destructive workflow is needed for this task.
- **Engineering/publication:** current-head CI/review, human review/merge and
  remediation of any validated findings still apply. This record does not
  authorize merging a PR or changing provider/NAS settings.

**#335 remains open.** Its actual snapshot/PITR/NAS audit verification and required
policy acceptance are not established by synthetic checks or an approved interim
operator contract alone. Leave its mixed policy/recovery checkboxes unchecked;
link the delivered portions and exact evidence instead of overstating completion.

Intentionally deferred #342 scope: broader stage readiness, operational alerting,
full-service/bytes recovery, commercial objectives and handoff. Deferred #346
scope: account/org deletion, customer-facing closure/export UI, general cleanup
and complete commercial lifecycle/privacy delivery. #341/#345, EPIC #224 and
unrelated commercialization are not added dependencies for #335.
