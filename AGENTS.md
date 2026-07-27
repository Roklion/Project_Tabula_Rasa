# Commit identification

For every Git commit created directly by Codex in this repository, append this commit trailer:

```
Made-with: Codex
```

Do not add this trailer to commits created by the user or by other tools.

# Completion checks

Before calling any coding task complete or ready for commit, run both of these
commands from the repository root using the project's active development
environment:

```
ruff check .
python -m pytest
```

If either command fails, resolve the failure or report it as a blocker instead
of describing the task as complete or ready for commit.
