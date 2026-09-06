# Setup

This guide creates a Google Sheets-backed business profile and prepares a
local or hosted deployment. Repeat the profile steps for each business.
Google Drive authorization is optional for ledger-only use; when receipts or
cloud backups are needed, follow [Google Drive](GOOGLE_DRIVE.md). Recovery
procedures belong in [Backup and recovery](BACKUP_RECOVERY.md).

## Prerequisites and configuration

Use Python 3.12 or newer, a supported Google account, and a Google Cloud
project for each Sheets service account. The application uses:

| File | Contents |
| --- | --- |
| .streamlit/secrets.toml | Application password hash and app-wide Drive OAuth/Picker configuration |
| .streamlit/business_profiles.json | Profile names, workbook IDs, Sheets credentials, Drive grants/folders, and local recovery metadata |

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
OAuth settings described in [Google Drive](GOOGLE_DRIVE.md) when that feature
is required. Start the application with:

```powershell
streamlit run tabula_rasa/app.py
```

## Create the Google Sheets profile

### Google Cloud and service account

1. Sign in to the [Google Cloud console](https://console.cloud.google.com/)
   and create or select a project dedicated to the business's Sheets
   integration.
2. Enable the Google Sheets API.
3. Under IAM & Admin > Service Accounts, create a recognizable service
   account. Do not grant project-wide Owner or Editor access.
4. Create and download a JSON key and record its client_email.
5. Treat the JSON as a password. Keep it in protected credential storage,
   outside the repository and ordinary download folders.

An organization policy may block service-account key creation. Ask the
administrator for the approved authentication path; do not weaken sharing or
make the workbook public.

### Blank workbook and required worksheets

1. Create a restricted folder and a blank spreadsheet for the business.
2. Share only the spreadsheet with the service account client_email as
   Editor. Copy the spreadsheet ID from the URL between /d/ and /edit.
3. Leave the workbook blank; the application creates or validates these tabs
   and headers:

| Worksheet | Required headers, left to right |
| --- | --- |
| Accounts | id, name, type, classification, opening_balance, active, created_at, parent_id |
| Categories | id, name, kind, parent_id |
| Payees | id, name, active, created_at |
| Tags | id, name, active, created_at |
| Transactions | id, txn_date, kind, amount, account_id, to_account_id, category_id, payee_id, description, reference, receipt_references, created_at, source_type, source_id, tag_ids |
| Mileage | id, trip_date, miles, vehicle, start_location, destination, business_purpose, notes, created_at, tag_ids |
| MixedUseExpenses | id, txn_date, kind, total_expense, business_use_percentage, allocated_amount, account_id, category_id, payee_id, description, reference, receipt_references, allocation_rationale, linked_transaction_id, tag_ids, created_at |

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

For a new profile, or a profile being changed to a different legacy workbook,
run the migration with the candidate workbook and a local service-account JSON
file before saving the profile:

```text
python scripts/migrate_workbook.py --spreadsheet-id WORKBOOK_ID --service-account-file path\to\service-account.json
```

Return to Account settings and validate/save the profile after the command
completes. The credential file is read locally; do not place it in the
repository.

See [Backup and recovery](BACKUP_RECOVERY.md) for migration behavior and
legacy-backup compatibility details.

Normal startup validates populated workbooks against the current headers only;
it never upgrades historical worksheet schemas or creates migration markers.
An outdated workbook fails with an actionable error and remains unchanged.
Upgrade a standard historical workbook explicitly, using the selected profile's
service-account access:

```text
python scripts/migrate_workbook.py --secrets .streamlit/secrets.toml --profile PROFILE_KEY
```

The migration command adds the hierarchy, receipt, managed-payee, tag,
provenance, and mixed-use columns, and backfills v9 mixed-use source tags from
their linked projection. It validates the complete current schema before
reporting success and can be rerun after an interrupted migration. Read-only
validation remains non-mutating and does not perform this conversion.

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

### Add a profile

1. Enter the business name and review the derived safe profile key. The key
   is editable before the first save and immutable afterward.
2. Enter the Google spreadsheet URL or ID.
3. Optionally enter an absolute local backup directory.
4. Upload the complete Sheets service-account JSON.
5. Select Validate and save.

Validation authenticates with the uploaded credential, opens the workbook,
checks or initializes required worksheets, and seeds defaults before storing
the profile. After saving, Profile readiness rereads the selected workbook and
configured Drive destinations, reports missing optional setup, and never
displays credentials, tokens, private ledger data, or receipt contents.

### Edit or rotate a profile

Edit local profile settings to change the business name, spreadsheet, or
optional local backup path without replacing the stored credential. Existing
Drive, storage-root, child-folder, Synology, and other profile settings remain
unless their dedicated controls change them.

Use Validate and rotate credential only for an intentional new service-account
key. A failed validation leaves the complete prior profile unchanged. Private
keys are never returned to the browser or displayed in the profile table.

All storage clients, workbook initialization, caches, prepared exports, and
duplicate-submission protection are scoped to the selected profile.

## Optional Google Drive, Maps, and recovery settings

For receipts and cloud-native backups, connect the selected profile to a human
Google account and provision its Drive storage root, Receipts child, and
Ledger Backups child. The Sheets service account and human Drive grant remain
separate. Follow [Google Drive](GOOGLE_DRIVE.md) for the complete OAuth and
Picker procedure.

Google address suggestions and automatic route mileage require paid,
app-wide Maps Platform configuration, two separately restricted API keys,
quotas, budget alerts, attribution, and deployment policy surfaces. Complete
the operator checklist in [Google Maps mileage setup](GOOGLE_MAPS.md) before
making a live request. Maps is not profile-scoped and must not reuse the Sheets
service account or Drive OAuth identity.

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
  Sheets service-account credential, and validated Drive authorization with its
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

Repeat the export after a profile, spreadsheet, Sheets credential, Drive grant,
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

### Service-account or workbook access failed

Confirm the spreadsheet ID, Sheets API, service-account project, and exact
Editor sharing address. Do not share the workbook publicly.

### Workbook initialization or structure validation failed

Confirm the service account has Editor access and the required tabs and
first-row headers match the table above. The application refuses to overwrite
populated incompatible worksheets.

### Service-account key creation is disabled

Consult the Google Workspace or Cloud administrator for the approved policy
exception or alternate deployment authentication.

### Hosted settings are stale

Regenerate and replace the complete hosted Secrets document after a
hosted-runtime field changes. Local readiness cannot verify hosted acceptance.

## Credential rotation

To rotate a Sheets key, create its replacement, validate and rotate it in
Account settings, export and replace hosted Secrets, confirm the deployed
application, then disable and delete the old key. To replace the application
password, run:

```powershell
python scripts\set_app_password.py
```

This changes the local hash only; it does not update a hosted deployment. After
the command succeeds, follow the [hosted Streamlit Secrets handoff](#hosted-streamlit-secrets)
to generate and replace the complete hosted Secrets document, save it, delete
the generated local file, and confirm that the deployed application accepts the
new password. If the hosted document is edited manually, replace only
`app_password_hash` with the new hash and never copy the plaintext password.

Keep any retained service-account JSON in protected storage outside the
repository. Never place credentials in backups, issues, logs, screenshots, or
documentation.

## References

- [Google Sheets API concepts](https://developers.google.com/workspace/sheets/api/guides/concepts)
- [Create and delete service-account keys](https://cloud.google.com/iam/docs/keys-create-delete)
- [Google Drive sharing permissions](https://support.google.com/drive/answer/2494822)
