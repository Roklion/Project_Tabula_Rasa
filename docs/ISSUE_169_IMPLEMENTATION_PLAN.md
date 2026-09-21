# Issue #169 implementation plan

Status: implemented locally; final validation results are recorded below.

Issue: [Add advanced multi-line journal entry workflow](https://github.com/Roklion/Project_Tabula_Rasa/issues/169).
Analyzed on 2026-09-20 against `origin/main` commit
`62e32bc85d583e88e317074f022cc1cef85894c3`, including the issue's clarification
that asset depreciation (#120) remains an independent Simple Ledger workflow.

Branch: `codex/issue-169-journal-entries`.
Worktree: `.worktrees/issue-169` under the original repository directory.
The original checkout's uncommitted work is outside this implementation scope.

## Outcome and scope

Add balanced, multi-line journals as an advanced editor under the existing
transaction creation surface. Keep simple transactions as one ledger row with
their existing Add/Edit/Copy/Delete, recurring, receipt, and metadata behavior.
Render journals in that same ledger as one parent followed by every posting.
Mutations, selection, search, sorting, and any future pagination operate on the
logical parent. A posting is never an independently editable transaction.

This work includes accounting/reporting, reference integrity, backups, explicit
migration, and profile isolation. A journal that appears in the ledger but is
absent from balances or reports is not a complete implementation.

Do not add Full Accounting Ledger mode, saved-record conversion, journal import,
a separate journal navigation tab, local ledger storage, or a generalized
transaction manager. Depreciation and mixed-use source ownership remain intact.

## Findings that determine the design

1. `Accounts` contains Asset/Liability/Equity accounts; Income/Expense accounts
   are represented by `Categories`. Depreciation already uses this distinction.
   A journal selector containing only `Accounts` cannot enter the issue's
   Office Expense / Meals Expense / Checking example.
2. `list_transactions()` validates only Income/Expense/Transfer and has many
   callers that assume exactly one source account and amount. Adding a Journal
   kind there would spread special cases into receipt, import, recurring, and
   asset code. Preserve that API and introduce an explicit combined-entry read.
3. `ledger_reporting.py` currently calculates from simple transaction kinds.
   `accounts.py`, `categories.py`, `dashboard.py`, and `reports.py` load only
   simple transactions. All relevant totals and activity counts need integration.
4. The ledger currently filters and searches a one-row-per-transaction frame,
   then maps selected row indexes to transaction IDs. That mapping must change
   when multiple display rows represent one logical entry.
5. `creation.py` uses `st.form`. Browser edits inside a form are buffered until
   submission. An outside segmented selector cannot reliably detect those edits
   by checking Python session state alone.
6. Pinned Streamlit 1.59.2 documents that enabling column selection disables
   column sorting (`streamlit/elements/arrow.py`). Combining row selection with
   column selection is a candidate for preserving `st.dataframe` grouping;
   prove this with the real browser before depending on it.
7. Runtime and backup validation accept only the current schema (format 12).
   New worksheets require a format change and explicit migration, not automatic
   startup repair of older workbooks.
8. Managed Payee merges rewrite references before deleting source payees.
   Journals must participate in that operation. Category delete/kind changes
   must also account for journal references.

## Proposed accounting and storage contract

### Posting identity and direction

Create a small backend-independent `tabula_rasa/journal.py` domain module.
Use a typed target `(target_type, target_id)`, where `target_type` is `account`
or `category`. Display managed account/category hierarchy paths in one Account
selector, with labels identifying classification or Income/Expense kind when
needed for disambiguation. Never infer target type from a display label.

Each posting has its own stable ID, parent entry ID, order, typed target, side,
positive amount, optional managed Payee ID, and description. The input editor
has Debit and Credit columns; normalized storage uses `side = Debit | Credit`
and one amount, so persisted direction is explicit and mutually exclusive.

Use Decimal and the existing cent-rounding convention. Reject nonfinite,
negative, and post-rounding zero amounts. Compare totals after normalization;
never use floating-point tolerance for a journal's balance. Ignore completely
blank placeholders, but reject incomplete populated rows. Persist at least two
valid lines with equal debit and credit totals. Distinct lines may reference
the same target; net-zero adjustments remain representable.

Generate parent and line IDs before attempting a write; preserve line IDs on
edit/reorder and generate new IDs only for newly added lines. Parent identity
is authoritative. Reject duplicate IDs, foreign-parent lines, orphaned lines,
invalid order, unsupported target types, missing references, and unbalanced
stored entries rather than silently dropping corrupt lines.

### Proposed format 13

Add two worksheets, without rewriting simple transaction rows:

| Worksheet | Fields |
| --- | --- |
| `JournalEntries` | `id`, `txn_date`, `description`, `created_at`, `updated_at` |
| `JournalPostings` | `id`, `parent_entry_id`, `position`, `target_type`, `target_id`, `side`, `amount`, `payee_id`, `description` |

Two worksheets expose the relationship explicitly, avoid a growing JSON cell,
and support one native Sheets batch for a complete parent/line mutation. Do not
duplicate journals as ordinary `Transactions` projections. Derive line count
and summary amount (total debits) from validated postings.

Add a cohesive `JournalsMixin` in `storage/google_sheets/journals.py`, composed
through the existing facade. Proposed APIs:

- `list_journal_entries(..., _force_refresh=False)` returns complete entries.
- `get_journal_entry(entry_id, _force_refresh=False)` returns one complete entry.
- `create_journal_entry(entry_id=..., txn_date=..., description=..., postings=...)`.
- `edit_journal_entry(entry_id, expected_entry=..., ...)`.
- `delete_journal_entry(entry_id, expected_entry=...)`.
- A small combined read returns typed logical records from simple transactions
  and journals for ledger/reporting consumers. Keep simple-only callers explicit.

Typed logical IDs include record type so even externally supplied equal UUIDs
cannot confuse a simple transaction and a journal in selection state.

### Mutation boundary

Under the existing workbook ledger lock, freshly read the affected journal
tables and required managed references. Validate the expected complete entry
before edit/delete; compare accounting fields and line identities, not labels
or worksheet positions. Validate new selections against active managed records;
retain existing inactive references only under the established historical-edit
policy. Inactive references from removed lines cannot authorize new lines.

Build one `spreadsheets.batchUpdate` request for parent and posting changes.
Use stable IDs to locate rows from fresh data; worksheet row indexes are only
request coordinates. For deletion, order row deletes so earlier coordinates
do not shift later targets. A confirmed successful response is authoritative.

Invalidate all affected caches on confirmed or uncertain writes. On an uncertain
response, perform one fresh complete-entry readback: accept exact final state,
otherwise stop with actionable guidance unless one retry is demonstrably safe.
For this feature, stopping after an unconfirmed outcome is an acceptable simpler
default. Do not blindly replay row-index-based deletes or build a reconciliation
loop. The existing `_write_with_uncertain_readback` can read again after a retry;
do not adopt it unmodified if that violates the one-readback contract.

A repeated create ID with the same canonical payload returns the existing
entry; the same ID with different content is a conflict. Preserve draft IDs
across failed/uncertain submissions, and scope draft/duplicate state by profile
and configuration. Increment workbook data revision only on confirmed success.

### Managed references and backup integrity

Extend category deletion and category-kind-change guards for journal postings.
Update Payee merge's fresh snapshot, reference rewrite, native batch, uncertain
outcome classification, and cache invalidation to cover journal lines before
deleting source payees. Review account edit/classification and deactivation
paths for equivalent existing invariants. Update managed activity counts to
count logical entries, deduplicating several postings to one target.

Add format 13 to current schema, backup export, validation, checksum manifest,
and blank-workbook restore. Share journal structural/reference validation
between live storage reads and backup validation. Restore still refuses the live
workbook and restores only into a new blank workbook.

Snapshot version-12 headers in `scripts/migration_schemas.py`. Extend
`migrate_workbook.py` to recognize the previous schema and explicitly add empty
journal tables; extend `migrate_legacy_backup.py` to accept v12 and generate a
validated v13 archive with empty journal tables. Preserve earlier supported
conversion routes and existing source data/provenance. Runtime never upgrades
an old workbook or archive implicitly.

## Accounting/report integration

Introduce a pure posting adapter (for example `accounting_postings.py`) used by
reporting. Its outputs carry entry type/ID, line identity, date, typed target,
explicit side, and Decimal amount. Journal lines pass through; simple rows expand
deterministically in memory:

| Simple kind | Debit | Credit |
| --- | --- | --- |
| Income | Selected account | Income category |
| Expense | Expense category | Selected account |
| Transfer | Destination account | Source account |

This adapter is not a second persisted ledger. Do not add fabricated transactions
to make existing report APIs accept journals.

- Account raw balances: opening balance plus account debits minus credits.
- Expense activity: expense-category debits minus credits.
- Income activity: income-category credits minus debits.
- Earnings: income minus expenses; preserve current Liability/Equity display
  sign conventions and the accounting equation.
- Transfers remain excluded from P&L. Journals containing no cash account do
  not imply a cash movement. Existing noncash depreciation remains unchanged.
- Preserve category/account hierarchy rollups without double counting parents.
- Apply entry date consistently to monthly, period, and as-of reports.
- Dashboard recent activity uses the latest eight logical records, with compact
  journal summaries; it must not count postings as separate recent entries.

Integrate `ledger_reporting.py`, `ledger_presentation.py`, Accounts, Categories,
Dashboard, Reports, and relevant export consumers. Keep receipt recovery,
transaction import, recurring schedules, and source-managed asset flows on
their simple-only APIs unless they explicitly need journals.

## Creation and editing workflow

Add `entry_creation.py` coordination and a cohesive `journal_editor.py` rather
than growing every behavior inside `creation.py` or `ledger.py`.

1. Render top-level Entry Type: Simple Transaction (default), Multi-line Journal.
2. Render one shared Date and optional entry memo where practical. Allow the
   shared field composer to accept supplied values for creation while retaining
   existing edit/copy defaults. Do not duplicate hidden sources of truth.
3. Preserve simple field composition, receipt recovery, recurrence creation,
   managed Payee/Tag behavior, validation, and success/reset sequencing.
4. Solve dirty switching before adding journal UI. Preferred implementation:
   render creation fields as normal widgets in the existing styled container,
   with a Save button, so changes reach session state; retain shared helpers.
   Existing Edit/Copy forms can remain forms. Verify keyboard behavior and
   browser change/blur ordering. A form-buffered approach is acceptable only
   if a prototype proves it cannot discard unsubmitted browser values.
5. Track committed editor mode separately from a requested mode. With a dirty
   draft, keep the current editor mounted and offer explicit discard/switch or
   cancel. Confirm clears only mode-specific state; cancel preserves every field.
   Compare values to initial defaults, including receipt uploads, reference,
   tags, payee, recurrence, amount, and journal row edits. Pending receipt or
   uncertain-save recovery must be resolved before changing editors.
6. Start journals with two blank rows. Provide explicit + Add line and a remove
   control per row; maintain at least two usable rows. Stable widget/line keys
   prevent values moving to another row after removal.
7. Provide Account, Debit, Credit, Description, and Payee per row with managed
   selectors where practical. Use a table-like row grid that can stack on narrow
   screens; prove that it satisfies the requested editable-table interaction.
   Avoid relying on `st.data_editor`'s automatic blank row as the add mechanism.
8. Show debit/credit totals, signed difference, and specific validation messages
   immediately. Disable Save until valid; revalidate in storage regardless.
9. Saved-record editing routes by stored type and has no Entry Type conversion
   selector. Journal edits/deletes always receive a complete parent snapshot.
10. Reuse permanent-delete acknowledgement strength and parent-level success
    notices. No line-level permanent deletion action exists.

Initial journal metadata is date, entry memo, and posting payee/description.
Journal receipt attachments, recurring journals, journal copying, and journal
Tags are not required by #169 and are not added speculatively. Preserve these
features for ordinary transactions. Document journal-specific limits clearly.

## Unified ledger pipeline

Build and test the following pure pipeline before integrating Streamlit:

```text
simple transactions + complete journal entries
    -> filter logical records
    -> search parent and all posting fields
    -> sort logical records with stable tie-breakers
    -> optional logical pagination
    -> flatten parent plus all child rows
    -> display rows + authoritative row-to-logical-ID mapping
```

For journals, any matching posting account/payee/description retains the whole
entry. Type filtering includes an explicit Journal choice. Account filtering
uses typed account/category targets with clear labels; simple filtering retains
its current meaning. Tag filters continue to match simple records; initial
untagged journals do not match an active Tag filter.

Preserve current simple columns/values. Add Debit/Credit columns only when
journals are present in the rendered result. Parent: date, Journal indicator,
ID, memo, Multiple accounts / N postings, amount = total debits. Children:
subordinate glyph, account/category path, one of Debit/Credit, payee, description;
blank repeated parent values and no independent summary amount.

Provide app-level logical sort controls. When grouped rows are visible, use
the verified Streamlit configuration that disables native sorting. Row plus
column selection is the first candidate; ignore column-selection events as
accounting actions and explain the controlled sort UI. Test every header and
menu sorting path. CSS-only interception is not sufficient evidence.

Map selected display rows back to typed parent IDs and deduplicate them. Counts,
delete totals, selectors, and exports operate on unique logical records. Include
sort, filters, visible parent/line identities, profile/configuration, and workbook
revision in selection scope so a stale browser event cannot target another entry.

Ordinary Copy/Edit/Bulk behavior remains available for eligible simple rows.
For the initial scope, disable bulk field edits, copying, and bulk deletion when
the selection includes a journal; explain that journals are edited/deleted as a
whole through the journal editor. Never silently apply an action to only the
simple subset. Export selected may include complete journals and all postings.
Single parent deletion satisfies the issue without introducing mixed-type bulk
mutation machinery.

Data & backup must not silently omit journals from a download presented as a
complete ledger. Keep the ordinary transaction CSV contract and expose a separate
explicit journal-posting CSV with parent ID/date/memo and line fields, or a
clearly labeled complete ledger export. Decide exact labels during UI integration;
backups always include both journal worksheets.

## Delivery sequence and agent ownership

Use bounded assignments with explicit file ownership, shared contracts, and
focused tests. Do not let multiple agents concurrently edit the same facade,
schema, reporting module, or transaction renderer.

| Stage | Work | Owner / dependency | Exit evidence |
| --- | --- | --- | --- |
| 0 | Prove safe mode switching and no native grouped-row sorting | Primary with a lower-cost UI agent | Browser prototype at desktop/narrow widths; settled API contracts |
| 1 | Domain validation and deterministic posting adapter | Lower-cost agent; primary reviews accounting | Balanced/unbalanced, currency, signs, simple parity, reversal tests |
| 2A | Journal schema, storage, reference integrity | Lower-cost storage agent after stage 1 | Complete batch create/edit/delete, stale, duplicate, uncertainty, two-profile tests |
| 2B | Logical filtering/search/sort/flatten functions | Lower-cost presentation agent after stage 1; parallel with 2A | Parent-child grouping and identity tests |
| 3 | Backup/migration and reporting consumers | Primary integrates storage/report contracts; delegate isolated migration tests | Format-12 conversion, v13 roundtrip/corruption rejection, report parity |
| 4 | Creation/journal editor and ledger routing | UI agent after 2A/2B; primary owns shared renderer integration | AppTest create/edit/delete, dirty switches, simple workflows |
| 5 | Exports, docs, regression and browser verification | Primary; bounded test/doc tasks may use lower-cost agents | Acceptance matrix complete; full validation passes |
| 6 | Broader separate-context review | Deferred to the later PR review at the user's request | Publication and review are separate from this implementation stage |

GPT-5.6-sol is a suitable lower-cost implementation model for the bounded storage
and UI tasks. Keep accounting architecture, integration decisions, and final
acceptance checks with the primary agent. Use one coherent feature branch with staged local
commits; every Codex-created commit includes `Made-with: Codex`.

Publication is a separate action: this request does not authorize pushing,
opening a PR, posting GitHub comments, or merging.

## Acceptance and validation matrix

| Area | Required scenarios |
| --- | --- |
| Domain | Two-line and 3+ line balance; both sides/zero/negative/nonfinite; cent rounding; blank versus incomplete rows; debit-only and credit-only rejection |
| Identity/storage | Stable parent/line IDs; order changes and line add/remove; duplicate payload idempotency; conflicting duplicate; wrong parent; whole delete; fresh stale-write conflict |
| Uncertainty | Success without verification read; committed-but-response-lost confirmed by one read; unchanged/unknown state stops safely; cache invalidation; no partial success notice |
| References | Missing/inactive account; Income/Expense category target; inactive historical retention; category deletion/kind change; Payee merge preserves every line |
| Isolation | Two profiles using equal IDs; independent storage, draft widgets, guard fingerprints, selection, and exports; switching during an unsaved journal |
| Accounting | Expense 100 + Expense 50 / Cash credit 150; income split; account-only transfer; expense credit reversal; noncash journal; liability/equity signs; opening balances; equation; hierarchy rollups; dates |
| Existing sources | Mixed-use remains one allocated projection; depreciation remains source-managed, noncash, and independent of journal UX; receipt/recurrent/simple-copy regressions |
| Creation | Simple default; exactly two blanks; explicit add/remove; running totals; disabled invalid save; dirty switch confirm/cancel including buffered browser input and uploads |
| Ledger | One ordinary row; parent plus all lines; child selects parent; search/filter retains all siblings; stable sort; header/menu cannot split group; no duplicate counts; filtered/stale selection clears |
| Editing | Correct editor by saved type; no conversion control; edits preserve unchanged line IDs; missing/stale entry rejection; complete delete with acknowledgement |
| Bulk/export | Simple behavior preserved; mixed selection never silently partially mutates; deduplicated whole-entry export; journal data visible in complete backups/downloads |
| Recovery | v13 backup roundtrip; checksums/manifests; orphan/duplicate/unbalanced rejection; v12 explicit conversion; runtime rejection of old schema; restore refuses configured live workbook |
| Browser | 1440x1000, 1200x900, 900x900, 390x844; entry selector, confirmation, row controls, totals, grouped ledger and selection; no page-level horizontal overflow |

Use fake services and synthetic fixtures only. Extend the existing storage,
migration, ledger-reporting, AppTest, and `.smoke_local` browser infrastructure.
Run focused tests and lint for each assignment. Before publishing and again at
the repository's final review gate run from this worktree in its active env:

```text
ruff check .
python -m pytest
git diff --check origin/main...HEAD
```

Also inspect uncommitted changes with `git diff --check` before local commits.
Update `design.md` current behavior, `docs/USING_TABULA_RASA.md`,
`docs/ARCHITECTURE.md`, `docs/BACKUP_RECOVERY.md`, and migration/setup guidance
as applicable only when the implementation establishes the new behavior.

## Implementation and validation results

The local implementation includes the journal domain model, format-13 storage,
whole-entry mutations, accounting projections, grouped ledger, creation/editing,
reference checks, journal CSV export, backup validation, explicit migration,
and updated current-behavior documentation. Simple transaction storage and
source-managed depreciation remain separate from journal persistence.

Sol implemented bounded storage and UI work; Terra checked concrete mutation
boundary defects; Luna completed migration, export, payee, and isolation checks.
The primary agent integrated reporting, ledger presentation, and acceptance
tests. Broader code review is intentionally deferred to the later PR stage.

The isolated worktree uses its own Python 3.13.14 environment with the pinned
development dependencies and Streamlit 1.59.2. Python 3.12, requested by the
checked-in Codex setup script, was not available locally. The original checkout's
environment was not modified. Tests run with `PYTHONUTF8=1` to avoid a Windows
subprocess stderr decoding failure in the environment-setup tests.

The journal browser smoke check passes at 1440x1000, 1200x900, 900x900, and
390x844. It exercises immediate dirty-draft switching, cancel/confirm behavior,
explicit add/remove controls, and canvas-rendered grouped rows under header
clicks, with no page-level horizontal overflow. AppTest coverage exercises
creation, logical search, mixed bulk-selection restrictions, whole-entry edit
with stable posting identity, deletion, and profile isolation.

### Continuation verification — 2026-09-21

Rechecked remote head `1c856fa` against issue #169 and its #120 dependency
clarification in a clean worktree. The remote branch is spelled
`codex/issue-169-journal-entries`. Continuation work is on local branch
`codex/issue-169-completion` in `.worktrees/issue-169`.

The feature was implemented at that head. Focused UI and storage/accounting
audits found one required correction: profile switching omitted the raw draft
comparison snapshots from cleanup. Both simple and journal raw baselines now
clear with the outgoing profile. Regression coverage switches between two
profiles, returns to a fresh Simple Transaction editor, and confirms switching
to Journal needs no discard confirmation. A populated middle-row removal test
also verifies surviving posting identities and values remain attached.

Validation uses the existing development environment at
`C:/Projects/Candice_Tabula_Rasa/.venv` (Python 3.12.10), without changing its
dependencies, with `PYTHONUTF8=1`. The initial unrestricted full run passed all
1,181 tests. Sandbox-only failures creating temporary files were environmental;
the redundant sandbox run was stopped. The journal browser check passed at
1440x1000, 1200x900, 900x900, and 390x844. After the profile-reset correction,
the full suite passed **1,182 tests** in 47.17 seconds; `ruff check .` and
the uncommitted-change whitespace check also passed.

The ordinary transaction browser smoke initially failed because it expected
the old `Upload receipt` label. Updated its locator to `Receipt (optional)`
and scoped it to the visible ledger tab. All four ordinary transaction
viewports then passed, as did all 18 smoke-runner tests. Removed the extra
blank line at the end of the journal payee UI test to satisfy the branch
whitespace gate.

Publication and the broader PR review remain separate, unperformed actions.
