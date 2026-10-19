# Final Sheets source contract

## Decision and ownership

Issue [#261](https://github.com/Roklion/Project_Tabula_Rasa/issues/261), under
[PostgreSQL EPIC #220](https://github.com/Roklion/Project_Tabula_Rasa/issues/220)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124),
freezes the **final supported Google Sheets workbook and backup archive at
format 13**. This guide is the canonical source boundary for continued Sheets
operation, Sheets recovery, and migration to PostgreSQL. A later change to
these fields, archive version, or relationships must explicitly revise this
decision and the dependent migration contracts; do not silently extend format 13.

All earlier ledger/workbook and backup formats are unsupported. Historical
ledger converters, schema catalogs, aliases, and conversion-only tests have
been retired. This supersedes the ongoing historical-conversion commitments
in closed #162/#163 without changing their completion history.

Retirement does not delete or rewrite existing accounting records, ledgers,
receipt files, backups, audit history, or the preserved pre-cutover Sheets
source. Keep unsupported files intact and private; supported recovery requires
a validated format-13 archive and a new blank workbook. Backup-file retention
is an operational policy owned by #223, separate from format support.

## Workbook identity and exact headers

A live workbook has no separate numeric version cell: the required worksheet
names and complete header sets identify its format. The executable contract is
[`schema.py`](../tabula_rasa/storage/google_sheets/schema.py):
`WORKBOOK_FORMAT_VERSION = BACKUP_FORMAT_VERSION = 13`, `WORKSHEET_HEADERS`,
`validate_workbook_headers`, and `validate_worksheet_headers`. Runtime and the
archive parser share these header validators. Extraction must consume them
rather than duplicating a historical schema catalog.

Every worksheet below is required, including header-only tables with no
records. Header names are case-sensitive after trimming surrounding whitespace;
blank, duplicate, missing, or additional ledger headers fail. Columns may be
reordered because supported reads and writes use names. The table lists the
canonical order used for bootstrap. Unmanaged worksheets such as Sheet1 may
remain; they are outside the ledger/source contract and are not exported.

| Worksheet | Exact headers in canonical bootstrap order |
| --- | --- |
| Accounts | `id`, `name`, `type`, `classification`, `opening_balance`, `active`, `created_at`, `parent_id` |
| Categories | `id`, `name`, `kind`, `parent_id` |
| Payees | `id`, `name`, `active`, `created_at` |
| Transactions | `id`, `txn_date`, `kind`, `amount`, `account_id`, `to_account_id`, `category_id`, `payee_id`, `description`, `reference`, `receipt_references`, `created_at`, `source_type`, `source_id`, `tag_ids`, `recurring_schedule_id`, `recurring_scheduled_date`, `recurring_source_kind`, `recurring_occurrence_type` |
| JournalEntries | `id`, `txn_date`, `description`, `created_at`, `updated_at` |
| JournalPostings | `id`, `parent_entry_id`, `position`, `target_type`, `target_id`, `side`, `amount`, `payee_id`, `description` |
| MixedUseExpenses | `id`, `txn_date`, `kind`, `total_expense`, `business_use_percentage`, `allocated_amount`, `account_id`, `category_id`, `payee_id`, `description`, `reference`, `receipt_references`, `allocation_rationale`, `linked_transaction_id`, `tag_ids`, `recurring_schedule_id`, `recurring_scheduled_date`, `recurring_source_kind`, `recurring_occurrence_type`, `created_at` |
| RecurringSchedules | `id`, `name`, `kind`, `source_kind`, `recurrence_unit`, `recurrence_interval`, `anchor_date`, `start_date`, `end_date`, `status`, `amount`, `total_expense`, `business_use_percentage`, `account_id`, `category_id`, `payee_id`, `description`, `reference`, `allocation_rationale`, `tag_ids`, `created_at`, `updated_at`, `attention_code`, `attention_at` |
| Assets | `id`, `name`, `asset_type`, `notes`, `acquisition_date`, `depreciation_start_date`, `cost_basis`, `salvage_value`, `useful_life_quarters`, `depreciation_method`, `depreciation_expense_account_id`, `accumulated_depreciation_account_id`, `payee_id`, `reference`, `tag_ids`, `source_transaction_id`, `retired_date`, `status`, `schedule_overrides`, `created_at`, `updated_at` |
| Tags | `id`, `name`, `active`, `created_at` |
| Mileage | `id`, `trip_date`, `miles`, `vehicle`, `start_location`, `destination`, `business_purpose`, `notes`, `created_at`, `tag_ids` |

Schema preflight is read-only for populated workbooks. Unsupported schemas
fail before source-ledger or migration-target writes, without automatic
conversion or referral to retired commands. Unknown non-empty data beyond
ledger headers must not be silently discarded. `from_secrets_read_only` is the
supported non-bootstrapping storage entry point for operator reads; extraction
must not use startup initialization as its preflight.

Startup may initialize a genuinely empty workbook or resume an interrupted
bootstrap containing only canonical current headers and no records. It
creates required tabs/headers, preserving empty unmanaged tabs. Defaults are
seeded through the existing setup service. Header-only historical layouts
are incompatible, not new empty workbooks. Restore initialization preflights
all target tabs before creating any sheets and refuses populated or
incompatible targets, including populated unmanaged tabs.

## Archive and manifest

The ZIP contains **exactly** one `<Worksheet>.csv` for each of the eleven
worksheets above, `receipts.json`, and `manifest.json`. Missing, additional,
or duplicate ZIP members fail. CSV and JSON use UTF-8; exports use CSV quoting
and LF line endings. Short rows are padded with empty strings, blank rows are
ignored, and over-wide CSV rows fail. Total uncompressed size must not exceed
100 MiB. No extraction to disk is needed for validation.

`manifest.json` is an object with these required fields:

| Field | Contract |
| --- | --- |
| `format_version` | JSON integer exactly `13`; other versions and non-integer values fail before initialization or writes. |
| `backup_time` | ISO timestamp with UTC offset, normally `YYYY-MM-DDTHH:MM:SSZ`. |
| `workbook_title` | Non-empty source workbook title string; metadata, not a ledger identity or authorization boundary. |
| `worksheet_headers` | Object keyed by exactly the eleven worksheet names, each value matching its CSV's normalized header list and order. |
| `row_counts` | Object keyed by exactly the eleven worksheet names, with integer counts of non-blank data records. |
| `sha256` | Object keyed by exactly the eleven CSV filenames and `receipts.json`, matching the SHA-256 of each complete data file's bytes. |

Additional top-level manifest metadata does not change the source schema and
is not an alternate version declaration. A format-13 archive already produced
by an earlier tool remains supported if it satisfies this contract. Manifest
checksums do not include `manifest.json` itself. Checksums detect corruption;
they do not authenticate the archive or replace private artifact handling.

Every record has a non-empty unique `id` within its worksheet. Existing domain
validators check hierarchy, managed references, journal balance, source-owned
relationships, and receipt integrity. Runtime uses the appropriate domain
checks at reads and mutation boundaries; schema preflight alone is not proof
of valid accounting data. Archive validation completes before restore writes.
Restore refuses every configured profile's live workbook and requires a new
blank target. A selected profile must match the archive's receipt inventory
before opening or initializing that target. All supported tables and existing
IDs/history are restored without generating replacement accounting entries.
See [Backup and recovery](BACKUP_RECOVERY.md) for operator commands.

## Values, identities, and relationships

The frozen source represents these domain meanings. Canonical PostgreSQL design
must map them without treating worksheet layout as the database model.

| Domain | Source meaning and integrity boundary |
| --- | --- |
| Profile/ledger | One selected profile owns one configured workbook, Google OAuth grant, Drive folders, caches, and duplicate guards. Never substitute another profile's workbook or credentials after a failure. The shared OAuth client and application password remain deployment-wide. |
| Accounts | Preserve IDs, type/classification, active state, opening balance, and parent hierarchy. Parent IDs reference accounts of compatible classification, without cycles. Preserve opening-balance signs and count them once in balances. |
| Categories | Preserve Income/Expense kind and parent hierarchy of the same kind. Categories are accounting classifications, distinct from Tags. |
| Payees/Tags | Preserve IDs and inactive historical references. Names use the existing normalization/uniqueness rules. Tag ID cells encode JSON arrays, not labels; optional payee IDs reference managed Payees. |
| Simple transactions | Income, Expense, and Transfer reference managed accounts; category/payee/tag references retain their meaning. Transfers move balances without affecting income or expenses. Preserve receipt cells, timestamps, references, and source/recurring provenance. |
| Advanced journals | JournalPostings belong to JournalEntries through `parent_entry_id`, with unique identities/positions, typed Account/Category targets, Debit/Credit sides, positive amounts, and equal total debits/credits. Optional managed payee references remain attached to postings. Advanced journals remain distinct from Simple Ledger transactions in source projections. |
| Mixed-use costs | MixedUseExpenses owns the total, business-use percentage, rounded allocation, rationale, tags, receipts, and linked transaction ID. Exactly one Expense projection carries `source_type=mixed_use_expense` and `source_id` back to the owner; `linked_transaction_id` points back. Preserve matching domain metadata and allocated business amount, without recreating the projection. |
| Recurring | RecurringSchedules owns the recurrence rule/status/template. Occurrences reside in Transactions and, for mixed-use schedules, their source/projection pair. The four `recurring_*` provenance values are either all absent or all present: schedule ID, scheduled date, source kind (`transaction`/`mixed_use`), and occurrence type (`initial`/`generated`). Preserve schedule references and unique dates per schedule; load existing owners and occurrences without replaying the scheduler. |
| Assets/depreciation | Preserve asset acquisition/basis/salvage/useful life, quarter overrides, status/retirement, managed references, and generated depreciation history with stable source IDs. Depreciation transactions and their asset owner form one migration unit. `source_transaction_id` retains acquisition provenance; the current asset model permits an absent historical acquisition transaction, so it is not an unconditional foreign-key requirement. |
| Mileage | Separate trip records with dates, miles, locations/purpose/notes, and optional Tags. Mileage does not become a financial transaction. |
| Receipts | Ledger receipt references are JSON metadata. `receipts.json` preserves referenced and intentionally unreferenced app-managed documents, stable receipt identity, old Drive IDs, original/stored names, MIME type, byte size, SHA-256, available timestamps, and transaction association. Mixed-use receipt references belong to their source/projection relationship. Bytes remain in DocumentStore or a matching recovery copy. Unlinking a reference does not delete the Drive file. |

Receipt inventory schema version remains `1`, independently of archive format
13. Its exact top-level keys are `schema_version`, `business_profile_key`, and
`receipts`. Each entry has `schema_version`, `receipt_id`, `reference_state`,
`transaction_id`, `stored_filename`, `original_filename`, `mime_type`,
`byte_size`, `sha256`, `old_drive_file_id`, `drive_created_time`, and
`drive_modified_time`. The strict inventory validator is
[`receipt_manifest.py`](../tabula_rasa/receipt_manifest.py). Referenced entries
must agree with the transaction's identity and integrity metadata; unreferenced
entries remain recoverable without attachment. Missing inventory is unsupported.

Sheets CSV cells are text: dates retain ISO calendar values, timestamps retain
UTC provenance, money/percentages use the existing Decimal/currency rounding
rules, and booleans retain the supported TRUE/FALSE meaning. Do not round-trip
money through binary floating point during migration. Retain all supported
records, including inactive reference data, past occurrences, retired assets,
journals, receipts, and provenance; a filtered UI export is not a complete
source. Preserve account classification/current earnings and the
`Assets = Liabilities + Equity` accounting check.

## Consumers and sequencing

- **#243:** map this final source into the independent canonical accounting
  model. Schema design proceeds alongside retirement; no production PostgreSQL
  schema migration belongs in #261.
- **#254:** extract the live workbook through a supported read-only boundary,
  consume the shared header validators, and preflight references/provenance
  before target writes. Keep source Sheets unchanged. Define deterministic
  IDs, dry-run behavior, dependency-complete units, and load ordering with
  #243/#255/#256. This contract does not add backup-archive import to #254.
  The [migration framework guide](SHEETS_POSTGRES_MIGRATION.md) documents the
  implemented extraction/reconciliation path. Selected private/live acceptance is
  tracked in [#303](https://github.com/Roklion/Project_Tabula_Rasa/issues/303).
- **#257:** verify supported final-format success and unsupported/retired-format
  rejection without writes, plus whole-profile accounting/reference/receipt
  reconciliation across both backends. Core totals alone do not authorize cutover.
- **#258:** require completed #261 retirement, #257 whole-profile acceptance,
  and verified #260 entity export before migrated-entity activation. Preserve
  the pre-cutover source for rollback only before divergent PostgreSQL writes.
  Commercial production writes additionally require #253 integrity/concurrency
  and #259 real backup/PITR recovery evidence.
- **#223/#259:** own retention and operational recovery. PostgreSQL schema
  migrations, managed backup/PITR, recovery-point schema validation, and
  document-byte recovery remain supported independently of Sheets retirement.
- **#260:** defines a separately versioned complete canonical PostgreSQL entity
  export. It does not inherit this worksheet layout/version and is not a
  PostgreSQL-to-Sheets reverse migration or disaster-recovery replacement.

Profile/OAuth migration, current-format receipt association and byte recovery,
and ordinary CSV/QuickBooks imports remain supported. These tools must still
reject an unsupported ledger before making ledger or document writes. No
permanent dual-write or historical-format runtime is introduced. The
#245/#246/usable-#247 milestone for beginning #221 remains unchanged. Future
consumer tickets own their implementations and acceptance evidence; this guide
supplies the source contract they must use.
