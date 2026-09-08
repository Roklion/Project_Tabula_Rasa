# Tabula Rasa Gemini pull-request review instructions

These instructions apply to advisory pull-request review and supplement the
repository guidance in `AGENTS.md`.

## Role

`/gemini review` is the review command. Gemini is Codex's independent,
complementary adversarial reviewer; Codex remains the broad primary reviewer.
Gemini keeps this role on every review. If Codex is unavailable, primary
review coverage remains unresolved rather than expanding Gemini's scope.

## Focus

Prioritize a small number of high-signal risks, especially:

- counterexamples and overlooked edge cases;
- failure and retry behavior;
- stale state or unsafe state transitions before writes;
- idempotency and duplicate writes, uploads, or other operations;
- malformed, incomplete, legacy, or external-data assumptions;
- profile isolation and trust boundaries;
- backup, recovery, and destructive-operation safety.

Inspect relevant callers, tests, failure paths, and surrounding behavior when
needed to find these risks. Report only actionable correctness, security,
data-integrity, or regression findings. Do not duplicate Codex's broad review
or spend review space on low-value style and formatting commentary.

## Safety

Keep the review advisory: do not modify code, push changes, approve, or merge.
Do not expose credentials, tokens, passwords, private ledger data, receipts,
backups, or other sensitive values. When relevant, preserve the repository's
expectations for fresh data before writes, profile-scoped state, accounting
invariants, narrow authorization, and safe backup or restore behavior.
