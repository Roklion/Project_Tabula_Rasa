# Visual-preview optimizer cache diagnosis (#384)

## Original failure retained

The [first controlled sample](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38992167347),
[UI shard 1](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38992167347/job/117276714385),
failed the desktop journal preview: 69/70 cases passed and the retained trace
recorded four HTTP 504 `Outdated Optimize Dep` responses. Its fixed source was
`84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db`. The original failed attempt and
[three-pair measurement report](https://github.com/Roklion/Project_Tabula_Rasa/blob/fbbfbfb86ededbde30cbda2835399d3e5881c311/experiments/ci-376/results/REPORT.md)
remain evidence for #376. Later unchanged-source passes are not fix validation.
This diagnosis does not alter those measurement pairs or their outcomes.

## Focused diagnosis

On 2026-10-18, a clean worktree based on `ea8c2de39a171a4010c821edc8648dbf241cd3dd`
used Windows, Node 24.19.0 and the pinned Vite 8.3.3 / Playwright 1.62.0 packages.
The normal configuration and visual-review configuration both resolved their
optimizer cache to `web/node_modules/.vite`. Their plugin lists differ because
the preview adds `synthetic-visual-review`.

Inspection of the installed Vite implementation establishes this lifecycle:

1. `getConfigHash` includes plugin names. The two configurations therefore have
   different optimizer configuration hashes.
2. `loadCachedDepOptimizationMetadata` removes the dependency cache when that
   hash changes. `runOptimizeDeps` later replaces it with newly bundled files.
3. `optimizedDepsPlugin` maps a missing versioned dependency file to
   `ERR_OUTDATED_OPTIMIZED_DEP`; Vite's transform middleware returns HTTP 504
   with status text `Outdated Optimize Dep`.

A synthetic diagnostic warmed a preview's entry module, left its dependency
request pending, and initialized the normal server's optimizer. Before normal
optimization committed replacement files, the preview's existing
`react-dom/client` URL returned **504 Outdated Optimize Dep**. The normal server
reported **Re-optimizing dependencies because vite config has changed**. The
observed configuration hashes were `d8ce114d` (preview) and `763a1432` (normal).
These hashes are local observations, not portable expected values.

The retained regression is `web/contracts/visual-preview-cache.spec.ts`. It
keeps two preview lifetimes open, warms their entries, initializes the normal
optimizer and requests their versioned dependencies. To expose the browser's
pending-request boundary deterministically, it disables speculative dependency
pre-transforms in the test and invokes optimizer initialization before listen.
It does not force optimization, delete caches itself, mock responses, sleep,
retry or change timeouts. Against the original helper it fails at the HTTP
assertion with **expected 200, received 504**; with isolated caches it passes.
It also verifies that closing one preview removes its cache without removing
the other preview's cache, and that closing both leaves neither cache behind.

## Correction and validation boundary

`startVisualPreview` remains the shared owner for browser and HTTP/Git preview
startup. Each invocation now creates a unique optimizer cache under
`web/node_modules/.vite-visual-*`, passes it through Vite's `cacheDir`, and removes
it after close or failed startup. Per-server ownership covers concurrent workers
and overlapping previews within one worker. Normal dev/build configuration,
synthetic routes, read-only API restrictions and existing browser assertions
remain unchanged. No CI partition, aggregate requirement, retry or timeout changes.

This establishes and prevents a concrete shared-cache invalidation mechanism.
The historical trace alone cannot prove the precise server scheduling that
caused its four failed requests, or exclude every other cause of Vite 504s.
Local Windows validation is separate from hosted Linux current-candidate CI and
independent review; those remain required before issue acceptance or merge
readiness. No hosted result is claimed by this local implementation.

## Initial local validation (head `191a73a`)

From the repository root on 2026-10-18, with the pinned dependencies:

| Check | Result |
| --- | --- |
| Original helper with the new dependency lifecycle regression | Expected failure: HTTP 504 `Outdated Optimize Dep` |
| `npm --prefix web run test:contracts` | 7 passed, including dependency isolation and failed-startup cache cleanup |
| `CI=1 npm --prefix web run test:browser -- --shard=1/2` | 70 passed; desktop and mobile; two workers |
| `CI=1 npm --prefix web run test:browser -- --shard=2/2` | 70 passed; Firefox and WebKit; two workers |
| `npm --prefix web test` | 106 passed in 24 files |
| `npm --prefix web run build` | Passed; existing bundle-size advisory |
| `npm --prefix web run typecheck` and `npm --prefix web run lint` | Passed after final test changes |
| `python -m pytest tests/tooling/test_ci_workflow.py -q` | 36 passed using the existing development environment |
| `git diff --check` and branch diff against `origin/main` | Passed; four scoped files |

Both browser shards completed without failures, skips or retries. All eight
existing preview cases (two tests across four projects) passed with their
unchanged assertions. The first shard started after a fresh dependency install;
every preview cache is newly allocated regardless of the main dev server's
cache state. Temporary preview caches were absent after teardown. The original
checkout stayed clean on `main`. Hosted current-candidate CI and independent
review have not been run for this local-only branch.


## First hosted run and teardown correction

The first ready-state [CI run 39186870676](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39186870676)
on head `191a73a` passed both UI shards but failed the
[frontend contract job](https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/39186870676/job/117851368910)
during HTTP-only preview teardown. It reported `ENOTEMPTY` while removing a
`deps_temp_*` directory. That failure is retained; Windows success above does
not establish Linux cleanup correctness.

A disposable Linux synthetic browser-test container (Node 24.22.0, pinned npm
dependencies, Git installed for the existing Git contracts) reproduced the same
teardown error in two of three diagnostic contract-suite repetitions on the
original helper. An initial container attempt lacked Git and could not evaluate
those Git contracts; it is not counted as teardown validation.

Pinned Vite's optimizer can hand a scan's result to a background build while
shutdown is in progress. Its native close promise alone does not establish that
all those output writes have stopped. Separately, `restartServer` replaces the
server's methods with `Object.assign(server, newServer)`, so patching `close`
does not preserve fixture cleanup across a restart (Codex review finding).

The fixture now returns its own `close()` function; both browser/HTTP fixture
owners and the cache contracts call that function. It waits for the client's
request crawl, dependency scan and discovered-dependency processing promises,
then calls the current server's native close method before removing the cache.
This keeps lifetime ownership outside Vite's replaceable methods. No sleeps,
retry-on-error cleanup, timeout changes or suppressed failures were added.
The contract now covers a real Vite restart and adds an HTTP-only cold-close
case, with explicit absence checks after fixture teardown.

After correction, all **24 Linux contract executions** (eight contracts, three
bounded diagnostic repetitions) passed. On Windows, **eight contracts** and all
**eight affected browser cases** passed with two workers and all four projects;
TypeScript and ESLint passed. These affected checks validate the remediation;
fresh hosted CI on its new head remains required. Earlier 140-case browser and
106-test unit results remain associated with the initial head, not relabeled
as new-head full-suite evidence. No claim that issue acceptance is complete.
