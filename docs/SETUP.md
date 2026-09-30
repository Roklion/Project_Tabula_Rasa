# Setup

This guide creates a Google Sheets-backed business profile and prepares a
local or hosted deployment. Repeat the profile steps for each business.
Google OAuth authorization is required for every ledger. Drive folder setup
is optional for ledger-only use; for receipts or cloud backups, follow [Google Drive](GOOGLE_DRIVE.md). Recovery
procedures belong in [Backup and recovery](BACKUP_RECOVERY.md).

## Prerequisites and configuration

Use Python 3.12 or newer, a supported Google account, and a Google Cloud
shared project and OAuth client for the deployment. The application uses:

| File | Contents |
| --- | --- |
| .streamlit/secrets.toml | Application password hash and app-wide Drive OAuth/Picker configuration |
| .streamlit/business_profiles.json | Profile names, workbook IDs, Google OAuth grants/folders, and local recovery metadata |

Both files are ignored. The profile file is plaintext and must stay on a
protected, non-synchronized filesystem. Never commit, email, upload, log, or
paste either file's private values.

## Install and launch

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create the ignored application secrets file and set an application password:

```powershell
New-Item -ItemType Directory -Force .streamlit | Out-Null
New-Item -ItemType File -Force .streamlit\secrets.toml | Out-Null
python scripts\set_app_password.py
```

At minimum, the file contains an app-wide password hash. Add the shared Drive
OAuth settings described in [Google Drive](GOOGLE_DRIVE.md). Start the application with:

```powershell
streamlit run tabula_rasa/app.py
```

## Create the Google Sheets profile

### Shared Google Cloud / OAuth application

Use the existing shared OAuth project and web client; do not create a project
per business. Enable the Sheets, Drive, and Picker APIs. Configure the narrow
`drive.file` scope, registered local/hosted origins and redirect URIs, and the
restricted Picker key as described in [Google Drive](GOOGLE_DRIVE.md).

### Blank workbook and required worksheets

1. Create a restricted folder and a blank spreadsheet for the business.
2. Ensure the profile's human Google account has Editor access. Select the
   workbook through Picker in Account settings > Google setup.
3. Leave the workbook blank; the application creates or validates these tabs
   and headers:

| Worksheet | Required headers, left to right |
| --- | --- |
| Accounts | id, name, type, classification, opening_balance, active, created_at, parent_id |
| Categories | id, name, kind, parent_id |
| Payees | id, name, active, created_at |
| Tags | id, name, active, created_at |
| Transactions | id, txn_date, kind, amount, account_id, to_account_id, category_id, payee_id, description, reference, receipt_references, created_at, source_type, source_id, tag_ids, recurring_schedule_id, recurring_scheduled_date, recurring_source_kind, recurring_occurrence_type |
| Mileage | id, trip_date, miles, vehicle, start_location, destination, business_purpose, notes, created_at, tag_ids |
| MixedUseExpenses | id, txn_date, kind, total_expense, business_use_percentage, allocated_amount, account_id, category_id, payee_id, description, reference, receipt_references, allocation_rationale, linked_transaction_id, tag_ids, recurring_schedule_id, recurring_scheduled_date, recurring_source_kind, recurring_occurrence_type, created_at |
| RecurringSchedules | id, name, kind, source_kind, recurrence_unit, recurrence_interval, anchor_date, start_date, end_date, status, amount, total_expense, business_use_percentage, account_id, category_id, payee_id, description, reference, allocation_rationale, tag_ids, created_at, updated_at, attention_code, attention_at |
| Assets | id, name, asset_type, notes, acquisition_date, depreciation_start_date, cost_basis, salvage_value, useful_life_quarters, depreciation_method, depreciation_expense_account_id, accumulated_depreciation_account_id, payee_id, reference, tag_ids, source_transaction_id, retired_date, status, schedule_overrides, created_at, updated_at |
| JournalEntries | id, txn_date, description, created_at, updated_at |
| JournalPostings | id, parent_entry_id, position, target_type, target_id, side, amount, payee_id, description |

The default Sheet1 tab may remain or be deleted. Existing compatible tabs are
preserved. Blank-workbook initialization creates the required tabs and headers;
populated workbooks with empty or incompatible required tabs fail validation
rather than being overwritten. Defaults are seeded only in a blank workbook.

Existing workbooks that still store transaction payee text must be upgraded
with the one-time combined workbook migration before using the managed
`Payees` and `Transactions.payee_id` schema:

