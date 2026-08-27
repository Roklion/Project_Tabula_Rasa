# Data & backup pre-change no-function-loss inventory

Captured before the #61 page extraction from `tabula_rasa/app.py` at the
starting commit `00b9949` on 2026-08-25. This inventory is the preservation
checklist for the extraction and regrouping.

## Page entry and profile scope

- The authenticated `Data & backup` route remains available only when a
  selected business profile and live Google Sheets workbook are available.
- Every Drive listing, upload, verification, receipt preparation, export,
  import, duplicate guard, and cache/session key is scoped to the selected
  profile and configuration revision.
- The page header identifies the private Google Sheets workbook as the live
  record source.

## Cloud backup

- Unconfigured Google Drive state explains that Account settings must connect
  Drive and select a backup folder.
- Configured state lists the profile-scoped backup destination and up to 30
  app-managed backups; it reports the latest name/time or the no-backup warning.
- **Upload fresh backup now** prepares a fresh receipt inventory, creates and
  validates a complete ZIP, computes the canonical filename/hash, uploads with
  profile/folder/retention/idempotency parameters, reports safe errors, and
  reruns only after success.
- **Verify latest cloud backup** is Drive-only: it downloads and validates the
  latest selected file, checks the stored hash when present, reports success or
  failure, and stops execution so it cannot read live Sheets, prepare exports,
  create a backup, restore, or mutate state in the same action.

## Recovery status

- Missing local Synology metadata states that hosted projections intentionally
  omit NAS settings and points administrators to loopback-only Account settings
  and DSM.
- Present but invalid Synology metadata reports validation errors and the
  Account settings repair path.
- Valid recovery metadata preserves warnings for missing Drive backup folder,
  receipt folder, or storage root.
- The status displays the canonical profile-root remote source, expected
  `Receipts` and `Ledger Backups` children, Cloud Sync direction, destination
  deletion policy, NAS destination, schedule, and retention.
- The status explicitly says Tabula Rasa neither configures nor observes DSM;
  transfer health and retries must be confirmed in DSM.

## Exports

- **Prepare downloadable exports** reads fresh accounts, categories,
  transactions, and mileage, prepares transaction and mileage CSV bytes, and
  attempts a fresh receipt-complete validated workbook ZIP.
- Prepared artifacts are stored under a key containing selected profile,
  profile/configuration revision, and confirmed `workbook_data_revision`.
- Confirmed transaction and receipt-reference writes advance
  `workbook_data_revision`, so a prepared export cannot be presented as current
  after the live ledger changes.
- Complete-backup failure is reported while transaction and mileage CSV
  downloads remain available.
- Existing prepared snapshots are surfaced only under their current key and
  include their preparation timestamp.
- Download controls remain available for transactions CSV, mileage CSV, and a
  complete workbook ZIP when present. Page-specific download filenames use
  `tabula-rasa`; CSV schemas and the historical cloud-backup filename contract
  remain unchanged.

## Imports

- Tabula Rasa CSV has its own profile-scoped uploader key, required-column
  diagnostics, preview, and explicit **Import rows** action.
- QuickBooks transactions has its own uploader key, CSV/XLSX/ZIP conversion,
  conversion diagnostics, required-column diagnostics, auto-create preview,
  ready/duplicate/income/expense/transfer summaries, row preview, and explicit
  **Import validated rows** action.
- QuickBooks mileage has its own uploader/session scope, required-column
  diagnostics, ready/duplicate/personal/unreviewed summaries and row details,
  preview, and explicit **Import validated mileage** action.
- Parsing, conversion, preview, diagnostics, duplicate summaries, and
  auto-create planning are read-only. All writes remain behind the explicit
  import buttons, existing duplicate guards, confirmed-write revision bump,
  success notice, rerun, and safe failure handling.
- Existing schemas, importer APIs, error messages, file limits, uploader keys,
  and profile isolation are preserved.

## Safety and boundaries

- No in-app restore, scheduler, NAS-health monitor, or alternate-ledger control
  is part of this page.
- Google Sheets remains the live ledger and receipt unlinking remains separate
  from backup/export behavior.
- Import and backup failures do not claim success and do not silently create
  rows, files, or a live-ledger mutation.

## Source anchors

- Current implementation: `tabula_rasa/app.py`, former route block lines 494-1020.
- Design authority: `design.md` sections 22-26, 27-30, 31.8, 32.8-32.9, 33-36.
- Relevant issue context: #51, #52, #53, #61, and #62.
