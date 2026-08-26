# Data & backup viewport evidence

Captured 2026-08-26 from the isolated #61 worktree using the sanitized
Streamlit AppTest workflow and a text-only responsive review. The review used
fake workbook data and fake profile names only; no application secrets, Drive
tokens, receipt contents, ledger rows, or backup bytes are included here.

The page keeps the required operational order: Cloud backup, Recovery status,
Exports, Imports. Native Streamlit columns are limited to the cloud upload /
verification pair; the export and import workflows are single-column controls
that stack naturally at narrow widths. Tables remain native scrollable
components and no page-level fixed-width container was added.

| Viewport | Evidence reviewed | Result |
|---|---|---|
| 1440 × 1000 | Full section order, Drive states, recovery summary, export downloads, and all three import workflows | Pass |
| 1200 × 900 | Full section order and two-column cloud action treatment | Pass |
| 900 × 900 | Cloud actions remain discoverable; export/import controls remain in logical order | Pass |
| 390 × 844 | Single-column workflow order, readable labels, no added fixed-width page container | Pass |

The repository's AppTest harness verifies the rendered controls, configured and
unconfigured Drive states, Synology status states, read-only verification
boundary, import separation, and profile-scoped session keys. AppTest does not
emulate browser pixel dimensions, so these results are a responsive-layout
review against the native component behavior and the shared shell breakpoint
rules; a browser screenshot capture remains a manual follow-up if visual
pixel-level evidence is required.
