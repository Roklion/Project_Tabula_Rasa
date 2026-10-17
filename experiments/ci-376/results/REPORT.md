# Controlled CI evidence for issue #376

Fixed source: `84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db`. Three paired hosted attempts; reconstructed baseline and partitioned layout share current source, dependencies and assertions.

| Pair | Baseline elapsed s | Partitioned elapsed s | Baseline runner s | Partitioned runner s | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| [1](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38992167347) | 1006 | 583 | 1537 | 2098 | failure |
| [2](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39000043429) | 1494 | 728 | 2163 | 2260 | success |
| [3](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39002104472) | 1077 | 696 | 1831 | 2440 | success |

Occupied runner seconds are unweighted job intervals, not billed usage. Queue/start delays, OS-specific runner seconds, step costs, runtime/cache observations, and individual JUnit report counts are preserved in the adjacent JSON files. Experiment aggregate overhead is excluded from both layouts.

Median elapsed seconds: baseline 1077 (range 1006–1494), partitioned 696 (range 583–728). Paired changes: -42.0%, -51.3%, -35.4%.
Median occupied runner seconds: baseline 1831 (range 1537–2163), partitioned 2260 (range 2098–2440). Paired changes: +36.5%, +4.5%, +33.3%.

## Coverage and diagnostic audit

All 27 component checkouts verified the fixed source SHA in their runtime logs. All three baseline overlay proofs match the unchanged UTF-8 test bodies from that Git revision. Source, dependencies, frontend build inputs, four UI projects, 13 native test modules, PostgreSQL service, commercial runtime image and synthetic NAS recovery smoke are the same in both layouts. The workflow revision is recorded separately from the checked-out source.

Each pair retained these JUnit inventories, with no missing report or unexecuted native phase:

| Report family | Baseline | Partitioned | Skips per layout |
| --- | ---: | ---: | ---: |
| Python suite | 2,976 | 2,976 | 141 |
| Windows tooling | 10 | 10 | 0 |
| Native browser | 131 | 131 | 0 |
| UI plus HTTP/Git contracts | 160 | 70 + 70 + 5 | 0 |

The 141 Python skips are identical supported prerequisite/platform selections in both layouts; dedicated native coverage ran without skips. The deliberate 15-execution reduction is five identical browser-independent contracts running once instead of four times, not removed assertions or page/browser permutations. Case counts alone are not proof of equivalence: the source checkout, native command inventory and unchanged contract/page body hashes supply that association.

Observed complete-layout outcomes are **baseline 3/3, partitioned 2/3**. There were **zero reruns, retries, cancellations or timeout terminations**. Sample 1 retained one failed desktop journal-preview case (69/70 passed in UI shard 1); all other component checks passed. The fail-closed experiment aggregate failed. Samples 2 and 3 passed without changing source or assertions. This small experiment does not establish improved reliability.

The failed case's trace contains HTTP 504 `Outdated Optimize Dep` responses for four optimized JavaScript dependencies; the expected preview could not render. Shared optimizer-cache lifecycle contention is plausible but not exclusively proven. [Failure evidence](../sample-1-failure.md) and [follow-up #384](https://github.com/Roklion/Project_Tabula_Rasa/issues/384) preserve the diagnostic and required remediation. Later unchanged-source passes do not establish a fix. The defect causes false-negative CI results; no gate or safety coverage was bypassed. Its correction requires a separate scoped change and current-candidate validation.

The partitioned job/step and retained trace identified the failing UI surface directly, while Python, native and contract diagnostics completed independently. The combined baseline still reports per-test detail, but a failed early UI step would prevent later native steps in that job; no such truncation occurred in these three samples.

## Interpretation and limits

The deliberate treatment is execution ownership: five unchanged HTTP/Git contracts execute twenty times in the reconstructed baseline and five times in the partitioned layout; all 140 UI/browser/device cases and the same native inventory remain. Current security, onboarding and NAS recovery coverage is included in both. Baseline reconstruction uses the prior 30-minute combined budget; production bounded partition budgets are unchanged.

Three pairs describe observed outcomes, not long-term reliability or causal isolation from runner/cache variability. Keep reported failures, cancellations and reruns. No billed-cost claim, production coverage reduction or broader visual scheduling follows from this experiment.

