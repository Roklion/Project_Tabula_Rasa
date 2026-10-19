# Supported-capability retirement inventory (#377)

This is the source-level retirement inventory for [#377](https://github.com/Roklion/Project_Tabula_Rasa/issues/377),
under [EPIC #221](https://github.com/Roklion/Project_Tabula_Rasa/issues/221) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Audit baseline: `5693ebbbf48fa7198366c580e40a68a7c887b061`, October 19, 2026.
Decisions below describe this cleanup slice, not a live deployment or permission
to delete data. Issue references identify responsible workstreams, including
completed implementations; their closure alone is not operational evidence.

## Operating modes and evidence boundary

- **Retain internal:** Streamlit, current-format Google Sheets and profile-scoped
  Drive remain supported for authorized unmigrated internal users. The local
  administrator remains loopback/operator/password protected independently of
  commercial membership. A migrated entity must never fall back to stale Sheets.
- **Retain new stack:** React/FastAPI/PostgreSQL, named identity and scoped document
  adapters remain the target architecture. Shared application/domain owners serve
  thin adapters; worksheet and SQL mutation/recovery semantics remain distinct.
- **Retire now:** only the demonstrably uncalled implementation artifacts listed
  below. No supported action, backend, format, provider or deployment mode is removed.
- **Deferred:** retain the named capability until its specific evidence condition
  is met. Deferral records a responsible issue and next decision; it does not create
  a replacement subsystem or a new alpha, cutover, beta or initiative gate.

Read the [routing matrix and retirement criterion](TECHNICAL_ALPHA.md#feature-routing-and-authority-during-transition),
[existing workflow ports](COMMERCIAL_WORKFLOW_PORTS.md),
[cutover procedure](BOOKKEEPING_CUTOVER.md), and
[local administration inventory](EXTERNAL_CONNECTIONS_AND_LEGACY_CLAIMS.md#retained-local-administration-inventory)
together. #288 accepted technical alpha, not repository-wide Streamlit retirement.
All seven workflow-port implementations (#357–#359, #361–#364) are delivered;
selected deployment/provider/owner verification remains separate. At this audit,
#303 still records all seven live-cutover criteria pending for the three active
profiles, and #321 still has outstanding hosted named-user acceptance. No private
profile identities, authority records or credentials were inspected or copied.
Remaining installed deployments, manual CLI users and recovery consumers have
not been operator-confirmed. They remain supported, with user/target confirmation
assigned to D1/D3/D4/D6 below; absence of a known caller is not a claim of zero users.

## Capability, caller and ownership inventory

Paths are relative to the repository root. Each row includes its active entry
points/callers; directory groups cover the corresponding domain modules and tests.
`D1`–`D7` refer to concrete deferral conditions in the next section.

### Runtime, domain and workflow paths

| Capability and active source/callers | Users/backend and owner | Decision and evidence |
| --- | --- | --- |
| `tabula_rasa/app.py`, `composition.py`, `page_renderers/`; README Quick start and `.streamlit/config.toml` start the internal app; `create_sheets_application` supplies its services | Internal users; Sheets/Drive; #221/#303 | **Retain, D1.** `app.py` initializes unmigrated profiles and refuses maintenance/PostgreSQL profiles. Shared services do not make the shell obsolete. |
| `http/serve.py`, `http/app.py`, `http/composition.py`, `http/migrated.py`, `web/src/main.tsx`, `web/src/app/`; Docker/uvicorn and React router are the entry points | New-stack users; PostgreSQL; #221/#279/#303 | **Retain.** `open_migrated_runtime` is a documented operator composition seam even where tests are its only in-repository caller. |
| `application/services.py`, capability services/contracts and pure accounting, reference, hierarchy, journal, recurrence, mixed-use and depreciation modules; both compositions and their adapters call them | Both modes; #219/#220/#221 | **Retain shared owners.** Extend these owners for future consolidation; do not copy rules into endpoints or rebuild a storage facade. |
| `infrastructure/google_sheets*.py`, `storage/google_sheets/`, `storage/__init__.py`; internal composition, explicit workbook administration and migration readers | Sheets internal/operator; #219/#220/#303 | **Retain, D1/D3/D4.** Schema/client/domain mixins own non-transactional writes, caches and bounded uncertainty. Public facades remain useful compatibility boundaries. |
| `infrastructure/postgres/`, `application/baselines.py`, `http/baselines.py`; HTTP/services, jobs, migration and recovery consumers | PostgreSQL; #220/#280/#223 | **Retain.** SQL transactions, loaded baselines, locks and canonical provenance are independent of Sheets mutation semantics. |
| `page_renderers/accounts.py`, `categories.py`, `transactions/payees_tags.py`; HTTP references/accounts and React reference editors | Both modes; #281/#219 | **Retain adapters, D1.** Shared reference services own normalization/hierarchies; each transport retains its rendering and authorization. |
| `page_renderers/transactions/{creation,ledger,ledger_editor,ledger_bulk,transaction_copy}.py`; HTTP accounting and React workflow pages | Both modes; #282/#358/#280 | **Retain, D1.** Simple entries, transfers, journals, copy and protected bulk actions remain supported. |
| `ledger_records.py`, `ledger_queries.py`, `ledger_presentation.py`; live Streamlit ledger; `application/reporting.py`, `ledger_reporting.py`, HTTP reporting and browser reports | Both modes; #282/#359 | **Retain shared calculation/presentation, D1.** Complete journal grouping, opening-balance signs, transfer exclusion and balance checks remain required. Replace the unused search predecessor below. |
| `page_renderers/transactions/{recurring,mixed_use,recurrence_controls}.py`, `recurrence_state.py`; application recurring/mixed-use services, HTTP secondary routes and React secondary pages | Both modes; #284/#362/#334 | **Retain, D1/D5.** `PendingRecurrenceState` is the active stable-ID/payload owner; remove only its unused key-access wrappers. Source/projection and independent-copy semantics remain supported. |
| `app.py` profile-initialization reconciliation; explicit Generate due occurrences; `infrastructure/postgres/{jobs,recurring_jobs}.py` and job CLI | Internal Sheets and PostgreSQL workers; #303/#333/#334/#223 | **Retain distinct authority paths, D5.** Worker implementation completion does not activate a hosted timer or retire internal page-triggered reconciliation. |
| `page_renderers/assets.py`, application asset/depreciation owners, PostgreSQL assets and HTTP/browser secondary workflows | Both modes; #285/#303 | **Retain, D1.** #303's proposed depreciation operational deferral is not accepted retirement; data/history and asset-register functionality stay supported. #121's new mixed-use asset features are outside cleanup scope. |
| `page_renderers/mileage*.py`, `application/mileage.py`, Sheets/PostgreSQL mileage adapters and browser mileage/import pages | Both modes; #286/#363/#364 | **Retain, D1.** Shared mileage preparation is active; remove the unused pre-extraction `_positive_miles` only. Keep financial/mileage separation, one-decimal normalization, round-trip and duplicate checks. |
| `address_autocomplete.py`, `maps_routing.py`, `google_maps_quota.py`, `http/maps.py` and React Maps fields | Both modes, app-wide Maps credentials/quota identity; #363/#133 | **Retain, D1/D7.** Internal quota sidebar and Google routes remain supported; remove only two uncalled display/calculation helpers. Drive grants never replace Maps quota credentials. |
| `application/import_files.py`, `imports.py`, `financial_csv.py`, QuickBooks parsers; `page_renderers/data_backup/`, HTTP import/CSV routes, React imports/exports | Both modes; #357/#359/#364 | **Retain, D1.** Existing supported formats and escaping/selection rules are shared. Category-template import #360 and standalone report downloads are excluded ideas, not missing replacements. |

### Documents, identity, operator and recovery paths

| Capability and active source/callers | Users/backend and owner | Decision and evidence |
| --- | --- | --- |
| `application/documents.py`, `receipt_context.py`, `infrastructure/google_drive_documents.py`, `entity_documents.py`, `drive_composition.py`, `google_drive/`; page receipt controllers and HTTP/browser documents | Both modes; profile/entity-scoped Drive; #233/#283/#318/#337/#361 | **Retain, D1/D3.** Ordinary and mixed-use source ownership, reference-only unlink, unreferenced-file recovery and retained bytes remain supported. |
| `infrastructure/s3_documents.py`, `requirements-object-storage.txt`, `docs/OPTIONAL_OBJECT_STORAGE.md`, `tests/s3_support.py` and S3 adapter/recovery tests | Explicit optional provider, not active commercial image; #337/#338/#382 | **Retain, D7.** Deliberate optional contract and recovery support; current Drive selection does not authorize deleting an implemented alternate provider. |
| `http/alpha.py`, `alpha_documents.py`, `TrustedDevelopmentContext`, deployment alpha module and `commercial-alpha.yml`; restricted-alpha/local fixtures and explicit alpha gate | Synthetic development/restricted staging; #288/#321 | **Retain, D2.** Named-user/production settings reject alpha bypass; synthetic tooling still has an independent supported use. |
| `application/{identity,authorization,connections,workspaces}.py`, PostgreSQL control-plane/session/grant/claims adapters, HTTP identity/workspaces and React identity pages | Named-user PostgreSQL; #222/#313/#318/#319 | **Retain.** #385–#388 own the business-centric access pivot under #124. Cleanup must not implement a second identity model or infer operator power from membership. |
| `legacy_admin.py`, `local_profile_admin*.py`, `local_profile_store.py`, `business_profiles.py`, `google_drive_admin.py`, `google_drive_picker.py`; Business Profiles/Account settings and `scripts/run_local_profile_admin.ps1` | Restricted internal operator; Sheets/profile config/Google grants; #319/#222 | **Retain, D3.** Registration, workbook selection/bootstrap, grants, backups and secrets export still have local owners. Remove the uncalled old setup-error formatter only. |
| `ledger_auth.py`, `legal.py`, Streamlit session/submission guards; internal shell and public legal routes | Internal deployment and protected profile workflows; #221/#222/#224 | **Retain, D1/D3/D7.** Application password and shared OAuth client are deliberately deployment-wide. Internal legal text is not commercial acceptance. |
| `application/support.py`, PostgreSQL support/audit/periods/jobs, HTTP support/period routes and operator CLI | Named authorized operators; PostgreSQL; #223/#341 | **Retain.** Scoped diagnostics/containment are not replacements for every local credential/restore action; deployed grants/acceptance remain separate. |
| Sheets backup mixin, `receipt_manifest.py`, `receipt_backfill.py`, `receipt_recovery.py`, `synology_recovery.py`; Data & backup, receipt controllers and backup/restore/recovery scripts | Internal/operator current-format Sheets/Drive/local recovery; #220/#261/#319/#339 | **Retain, D4.** Blank-target/live-workbook refusal, manifest/checksum/version checks and profile isolation still apply. Historical schema acceptance must not return. |
| `bookkeeping_export/`, `migration/`, PostgreSQL migration/cutover/export/recovery adapters; `scripts/{migrate_sheets_to_postgres,cutover_bookkeeping,export_postgres_entity,verify_postgres_recovery}.py` | Operator, frozen Sheets source to PostgreSQL/recovery; #220/#303/#223 | **Retain, D1/D4.** Acceptance, 26-collection export, provenance and divergence protection outlive old UI writers. `bookkeeping_export/accounting.py` intentionally reconstructs exported facts for independent tests. |
| PostgreSQL Alembic versions and SQL; migration CLI, image startup/release schema checks and recovery consumers | All deployed PostgreSQL environments; #220/#223 | **Retain permanently as deployed history.** No squash, rewrite or deletion follows from runtime retirement. |
| `application/document_recovery.py`, `infrastructure/document_archive.py`, Drive copy/promotion adapters; `scripts/{drive_document_recovery,manage_document_storage,benchmark_receipt_recovery}.py` and hosted drill | Private operator Drive/PostgreSQL recovery; #338/#342 | **Retain, D4/D7.** #338's completed manual isolated hosted drill does not establish scheduled backups, alternate custody or all operational guarantees. |
| `scripts/migrate_profile_oauth.py`, `scripts/migrate_receipt_associations.py`; documented explicit conversion and `tests/migrations/` | Explicit internal operator preparation; #215/#217/#220/#303 | **Retain, D6.** One-time conversion is outside startup/restore; source-only inspection cannot establish that no supported user still needs it. No obsolete workbook-format converters are added. |

### Packaging, deployment, scripts, fixtures and documentation

| Surface and active callers | Owner | Decision and evidence |
| --- | --- | --- |
| `requirements.txt`, `requirements-dev.txt`, `.devcontainer/`, `.codex/environments/`, `.streamlit/config.toml`; README/dev setup and internal tests | #221/#223 | **Retain, D1/D3.** Streamlit/gspread/plotly remain used; no dependency is removed on image-exclusion evidence alone. |
| `requirements-api.txt`, `requirements-postgres.txt`, `deploy/commercial/{Dockerfile,render.yaml}`, `.dockerignore`, `.env.example`; HTTP runtime and release workflows | #279/#221 | **Retain.** Commercial image already excludes installing Streamlit/gspread; CI checks imports. Copying source into the image is not proof that an internal package is unused repository-wide. |
| `.github/workflows/commercial-{image,staging,promote,alpha,staging-maintenance}.yml`, `tabula_rasa/deployment/`; release, promotion, explicit maintenance and alpha entry points | #279/#288/#321/#223 | **Retain, D2/D7.** Selected release, immutable-image/schema checks, safe smoke and rollback remain independently owned. |
| `.github/workflows/ci.yml`, `scripts/summarize_ci_timings.py`, `docs/evidence/ci-376/`, `web/playwright*.ts`, contract/UI/native tests | #295/#376/#223 | **Retain.** Required full-suite aggregate and independent partitions remain unchanged. #376 already owns measured execution deduplication; no blanket test selection or retries. |
| `scripts/{backup_google_sheets,validate_google_sheets_backup,restore_google_sheets_backup,recover_synology_receipts}.py`, `register_weekly_backup_task.ps1` | #261/#319/#223/#339 | **Retain, D4.** Windows weekly Sheets scheduling is not the PostgreSQL NAS scheduler. Keep documented current-format recovery and existing retention policy. |
| `scripts/{validate_google_sheets,validate_app_google,export_streamlit_secrets,set_app_password}.py`, Google/identity/document management scripts | #319/#318/#321/#223 | **Retain, D3/D7.** Explicit operator entry points count as callers even if imported only by tests; credentials remain private. |
| `deploy/nas/`, `scripts/nas_postgres_backup.py`, `tests/tooling/nas_backup_smoke.py`; NAS operator and required CI drill | #294/#223 | **Retain, D4.** NAS acceptance is still open; preserve all successful generations under the current indefinite-retention policy. |
| `.github/workflows/drive-recovery-drill.yml`, `scripts/run_hosted_drive_recovery.py`; explicit manual hosted drill | #338/#342 | **Retain.** Reviewed main-history selection, fresh folders, encrypted evidence/custody and bounded execution remain necessary for reproducible isolated drills. |
| `.smoke_local/`, `scripts/smoke_{transactions,journals,assets}.py`; optional explicit viewport checks | #221/#287/#331 | **Retain, D1.** Fake Sheets UI checks protect a supported shell, not the React/native-browser contract. Synthetic secret-shaped fixture files are not live credentials. |
| `tests/conftest.py`, `fakes.py`, `app_support.py`, `google_auth_fixtures.py`, domain-local `_support.py`; Sheets/Drive/UI tests | #219/#221/#222 | **Retain, D1/D3/D4.** Existing fixture owners already share schema/defaults/auth; fresh per-test workbooks and two-profile scope remain essential. |
| `tests/postgres/conftest.py`, native/browser support, `web/src/test/`, `web/e2e/`, `web/contracts/`; real-storage, controlled-transport and frontend tests | #220/#221/#222/#376 | **Retain.** These represent distinct persistence/HTTP/DOM/browser boundaries, not duplicate copies of Sheets tests. No broad fixture merger is justified. |
| README, `design.md`, internal setup/usage/backup guides, architecture and commercial/cutover/operations guides | #221/#124 with domain owners | **Retain and clarify scope.** Link this inventory, qualify Sheets-specific introductions and remove the superseded pre-acceptance instruction block from the transition drafts. Git history and linked #288 acceptance retain historical evidence. |

## Deferred decisions and concrete eligibility conditions

| ID | Responsible owner | Required evidence before a later removal |
| --- | --- | --- |
| D1 — internal bookkeeping and adapters | #303 live execution; #221 workflow owners | Inventory every remaining user/source and consume actual accepted selected-release workflow/auth/provider/migration/authority evidence. For the three owner profiles, #303 owns source freeze, writer drain, complete acceptance/export, activation, post-write restart/report/export/isolation and operator acceptance. Migrate or explicitly retire every other internal use separately. Preserve source and recovery tools even when writers retire. |
| D2 — restricted alpha mechanisms | #321 identity rollout; #288 alpha contract; #221 deployment | Establish accepted named-user transition/rollback for affected environments and a separate retain/replace/retire decision for local synthetic contexts, explicit alpha journeys and their scripts/tests. A staging mode switch alone does not retire reusable synthetic tooling. |
| D3 — local administration and credentials | #319/#222, #318 connections, #313/#341 privileges | Map each registration, Google grant/Picker/workbook bootstrap, profile edit, secrets export and recovery configuration action to a verified authorized replacement or explicit maintainer retirement. Verify remaining operator users, scope isolation and credential custody. Keep loopback/password/reauthentication until that decision; named Owner is not local operator. |
| D4 — backup, migration and recovery | #223/#294/#338/#342; #220/#261 source contract; #339 resources | Inventory retained recovery callers and demonstrate an accepted replacement for each capability proposed for removal. Preserve frozen source, archive versions/checksums, export verification, receipt bytes and deployed schema history. #339 owns separately approved resource disposal; neither #303 nor this inventory authorizes deleting artifacts. |
| D5 — recurring generation authority | #303 owner choice; #333/#334/#223 operations | Obtain the pending manual-versus-automatic owner decision, then verify the chosen runtime/entity/time-zone authority and any required hosted timer, restart/catch-up/failure/isolation behavior. Drain the old generator before enabling its replacement. Preserve legacy generation while internal users require it. |
| D6 — explicit one-time conversion | #222 profile owners; #220/#303 migration owners | Confirm remaining supported source users no longer need the particular converter, or obtain an explicit retirement decision with preparation guidance. Keep conversion out of normal startup/restore. File age and no automatic caller are insufficient. |
| D7 — provider/configuration/operator/release mechanisms | Applicable #133/#222/#223/#224/#382 owner | Verify the affected selected provider and entry point, authorized operational replacement and absence of remaining internal/test/recovery consumers, or record explicit retirement. No provider purchase, Maps rotation, business-access pivot, customer admission or launch work is added by cleanup. |

## Implemented removals and independent test review

A tracked-source symbol search plus import/caller inspection was used to find
candidates. Search counts alone are not deletion evidence: decorators, `__all__`,
CLI entry points, documented public seams and test-only independent verifiers were
reviewed before deciding. No generic dead-code scanner or exclusion framework is
added to runtime or CI.

| Removed/replaced artifact | Caller/replacement evidence and invariant/risk rationale | Retained coverage |
| --- | --- | --- |
| `page_renderers/transactions/search.py` (`filter_transaction_rows`, `_searchable_text`, old field list) | Only `test_transaction_search.py` and one mixed-use test called it. Live `transactions/ledger.py` already calls `ledger_records.search_ledger_entries`, which also preserves complete journals. Remove the parallel algorithm and retarget supported field/case/trim/tag/exclusion/no-mutation checks to that active owner. | `test_transaction_search.py`, `test_journal_ledger_records.py` (posting match retains all siblings), `test_mixed_use_ui.py` (projection counted once), existing ledger UI tests. Hidden filename/Drive metadata exclusion uses populated synthetic fields. |
| Old search tests for numeric ID/reference `0`, three NaN variants and `Fraction` in arbitrary display dictionaries | They specified an uncalled helper's generic coercion, not validated ledger inputs. Stable IDs and searchable text are strings; amounts are excluded. Retain a text `"0"` reference regression and all supported field/exclusion checks; remove the four NaN/Fraction cases. No production search behavior is changed to satisfy an obsolete helper test. | Active search tests above; input validation remains in domain/storage tests. No accounting or valid-input isolation contract is removed. |
| `recurrence_controls.py`'s four `*_edit_pending_{schedule,payload}_key` wrappers and now-unused imports/exports | No runtime or test caller. `ledger_editor.py` and `mixed_use.py` already call `transaction_edit_pending_state` / `mixed_use_edit_pending_state` directly. Remove adapters that expose fragments of the same state owner. | `test_recurrence_state.py` preserves stable IDs/original payload, configuration changes, exact profile suffixes and two-profile separation; recurring and mixed-use UI retries stay covered. |
| `local_profile_admin_support.profile_setup_error_message` and its four parametrized tests | Formatter had no runtime caller after profile registration was separated from Google setup. Current forms catch `LocalProfileStoreError`; Google setup and fresh readiness own remote-error handling. The removed test cannot establish secrecy for those live paths. | `test_local_profile_admin.py`, `test_profile_readiness.py`, `test_google_drive_admin.py`, `test_legacy_admin_boundary.py`; actual profile-summary masking is asserted in the existing display test. |
| `google_maps_quota._format_google_timestamp`, `_utilization` | No caller/import/test; current sidebar formats usage through its live row construction and `_usage_in_limit_unit`. No quota grant or fetch behavior is changed. | `test_google_maps_quota.py`: scoped dedicated credential identity, unit conversion, unavailable/unlimited usage, sanitized failure and cached-report behavior. |
| `storage/google_sheets/journals._stored_values` | No caller/import/test; journal signatures/baselines and stored-row construction use active journal methods. | Sheets journal success/conflict/uncertainty and reporting/UI tests remain; no write-boundary coverage removed. |
| `storage/google_sheets/validation._positive_miles` and its unused module export | No caller, including facade/dynamic imports; mileage facade delegates to `application.mileage.prepare_mileage_trip` and its normalization. Keep the used facade/private preparation adapter. | `test_mileage_service.py`, Sheets mileage/tag tests: positive finite values, rounding, no-write validation failure, import/round-trip and two-profile isolation. |
| Superseded pre-acceptance instruction block in `TECHNICAL_ALPHA_TRACKING_DRAFTS.md` | #288's accepted handoff and current workflow-port guide supersede instructions to publish still-draft trackers or await the already-merged runtime. Retain scoped TA descriptions, approved exclusions and reusable acceptance template. | Documentation links and current owner/operator gates remain; this removes no release validation or historical Git evidence. |

Additional reviewed candidates **retained**: `bookkeeping_export/accounting.py`
reconstructs exports independently in PostgreSQL acceptance tests;
`ledger_reporting.expenses_by_category` is a public reporting projection with
accounting regression coverage; `http/context.py:ContextResolver` is a public
resolver type contract. These are not obsolete merely because ordinary runtime
callers are absent. No supported public facade, test suite, fixture family,
dependency, deployment flag or executable script is removed in this slice.

## Validation and continuation

Local validation of this slice used the existing repository Python 3.12.10
development environment from the clean worktree root: **360 affected tests passed**
with no skips, including ledger/journal UI and reporting, recurrence retries,
local admin/Google/readiness boundaries, shared Sheets schema/current-format
backup validation, mileage/tags and two-profile isolation. Root
`python -m ruff check . --no-cache` passed. Changed runtime modules compiled,
all local Markdown file links in the seven changed guides resolved, and
`git diff --check` passed. No live providers, ledger data, database resources or
private configuration were used. Full local and hosted suites were not run;
publication/current-revision CI and review remain separate.

Run the affected ledger/search/journal, recurrence, local admin/Google/readiness,
Maps quota, mileage/tag and application-boundary checks from the repository root
using the development environment. Run root Python lint and `git diff --check`.
See [Development](DEVELOPMENT.md#required-validation) for scoped checks and
[CI ownership](CI_TEST_SUITES.md) for required independent layers. The unchanged
current-revision `Full test suite` remains the hosted merge gate; local affected
checks do not satisfy it. No local full-suite run is required for this slice.

Future slices must update the applicable inventory row and record its replacement
or retirement evidence, distinct test invariants, exact validation and deferred
owner/condition. Recheck linked issues and actual callers; this dated inventory
is not a permanent claim about deployed authority. #376 owns CI execution
optimization, #339 owns resource disposition, and #224/#298 retain release and
commercial-activation decisions. Completing this source cleanup does not close
those issues or assert that all legacy capabilities can be removed.
