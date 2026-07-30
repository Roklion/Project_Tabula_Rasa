# Commit identification

For every Git commit created directly by Codex in this repository, append this commit trailer:

```
Made-with: Codex
```

Do not add this trailer to commits created by the user or by other tools.

# Read-only commands

Read-only commands against Git or local files are pre-authorized and do not
require asking the user for explicit approval. This includes inspecting status,
diffs, logs, tracked files, configuration, and file contents.

Read-only access to any file within the project directory is pre-authorized and
does not require asking the user for explicit approval.

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

## Business-profile isolation

- Every ledger, credential, Google Drive, backup, cache, and
  duplicate-submission operation must remain scoped to the selected business
  profile.
- Flag global or fallback state that could reuse one profile's spreadsheet,
  service account, OAuth token, folder, cached data, or submission guard for
  another profile.
- The application password grants deployment-wide access. Do not imply that it
  provides per-profile authorization.

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

- Credentials, refresh tokens, password material, private ledger data,
  receipts, and backup contents must never be logged, displayed, committed, or
  included in errors.
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
