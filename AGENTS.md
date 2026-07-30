# Commit identification

For every Git commit created directly by Codex in this repository, append this
commit trailer:

```
Made-with: Codex
```

Do not add or require this trailer for commits created by the user or by other
tools, even when they contain Codex-assisted changes. Codex can enforce the
trailer only when Codex performs the commit operation.

When reviewing trailer compliance, inspect only commits that are reachable
from the pull request's actual head branch. Do not treat temporary or synthetic
commits created while applying a patch or running a review as pull-request
commits. If a cited commit is not present in the PR branch history, do not
request a trailer for it.

# Read-only commands

Read-only commands against Git or local files are pre-authorized and do not
require asking the user for explicit approval. This includes inspecting status,
diffs, logs, tracked files, configuration, and file contents.

Read-only access to any file within the project directory is pre-authorized and
does not require asking the user for explicit approval.

Read-only access through the connected GitHub integration or GitHub webpages
to information about this repository is pre-authorized and does not require
asking the user for explicit approval. This includes pull requests, issues,
comments, reviews, checks, commits, branches, and repository metadata. It does
not authorize posting comments, resolving review threads, merging, changing
settings, or performing other GitHub write actions.

# Completion checks

Running tests, linters, format checks, and other read-only validation commands
is pre-authorized and does not require asking the user for approval.

Before calling any coding task complete or ready for commit, run both of these
commands from the repository root using the project's active development
environment:

```
ruff check .
python -m pytest
```

If either command fails, resolve the failure or report it as a blocker instead
of describing the task as complete or ready for commit.

# Code Review Rules

## PR description completeness

- Before reviewing the implementation, check whether the pull-request
  description states the change's intent, expected behavior, behavior that must
  not change, and validation evidence.
- If information needed for a confident review is missing, unclear, or
  internally inconsistent, leave a concise review comment that names the
  missing decision or field and asks the author to update the PR description.
  Do not silently use the implementation as its own requirement.
- A small change may describe each field in one sentence. Do not request
  ceremony that would not improve the review.

## Review method

- Treat the PR description as a hypothesis to verify, not proof that the
  implementation is correct.
- Infer intended behavior from the PR description, relevant canonical
  documentation, unchanged callers, existing tests, and surrounding code. If
  these sources disagree, report the discrepancy.
- Review new and modified tests independently. Look for counterexamples where
  incorrect behavior would still pass the tests.
- Inspect affected callers, storage paths, failure paths, and state transitions
  beyond the changed lines.
- Report actionable correctness, security, data-integrity, or regression risks.
  Leave formatting and other deterministic mechanical checks to CI.

## Addressing review feedback

- Before applying a suggested fix, verify that each review comment is valid and
  practical against the stated requirements, canonical documentation, current
  implementation, callers, and tests.
- Do not assume that every review comment requires a code change. If feedback
  is invalid, impractical or disproportionate to implement, or based on a
  misunderstanding of the implementation, explain the evidence and tradeoffs
  instead of forcing a change.
- When feedback is ambiguous, investigate the relevant behavior and request
  clarification if the intended outcome still cannot be determined safely.
- When feedback is valid, make the smallest safe change that addresses the
  underlying issue and add or update validation where appropriate.

## Business-profile isolation

- Every ledger, Google Drive, backup, cache, duplicate-submission, and
  profile-specific credential operation must remain scoped to the selected
  business profile.
- Flag global or fallback state that could reuse one profile's spreadsheet,
  service-account credential, refresh token, folder, cached data, or submission
  guard for another profile.
- The application password and shared OAuth client are intentionally
  deployment-wide. Do not require per-profile handling for them or imply that
  the application password provides per-profile authorization.

## Ledger writes and reliability

- Edits, deletes, uniqueness checks, and reference checks must use fresh data
  before writing.
- Show success only after the Google API confirms the operation, and invalidate
  affected caches only after a confirmed write.
- Retries, duplicate suppression, imports, and uploads must not create
  duplicate ledger rows or files after uncertain network responses.
- The active ledger must remain Google Sheets-backed. Do not introduce local
  storage as an alternate source of truth.

## Secrets and authorization

- Credentials, refresh tokens, and password material must never be logged,
  displayed, committed, or included in errors.
- Private ledger data, receipts, and backup contents may be displayed only in
  authorized application views; never log, commit, include them in errors, or
  expose them elsewhere.
- Preserve the separation between the Sheets service account and the human
  Google Drive authorization.
- Preserve narrow OAuth scopes and the local administrator's reauthentication
  and loopback-only restrictions.

## Accounting behavior

- Transfers must not affect income or expenses.
- Mileage must remain separate from financial transactions.
- Preserve account classification, opening-balance sign conventions, current
  earnings, and the `Assets = Liabilities + Equity` check.

## Backup, restore, and receipts

- Restoration must target a new blank workbook and must refuse the configured
  live workbook.
- Backup version, manifest, checksum, and validation requirements must not be
  bypassed.
- Backups are recovery artifacts, not alternate live ledgers.
- Unlinking a receipt removes its ledger reference but must not delete the
  Google Drive file unless an explicitly separate destructive operation is
  introduced.

## Tests and documentation

- Behavior changes need regression coverage for both the success path and
  relevant failure paths.
- Profile-sensitive changes need an isolation test using at least two profiles.
- Update the canonical guide when externally visible behavior, configuration,
  recovery procedures, or security boundaries change.