```text
python scripts/migrate_workbook.py --secrets .streamlit/secrets.toml --profile PROFILE_KEY
```

For a candidate historical workbook, connect a saved profile first, use
Google setup > Authorize a recovery or migration workbook, then run:

```text
python scripts/migrate_workbook.py --profile PROFILE_KEY --spreadsheet-id WORKBOOK_ID
```

Return to Google setup, select the migrated workbook as the ledger, and
validate it. Merely pasting a workbook ID does not grant `drive.file` access.

See [Backup and recovery](BACKUP_RECOVERY.md) for migration behavior and
legacy-backup compatibility details.

Normal startup validates populated workbooks against the current headers only;
it never upgrades historical worksheet schemas or creates migration markers.
An outdated workbook fails with an actionable error and remains unchanged.
Upgrade a standard historical workbook explicitly, using the selected profile's
Google OAuth access:

```text
python scripts/migrate_workbook.py --secrets .streamlit/secrets.toml --profile PROFILE_KEY
```

The migration command adds the hierarchy, receipt, managed-payee, tag,
provenance, mixed-use, recurring, fixed-asset, and journal tables and columns,
and backfills v9 mixed-use source tags from their linked projection. When it
recognizes a format-12 workbook, it adds empty `JournalEntries` and
`JournalPostings` tables without rewriting simple transaction rows. It validates
the complete format-13 schema before reporting success and can be rerun after
an interrupted migration. Read-only validation remains non-mutating and does
not perform this conversion.

If the historical Drive receipt files predate workbook receipt references, run
the separate one-time association migration after the workbook migration:

```text
python scripts/migrate_receipt_associations.py --secrets .streamlit/secrets.toml --profile PROFILE_KEY
```

Normal startup and backup creation never infer associations from legacy Drive
metadata. The receipt migration considers only blank legacy cells and leaves an
explicit empty receipt list unlinked.

## Local profile administration

The authenticated Account settings route can create and edit the local
profile file only when both conditions hold:

- TABULA_LOCAL_PROFILE_ADMIN=1 is set for the server process; and
- Streamlit is bound to localhost, 127.0.0.1, or another loopback address.

Use the launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_profile_admin.ps1
```

The launcher sets the flag only for its process and binds Streamlit to the
loopback interface. In Account settings, re-enter the application password
before configuration changes.

### Add or edit a profile

1. Enter the business name, review its safe immutable profile key, and optionally
   set an absolute local backup directory. Select Save profile.
2. Open Google setup for that profile and Connect Google. Authorize the human
   account that can edit the ledger. One account may serve several profiles;
   each profile stores its own grant and resource selections.
3. Choose the existing ledger with Google Picker. The app confirms Google Sheets
   access and Editor capability before saving the ID. Selection does not create
   a workbook or alter its rows.
4. Select Validate ledger. Genuinely blank workbooks receive the existing schema
   and defaults; populated historical workbooks require explicit migration.
5. For receipts/backups, choose or create a storage root and Provision storage
   folders. Run readiness under Recovery.

Ordinary edits change only the name and local backup path. Change the ledger
through Google setup; reconnect there to replace OAuth authorization. Failed
ledger selection preserves the previous ID. Tokens and private ledger contents
are never displayed by setup. Disconnect removes only the selected profile's
local authorization; it disables both Sheets and Drive for that profile. It does
not revoke the shared account's Google application grant or delete files.

All storage clients, workbook initialization, caches, prepared exports, and
duplicate-submission protection are scoped to the selected profile.

## Optional Google Drive, Maps, and recovery settings

For receipts and cloud-native backups, connect the selected profile to a human
Google account and provision its Drive storage root, Receipts child, and
Ledger Backups child. Sheets and Drive use the same profile OAuth grant. Follow [Google Drive](GOOGLE_DRIVE.md) for the complete OAuth and
Picker procedure.

Google address suggestions and automatic route mileage require paid,
app-wide Maps Platform configuration, two separately restricted API keys,
quotas, budget alerts, attribution, and deployment policy surfaces. Complete
the operator checklist in [Google Maps mileage setup](GOOGLE_MAPS.md) before
making a live request. Maps is not profile-scoped and must not reuse the Sheets
profile Google OAuth identity.

For an optional Synology recovery copy, Account settings records a profile-root
Cloud Sync destination, schedule, and retention policy. The application does
not configure or monitor DSM. Follow the [backup and recovery
guide](BACKUP_RECOVERY.md) for the required download-only task and validation.

## Hosted Streamlit Secrets

Local development uses split app and profile files. Hosted Streamlit uses one
combined Secrets document containing:

- app-wide `app_password_hash`, shared `google_drive_oauth`, and optional
  `google_maps` configuration; and
- one `business_profiles` entry per profile containing its name, spreadsheet ID,
  validated Google OAuth authorization with its
  storage root and Receipts and Ledger Backups children.

Local backup paths, Synology metadata, and unknown local-only fields are
excluded. In Account settings > Security & deployment information, choose
Generate hosted Secrets file after all hosted fields are ready. The application
reloads and validates the local profiles, writes a new randomly named ignored
TOML file without overwriting an existing file, and displays only its path.
It never displays or logs credentials.

The command-line equivalent is:

```powershell
python scripts\export_streamlit_secrets.py
```

Paste the complete generated document into Streamlit App settings > Secrets,
save it, delete the generated local file, and confirm the deployed application.
The local administrator cannot inspect the hosted Secrets store or claim that
Streamlit accepted the replacement.

Repeat the export after a profile, spreadsheet, Google OAuth grant,
storage root, receipt folder, backup folder, or Drive connection changes.
Changes only to a local backup path, Synology destination, schedule, retention
policy, or app-wide Synology defaults do not require a hosted export.

## Validate readiness

Validate one configured workbook, its headers, and managed Payees records
without displaying ledger rows:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY
```

