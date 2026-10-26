# Setup

Bookkeeping uses the [browser/API runtime](browser/RUNTIME.md) and PostgreSQL.
Create new businesses in the application; native bootstrap creates the ledger.
[Deployment](operations/DEPLOYMENT.md) owns server setup. This guide covers the
retained local operator interface for Google grants, folders, source/recovery
workbooks and protected local configuration. It does not create PostgreSQL entities
or provide customer self-service Google consent.

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
powershell -ExecutionPolicy Bypass -File scripts/run_local_profile_admin.ps1
```

## Configure a source or recovery profile

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

The exact worksheet/header contract is centralized in
[Final Sheets source contract](SHEETS_SOURCE_CONTRACT.md). The default Sheet1
tab may remain. A genuinely empty workbook, or interrupted bootstrap containing
only current headers and no records, receives format-13 tabs and headers.
Populated workbooks are validated without modification; missing, historical,
or additional ledger fields are rejected. Select a supported format-13 workbook
or restore a validated format-13 backup into a new blank workbook. Historical
ledger and archive converters are retired; preserve unsupported source files.

Earlier profile and receipt-association preparation converters are retired. Use only
current local configuration and explicit format-13 receipt relationships. No startup,
backup or migration path infers associations from old Drive metadata. Preserve
unsupported sources and use a validated format-13 generation for recovery.


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
   a workbook or alter its rows. Each ledger may belong to only one local
   business profile; selecting another profile's ledger is rejected.
4. Select Validate ledger. Genuinely blank workbooks receive the existing schema
   and defaults; populated workbooks must match the frozen format-13 contract.
5. For receipts/backups, choose or create a storage root and Provision storage
   folders. Run readiness under Recovery.

Ordinary edits change only the name and local backup path. Change the ledger
through Google setup; reconnect there to replace OAuth authorization. Failed
ledger selection preserves the previous ID. Tokens and private ledger contents
are never displayed by setup. Disconnect removes only the selected profile's
local authorization; it disables both Sheets and Drive for that profile. It does
not revoke the shared account's Google application grant or delete files.

All operator storage clients, workbook initialization, caches and recovery settings
are scoped to the selected profile. Opening administration does not initialize any
workbook or run recurring generation.

## Optional Google Drive, Maps, and recovery settings

For receipts and cloud-native backups, connect the selected profile to a human Google
account and provision its Drive storage root, Receipts child, and ledger Backups child.
Sheets and Drive use the same profile OAuth grant. Follow [Google
Drive](GOOGLE_DRIVE.md) for the complete OAuth and Picker procedure.

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

## Commercial deployment configuration

Streamlit Cloud Secrets generation and export are retired. Local administration
continues to use the protected split app/profile files. Local changes do not
configure the React/FastAPI deployment. Use [external connections and claims](identity/CONNECTIONS_AND_CLAIMS.md)
for approved encrypted grant staging and Owner activation, and [deployment](operations/DEPLOYMENT.md)
for server configuration. Never paste provider grants into a browser form or
bookkeeping export.

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

The override cannot be combined with `--write-test`. Confirm the intended profile
and workbook privately before any recovery mutation.

## Troubleshooting

### Google OAuth or workbook access failed

Reconnect the selected profile's Google account. Confirm Sheets API is enabled
in the shared OAuth project, Editor access to the workbook, and explicit Picker
selection. Do not make the workbook public. Confirm required tabs and headers;
the app refuses to overwrite populated incompatible worksheets.

## Credential rotation

Reconnect Google locally to replace a local grant and validate the selected profile.
For a commercial connection, follow the separate approved encrypted staging and
Owner activation procedure in [connections](identity/CONNECTIONS_AND_CLAIMS.md). To replace the application password:

```powershell
python scripts\set_app_password.py
```

This changes the local application password only. Commercial named login and
provider secrets use separate custody; local password rotation does not update
them or grant business access.

Keep OAuth configuration and refresh tokens in protected storage. Never place credentials in backups, issues, logs, screenshots, or
documentation.

## References

- [Google Sheets API concepts](https://developers.google.com/workspace/sheets/api/guides/concepts)
- [Google Sheets authorization scopes](https://developers.google.com/workspace/sheets/api/scopes)
- [Google Drive sharing permissions](https://support.google.com/drive/answer/2494822)

## Existing deployment configuration

Runtime accepts only version-2 local profiles. Older profile conversion is retired;
use [Google authorization and configuration recovery](OAUTH_MIGRATION.md) for current
setup and preservation guidance. Commercial connection staging remains separate.


### Initial recovery workbook provision

In Account settings > Google setup, a connected profile with no ledger can use
Create ledger spreadsheet instead of selecting an existing file for an approved
source/recovery operation. New PostgreSQL businesses use in-app creation. The app creates
`Business name Ledger` in that Google account's My Drive, saves its ID, and
initializes the existing required worksheets and default accounts/categories.
This does not require a separate Picker grant because the app creates the file.
The action is hidden once a ledger is configured and never replaces an existing
ledger. Drive receipt/backup folders are still configured in the same setup tab.

If creation or initialization is uncertain, no file is deleted or blindly
recreated. Inspect Drive and select the created file through Picker; if its ID
was saved, use Validate ledger to finish supported blank-workbook initialization.