## Phase costs and bounded budgets

All values below are measured job/step wall seconds, including installation/build/artifact work rather than only testcase sums. Individual step costs, OS totals, top-20 pytest setup/call/teardown duration observations and JUnit case-time distributions remain in the adjacent JSON. Top-20 duration observations are not complete fixture-time totals.

| Pair | Baseline combined job | Baseline UI step | Baseline native step | Partitioned UI1/UI2 steps | Partitioned native job/step |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1006 | 445 | 435 | 284/279 | 583/450 |
| 2 | 1493 | 706 | 602 | 368/336 | 728/607 |
| 3 | 1077 | 480 | 453 | 366/329 | 695/577 |

The UI step imbalance was 5, 32 and 37 seconds (about 2%, 10% and 11% of the faster shard). Both shards retain 70 cases; different runtimes show that case counts alone do not perfectly balance work. No further split is justified by this bounded sample.

| Pair | Baseline / partitioned pip install totals | Baseline / partitioned browser install totals | Baseline / partitioned application build totals | Baseline / partitioned artifact-upload totals |
| --- | ---: | ---: | ---: | ---: |
| 1 | 87/134 | 43/189 | 5/11 | 6/9 |
| 2 | 115/139 | 58/180 | 7/13 | 8/12 |
| 3 | 117/144 | 46/158 | 5/15 | 6/11 |

More runners duplicate dependency/browser setup and the application build. The native Python browser installation largely benefits from the preceding Node installation in the combined baseline; separate jobs cannot share that runner-local state. The observed occupied-cost increases are therefore retained as a tradeoff, not described as a cost saving. Artifact upload and runtime-image/NAS build step costs remain individually available in the JSON.

Keep the existing bounded budgets: Python 30 minutes, Windows/frontend 15 minutes, UI/native 20 minutes, production aggregate 5 minutes. Maximum observed partitioned job durations were Python 686 s, Windows 119 s, frontend 113 s, UI 457 s and native 728 s; all completed within those bounds. Maximum combined baseline job time was 1,493 s against its reconstructed 1,800 s budget. These samples support retaining headroom, not increasing timeouts or adding retries. The observed failure was an optimizer response error rather than a job timeout. Do not move broader visual permutations to scheduled-only execution: this evidence supplies no coverage/fallback justification for doing so.

## Environment, variability and retention

All pairs used Ubuntu 24.04 image `20261012.334.1` and Windows 2025/VS2026 image `20261007.264.1`. Configured Python was 3.12.15 on Linux and 3.12.10 on Windows; Node 24.21.0/npm 11.19.0 were identical across applicable jobs. The earlier provenance step's bootstrap Python is recorded separately and is not the configured test runtime. Setup pip/npm caches reported hits; their public keys/observations are retained. Browser-engine download/dependency installation and Docker build costs still varied. Component starts occurred 2–4 seconds after workflow creation; these start delays are excluded from component elapsed measurements and recorded separately, without pretending to isolate GitHub queue time from scheduling overhead.

The same full Python test step ranged from 373–556 seconds in the baseline and 380–615 seconds in the partitioned layout despite identical inputs. The baseline UI step ranged 445–706 seconds. These differences demonstrate substantial hosted variability and prevent attributing every paired delta solely to partitioning. Layouts ran concurrently within each pair on the same hosted runner class; three pairs were sequential, without randomized order or resource-contention isolation.

This report records shorter observed elapsed times in all three pairs and higher occupied runner time in all three. It does not establish a reliable production speedup, improved pass rate, statistical confidence, billed-cost reduction or a guarantee for future runner images. Raw logs, traces and JUnit remain hosted artifacts; only sanitized metadata, aggregate counts/times and body-hash proofs are committed. No production data, credentials or live NAS endpoints were used. Main CI and its authoritative full-suite gate remain unchanged.

The original six #376 acceptance criteria now have measurement evidence. The independently tracked preview reliability defect remains open in #384 and is not claimed fixed by completing the measurement ticket. EPIC #223, initiative #124, #377 retirement and #339 resource cleanup retain their separate unfinished scope; this creates no new release gate.