For a reversible permission test on a disposable worksheet:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --write-test
```

The write test creates, reads, updates, and deletes only that disposable
worksheet. For a recovery workbook, use a read-only spreadsheet override:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --spreadsheet-id RECOVERY_WORKBOOK_ID
```

The override cannot be combined with `--write-test`. After validation, start the
application, sign in, select the business, and confirm its workbook title.

## Troubleshooting

### Google OAuth or workbook access failed

Reconnect the selected profile's Google account. Confirm Sheets API is enabled
in the shared OAuth project, Editor access to the workbook, and explicit Picker
selection. Do not make the workbook public. Confirm required tabs and headers;
the app refuses to overwrite populated incompatible worksheets.

### Hosted settings are stale

Regenerate and replace the complete hosted Secrets document after a
hosted-runtime field changes. Local readiness cannot verify hosted acceptance.

## Credential rotation

Reconnect Google locally to replace a grant, then export and replace hosted
Secrets and validate the deployed profile. To replace the application password:

```powershell
python scripts\set_app_password.py
```

This changes the local hash only; it does not update a hosted deployment. After
the command succeeds, follow the [hosted Streamlit Secrets handoff](#hosted-streamlit-secrets)
to generate and replace the complete hosted Secrets document, save it, delete
the generated local file, and confirm that the deployed application accepts the
new password. If the hosted document is edited manually, replace only
`app_password_hash` with the new hash and never copy the plaintext password.

Keep OAuth configuration and refresh tokens in protected storage. Never place credentials in backups, issues, logs, screenshots, or
documentation.

## References

- [Google Sheets API concepts](https://developers.google.com/workspace/sheets/api/guides/concepts)
- [Google Sheets authorization scopes](https://developers.google.com/workspace/sheets/api/scopes)
- [Google Drive sharing permissions](https://support.google.com/drive/answer/2494822)

## Existing deployment: single-step OAuth cutover

There is no ledger data/schema migration for this authentication change. Normal
runtime accepts only version 2 local profiles and OAuth-only hosted profiles.
Follow [the migration runbook](OAUTH_MIGRATION.md) for preparation, downtime,
coordinated code/Secrets replacement, validation, and key retirement.

### Initial ledger provision

In Account settings > Google setup, a connected profile with no ledger can use
Create ledger spreadsheet instead of selecting an existing file. The app creates
`Business name Ledger` in that Google account's My Drive, saves its ID, and
initializes the existing required worksheets and default accounts/categories.
This does not require a separate Picker grant because the app creates the file.
The action is hidden once a ledger is configured and never replaces an existing
ledger. Drive receipt/backup folders are still configured in the same setup tab.

If creation or initialization is uncertain, no file is deleted or blindly
recreated. Inspect Drive and select the created file through Picker; if its ID
was saved, use Validate ledger to finish supported blank-workbook initialization.
