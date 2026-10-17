# Sample 1: observed UI failure

Run: https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38992167347

Failed job: https://github.com/Roklion/Project_Tabula_Rasa/actions/runs/38992167347/job/117276714385

Workflow head: `30d768c7abdfab3053f1247da48c64d4a1adbb74`; fixed test/application source: `84f427e1ec0f9bb38baf63b7b4c6a6b0bb98f6db`; attempt 1, no retry.

Partitioned UI shard 1 finished with 69 passed and one failed. The desktop journal preview case could not find the Journals region within the existing five-second assertion timeout. Its retained browser trace records four HTTP 504 `Outdated Optimize Dep` responses for optimized JavaScript dependencies. This prevented the expected preview from rendering. The same case subsequently passed on the mobile project; shard 2 passed.

This is a real observed failed attempt, not evidence that the assertions should be weakened or a timeout increased. The base dev server and in-process preview servers inherit Vite's default dependency cache directory, and two Playwright workers can run concurrently. Shared optimizer cache contention is a plausible cause, but the trace alone does not establish exclusive causality; a focused startup/cache reproduction is needed before choosing a fix. No source change or blind rerun was made. Preserve this observation in the final reliability comparison even if later samples pass.

The completed paired run passed all three baseline components and five of six partitioned components. The fail-closed experiment aggregate correctly failed. Include this completed failure in the three-pair comparison; do not discard it or claim three successful partitioned attempts. Raw synthetic browser artifacts remain hosted; this note retains only the diagnostic facts.
