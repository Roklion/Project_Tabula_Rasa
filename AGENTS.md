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
