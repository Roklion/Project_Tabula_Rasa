# Business profile setup

Each business profile isolates a Google Sheets ledger, service-account
credential, optional Google Drive authorization, backup destinations, and
runtime caches. Repeat this guide for every business.

A business may use a Google Cloud project and Google account different from
every other profile. The application's current password grants access to all
configured profiles; use separate deployments or add profile-level
authorization when different users must see different businesses.

## Configuration boundaries

Local configuration is split deliberately:

| File | Contents |
| --- | --- |
| `.streamlit/secrets.toml` | Application password hash and app-wide Google Drive OAuth/Picker configuration |
| `.streamlit/business_profiles.json` | Business names, spreadsheet IDs, service-account credentials, per-profile Drive tokens and folders, and recovery metadata |

Both files are ignored. The profile JSON is plaintext and inherits permissions
from the project directory. Never commit, email, upload, or synchronize either
file.

## 1. Create or select a Google Cloud project

1. Sign in to the [Google Cloud console](https://console.cloud.google.com/)
   with the account that will administer the business's Sheets integration.
2. Create a new project or select an existing project dedicated to this
   business. Record its project ID.
3. Open **APIs & Services > Library** and enable the **Google Sheets API**.

The Sheets API must be enabled in the project that owns the service account,
even when the spreadsheet belongs to another Google account.

## 2. Create the Sheets service account

1. Open **IAM & Admin > Service Accounts** in the selected project.
2. Select **Create service account** and use a recognizable name such as
   `tabula-rasa-example-business`.
3. Do not grant project-wide Owner or Editor access. The application receives
   access by sharing one spreadsheet with the service account, so no Google
   Cloud project role is required for normal operation.
4. Open the new service account and select
   **Keys > Add key > Create new key > JSON**.
5. Download the JSON and record its `client_email`.

Treat the JSON like a password. Never:

- email it;
- upload it to Google Drive;
- commit it to Git;
- paste it into an issue, log, or documentation; or
- keep it in an unprotected download folder.

A Google Workspace organization may prohibit service-account JSON key creation.
An administrator must approve the relevant organization-policy exception or a
different deployment authentication method will be required.

## 3. Create and organize the ledger workbook

1. Sign in to the Google account that should own the business records.
2. Create a restricted folder such as `Tabula Rosa - Example Business`.
3. Inside it, create a blank spreadsheet with a clear business-specific name.
4. Keep **General access** set to **Restricted**.
5. Share only the spreadsheet with the service account's `client_email` as
   **Editor**. Clear **Notify people** if Google offers that option.
6. Copy the spreadsheet ID from the value between `/d/` and `/edit`:

   ```text
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
   ```

Sharing only the spreadsheet is the least-privilege choice. Sharing the
containing folder is optional and grants broader inherited access.

Leave the workbook blank. When the profile is validated and saved, Tabula Rosa
creates or validates the required worksheets and first-row headers:

| Worksheet | Row 1 headers, from left to right |
| --- | --- |
| `Accounts` | `id`, `name`, `type`, `classification`, `opening_balance`, `active`, `created_at`, `parent_id` |
| `Categories` | `id`, `name`, `kind`, `parent_id` |
| `Transactions` | `id`, `txn_date`, `kind`, `amount`, `account_id`, `to_account_id`, `category_id`, `payee`, `description`, `reference`, `receipt_references`, `created_at` |
| `Mileage` | `id`, `trip_date`, `miles`, `vehicle`, `start_location`, `destination`, `business_purpose`, `notes`, `created_at` |

The default `Sheet1` tab may remain or be deleted. Existing compatible ledger
tabs are preserved. Empty required tabs receive their headers. Populated tabs
with incompatible headers cause validation to fail rather than being
overwritten. Initial accounts and categories are seeded while the profile is
saved.

On normal application startup, an existing workbook with the exact legacy
format-version 5 Accounts and Categories headers is migrated in place by
appending a blank `parent_id` column to each worksheet. Existing rows remain
Layer 1 records. The read-only validation command accepts those legacy headers
before startup without modifying the workbook.

If the business uses a Google Workspace Shared Drive, confirm its administrator
permits the external service-account address and grant only the minimum role
needed. Files in a Shared Drive are owned by the organization; files in My Drive
are owned by the account that created them.

## 4. Configure the application password

Create the ignored application secrets file if it does not exist:

```powershell
New-Item -ItemType Directory -Force .streamlit | Out-Null
New-Item -ItemType File -Force .streamlit\secrets.toml | Out-Null
python scripts\set_app_password.py
```

At minimum, `.streamlit/secrets.toml` contains:

```toml
app_password_hash = "scrypt$..."
```

Google Drive OAuth configuration is app-wide and belongs in this same file.
Follow [Google Drive OAuth and per-business access](../architecture/GOOGLE_DRIVE_OAUTH.md)
when receipts or cloud backups are required.

## 5. Start the loopback-only profile administrator

The authenticated **Business profiles** page can add or replace profiles in
`.streamlit/business_profiles.json`. It fails closed and is not available
unless:

- `TABULA_LOCAL_PROFILE_ADMIN=1` is set for the server process; and
- Streamlit is bound to `localhost`, `127.0.0.1`, or another loopback address.

Use the provided launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_profile_admin.ps1
```

The launcher sets the flag only for its process and binds Streamlit to the
loopback interface. If it reports that `.venv` is not runnable, recreate the
ignored virtual environment using the root README's installation commands.

## 6. Add or replace the profile

1. Sign in to Tabula Rosa normally.
2. Open **Business profiles** and re-enter the application password.
3. Enter the business name and a safe profile key.
4. Enter the Google spreadsheet URL or ID.
5. Enter an absolute local backup directory when local scheduled backups are
   needed.
6. Upload the complete service-account JSON.
7. Confirm replacement only when intentionally replacing an existing key.
8. Select **Validate and save**.

Validation authenticates with the uploaded credential, opens the workbook,
checks or initializes its required worksheets, and seeds defaults before
storing the profile.

The private key is never displayed or written to Google Sheets. It exists
briefly in browser/server memory and is then stored in the local ignored profile
JSON. The loopback-only launcher controls editing, not reading; normal app and
backup processes read the file after it has been created.

After signing into the normal application, select the active business in the
sidebar. Storage clients, workbook initialization, caches, and duplicate
submission protection are isolated by profile.

## 7. Connect optional Google Drive storage

If the profile needs receipts or cloud-native backups, follow
[Google Drive OAuth and per-business access](../architecture/GOOGLE_DRIVE_OAUTH.md).
The Drive-owning human Google account may differ from both:

- the account that administers the Sheets service-account project; and
- the account that owns the ledger spreadsheet.

The service account does not receive access to receipt or backup folders unless
someone separately shares them, which is not required.

## 8. Export profiles to Streamlit Community Cloud

Local development uses split files, while the hosted app expects one combined
Streamlit Secrets document. Generate it with:

```powershell
python scripts\export_streamlit_secrets.py
```

The command:

- validates the app secrets and every local profile;
- creates a randomly named ignored TOML file under `.streamlit/`;
- never prints credential values;
- never overwrites an existing output; and
- excludes `.streamlit/config.toml`.

Paste the complete generated document into
**Streamlit App settings > Secrets**, save it, and immediately delete the
generated local file.

Repeat the export after any:

- profile addition or replacement;
- Sheets credential rotation;
- Google Drive connection or reconnection;
- receipt or backup folder change;
- Google Drive disconnection; or
- Synology recovery metadata change.

Streamlit Community Cloud cannot safely write those changes back to its Secrets.

## 9. Validate each profile

Verify service-account authentication, workbook access, and worksheet headers
without displaying ledger rows:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY
```

Run the reversible permission test:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --write-test
```

It creates, reads, updates, and deletes a disposable worksheet without modifying
ledger rows.

After both commands pass:

1. start or redeploy the application;
2. sign in;
3. select the new business in the sidebar; and
4. confirm its workbook title is displayed.

Repeat this validation for every configured profile.

For a recovery workbook, use the read-only override without changing the
configured profile:

```powershell
python scripts\validate_google_sheets.py --profile PROFILE_KEY --spreadsheet-id RECOVERY_WORKBOOK_ID
```

The override reports sanitized row counts for all required worksheets and
cannot be combined with `--write-test`.

## Troubleshooting

### Service-account authentication failed

The uploaded key may be malformed, disabled, revoked, or deleted. Create a
replacement key, replace the profile locally, validate it, and export hosted
Secrets again.

### Workbook access failed

Confirm:

- the spreadsheet ID is correct;
- the Sheets API is enabled in the service account's project; and
- the spreadsheet is shared with that profile's exact `client_email`.

### Workbook initialization failed

Confirm the service account has Editor access and that the required worksheets
or header cells are not protected.

### Workbook structure validation failed

Correct the named worksheet and first-row headers exactly as listed in this
guide. The application refuses to overwrite populated incompatible worksheets.

### Organization policy blocks sharing

A Google Workspace administrator may need to permit sharing with the
service-account address. Do not make the spreadsheet public as a workaround.

### Service-account key creation is disabled

Consult the Workspace or Cloud administrator. Newer organizations may enforce
this restriction by default.

## Credential rotation

To rotate a Sheets service-account credential:

1. create the replacement key;
2. replace the profile through the local administrator;
3. validate read and reversible write access;
4. export and replace hosted Secrets;
5. confirm the hosted application; and
6. disable and delete the old key.

To replace a forgotten application password, run:

```powershell
python scripts\set_app_password.py
```

Then export or manually copy the new hash to hosted Secrets.

The original service-account JSON file is not required after local and hosted
configuration are complete. If retained for disaster recovery, keep it in
protected credential storage outside the repository.

## References

- [Google Sheets API overview](https://developers.google.com/workspace/sheets/api/guides/concepts)
- [Create and delete service-account keys](https://cloud.google.com/iam/docs/keys-create-delete)
- [Google Drive sharing permissions](https://support.google.com/drive/answer/2494822)
