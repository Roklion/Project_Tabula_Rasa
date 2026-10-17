# Controlled CI comparison for #376

Fixed application, test and dependency source: `84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db` (merged PR #379).

This branch is an experiment, not a production workflow change. Its push-only workflow checks out that fixed source in every component. Main CI and its required aggregate remain unchanged. The generator copies the production jobs from the fixed source; rerunning it requires this branch to retain that source's `ci.yml`.

Each paired sample runs the six partitioned component runners and three reconstructed baseline runners on GitHub-hosted Ubuntu/Windows. Both include the same frontend, Python/PostgreSQL, Windows, native inventory, commercial image and synthetic NAS recovery contracts. The baseline combines frontend/UI/native work within the prior 30-minute combined budget and executes the unchanged five HTTP/Git test bodies in all four UI projects. An artifact records test-body hashes. The baseline has 160 Playwright executions; the partitioned layout has 140 UI executions plus five run-once contracts. Assertions and browser/page permutations are preserved. This is a controlled reconstruction, not a rerun of the older security revision.

Run three sequential paired samples without automatic retries. Change only `SAMPLE` in `generate.py`, regenerate, and push after the preceding pair completes. Record every attempt, including failure/cancellation, rather than selecting successful results. Diagnose failures before proceeding; do not increase timeouts or add retries blindly.

Collect attempt-specific job/step timestamps, source/workflow identities, runner images/runtime versions, cache-hit evidence, JUnit counts/failures/skips and test times, and overlay proof. Report elapsed critical paths, queue delay separately, occupied runner seconds by OS (not billed usage), phase costs, shard imbalance, and observed pass rate. Setup/build/artifact overhead remains part of the comparison. Fixtures remain included in test-step costs; pytest slow-duration logs identify dominant setup/call/teardown costs. Three pairs bound this experiment but do not establish long-term reliability or causality for runner variability. No production data, secrets, real NAS endpoints or paid resources are configured.

Keep required per-PR coverage and existing budgets unless the observations establish a concrete adjustment. Broader visual scheduling requires its own explicit coverage policy. #377 and #339 retain their separate ownership; this adds no initiative release gate.
