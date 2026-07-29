# Tabula Rosa

A private Google Sheets-backed bookkeeping app for one person or a small group of businesses. Each business can use its own spreadsheet and Google service account while sharing one Streamlit deployment.

## Run it

1. Install Python 3.11 or newer.
2. Create the virtual environment and install the application dependencies:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Create the ignored local secrets file and set the application password:

   ```powershell
   New-Item -ItemType Directory -Force .streamlit | Out-Null
   New-Item -ItemType File -Force .streamlit\secrets.toml | Out-Null
   python scripts\set_app_password.py
   ```

   The script stores only a password hash. Keep application-level secrets in
   `.streamlit/secrets.toml`; business settings and per-profile credentials
   live in `.streamlit/business_profiles.json`.
4. Follow **Multiple business profiles** to add the first profile. If receipts
   or cloud backups are needed, also complete **Google Drive OAuth for receipts
   and cloud backups** before exporting the hosted secrets.
5. Start the normal app:

   ```powershell
   streamlit run tabula_rasa/app.py
   ```

The app reads and writes the private Google workbook through its narrowly scoped service account. It does not use a local SQLite database as its active datastore.

## Repository layout

- `tabula_rasa/` contains the Streamlit entry point and application modules.
- `scripts/` contains setup, validation, backup, and recovery utilities.
- `tests/` contains the automated test suite and UI workflow scenarios.

## Multiple business profiles

Repeat the following setup for every business. A business may use a Google Cloud
project and Google Drive owned by a different Google account from the other
profiles.

### 1. Create or select a Google Cloud project

1. Sign in to the [Google Cloud console](https://console.cloud.google.com/)
   with the Google account that will administer this business's integration.
2. Create a new project, or select an existing project dedicated to this
   business. Record its project ID.
3. Open **APIs & Services > Library** and enable the **Google Sheets API**. The
   API must be enabled in the project that owns the service account, even when
   the spreadsheet belongs to another Google account. See Google's
   [Sheets API overview](https://developers.google.com/workspace/sheets/api/guides/concepts).

### 2. Create the service account and JSON key

1. In the selected Cloud project, open **IAM & Admin > Service Accounts**.
2. Click **Create service account**. Use a recognizable name such as
   `tabula-rasa-heathcote`, then click **Create and continue**.
3. Do not grant project-wide Owner or Editor access. This app gets access by
   sharing one specific spreadsheet with the service account, so no Google
   Cloud project role is required for its normal use. Finish creating the
   account.
4. Open the new service account, select **Keys > Add key > Create new key**,
   choose **JSON**, and download the file. Google documents the current process
   under [Create and delete service-account keys](https://cloud.google.com/iam/docs/keys-create-delete).
5. Record the `client_email` from the downloaded JSON. You will share the
   spreadsheet with this address and copy the complete JSON values into
   Streamlit secrets.

Treat the JSON file like a password: never email it, upload it to Drive, commit
it to Git, or paste it into an issue or log. It is ignored by this repository,
but should still be moved to protected credential storage or securely deleted
after local and hosted secrets have been configured. A Workspace organization
may prohibit JSON key creation; in that case an administrator must approve the
organization-policy exception or a different deployment authentication method
will be needed.

### 3. Create and organize the spreadsheet in Drive

1. Sign in to the Google account that should own the business records.
2. In Google Drive, create a restricted folder for the business, for example
   `Tabula Rasa - Heathcote`. Do not enable **Anyone with the link**.
3. Inside that folder, create a blank Google spreadsheet and give it a clear
   name such as `Heathcote Advisory Ledger`.
4. Leave the spreadsheet blank. When the business profile is validated and
   saved, the app uses the supplied spreadsheet ID to create these four
   worksheet tabs and first-row headers automatically:

   | Worksheet | Row 1 headers, from left to right |
   | --- | --- |
   | `Accounts` | `id`, `name`, `type`, `classification`, `opening_balance`, `active`, `created_at` |
   | `Categories` | `id`, `name`, `kind` |
   | `Transactions` | `id`, `txn_date`, `kind`, `amount`, `account_id`, `to_account_id`, `category_id`, `payee`, `description`, `reference`, `created_at` |
   | `Mileage` | `id`, `trip_date`, `miles`, `vehicle`, `start_location`, `destination`, `business_purpose`, `notes`, `created_at` |

   The default `Sheet1` tab may be left in place or deleted. Existing compatible
   ledger tabs are preserved, empty required tabs receive their headers, and
   populated tabs with incompatible headers cause validation to fail instead of
   being overwritten. The app also seeds its initial accounts and categories
   while saving the profile.
5. Share the spreadsheet with the service account's `client_email`, select
   **Editor**, clear **Notify people** if Google offers it, and click **Share**.
   Keep **General access** set to **Restricted**. Google's
   [Drive sharing guide](https://support.google.com/drive/answer/2494822)
   describes these permission levels.
6. Copy the spreadsheet ID from its URL. It is the value between `/d/` and
   `/edit`:

   ```text
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
   ```

Sharing the containing folder with the service account is optional and grants
broader inherited access. Sharing only the spreadsheet is the least-privilege
choice. If the business uses Google Workspace Shared Drives, confirm that its
administrator permits the external service-account address and grant only the
minimum role needed. Files in a Shared Drive are owned by the organization,
whereas a spreadsheet in personal My Drive remains owned by the Google account
that created it.

### 4. Add the profile to the business profiles JSON

Use the authenticated **Business profiles** page described below. It writes
each business's spreadsheet, Drive locations, and complete service-account
credential together in the ignored `.streamlit/business_profiles.json`.
`.streamlit/secrets.toml` should contain only application-level secrets.
At minimum it contains:

```toml
app_password_hash = "scrypt$..."
```

Share each spreadsheet as Editor with the `client_email` from that same
profile. The Google Cloud projects and owning Google accounts may be different;
each profile authenticates independently. After signing in, choose the active
business in the sidebar. Storage clients, default initialization, and duplicate
submission protection are isolated by profile.

The application password currently grants access to every configured profile.
Use separate deployments or add profile-level authorization if different users
must only see particular businesses.

### 5. Business profile onboarding UI

For local deployments, an authenticated **Business profiles** page can add or
replace profiles in the ignored `.streamlit/business_profiles.json` file. The
page is fail-closed and is
not present unless the server process has exactly the following flag **and**
Streamlit is bound to `localhost`, `127.0.0.1`, or another loopback address:

```text
TABULA_LOCAL_PROFILE_ADMIN=1
```

Use the provided launcher, which enables the flag only for that process and
binds Streamlit to the loopback interface:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_profile_admin.ps1
```

If the launcher reports that `.venv` is not runnable, remove and recreate that
ignored virtual environment using the installation commands under **Run it**.

Then:

1. Sign in to Tabula Rosa normally.
2. Open **Business profiles** and re-enter the application password.
3. Enter a business name, safe profile key, Google spreadsheet URL or ID, and
   the absolute Google Drive Desktop backup folder path.
4. Upload the complete service-account JSON downloaded from Google Cloud.
5. Confirm replacement only when intentionally overriding an existing key.
6. Select **Validate and save**. Validation opens the workbook and initializes
   the required worksheets before the credential is stored locally.

The uploaded private key is never displayed, written to Google Sheets, or put
in the ledger. It exists briefly in browser/server memory and is then stored in
the ignored local JSON profile file so the app can authenticate after a
restart. The file is plaintext and inherits access controls from the project
directory. Do not put the project on a shared or automatically synchronized
folder, and ensure other operating-system users cannot read it.

The profile file is read during normal app and backup-script execution. The
loopback-only launcher controls editing, not reading. Never commit, email, or
synchronize this plaintext credential file.

## Google Drive OAuth for receipts and cloud backups

Google Sheets continues to use each profile's service account. Google Drive
uses one separate, app-wide OAuth client plus a human Google authorization for
each business profile. The refresh token and selected folders are stored under
the corresponding profile; they are never written to the ledger workbook or
displayed after authorization.

### 1. Configure the app-wide Google Cloud project

Use a separate Cloud project such as `tabula-rosa-oauth-client`, rather than a
project dedicated to one business's Sheets service account.

1. Enable the **Google Drive API** and **Google Picker API**.
2. Open **Google Auth Platform** and configure Branding.
3. Choose **External** audience when profiles may use personal accounts or
   accounts outside one Workspace organization.
4. During initial Testing, add each human Drive-owning Google account as a test
   user. Do not add service-account `client_email` addresses.
5. Under **Data Access**, add only:

   ```text
   https://www.googleapis.com/auth/drive.file
   ```

6. Create a **Web application** OAuth client. Add these JavaScript origins:

   ```text
   http://localhost:8501
   http://127.0.0.1:8501
   https://tabula-rasa.streamlit.app
   ```

7. Add the matching exact redirect URIs:

   ```text
   http://localhost:8501/
   http://127.0.0.1:8501/
   https://tabula-rasa.streamlit.app/
   ```

8. Create an API key for Google Picker. Restrict it to the Google Picker API
   and to the three HTTP referrers above, using `/*` after each origin.
9. Record the OAuth client ID, client secret, API key, and numeric Cloud project
   number. The project number is under **IAM & Admin > Settings** and is not the
   project ID.
10. Before production use, open **Audience**, publish the app, and confirm its
    publishing status is **In production**. Test-user allowlisting no longer
    controls access in this state, although Google Workspace administrators can
    still restrict third-party applications.

Testing-mode Drive grants, including offline refresh tokens, expire after seven
days. Google documents the distinction under
[Manage App Audience](https://support.google.com/cloud/answer/15549945).
After moving an existing OAuth project from Testing to In production, reconnect
each business profile once and export the hosted secrets again. This replaces
any refresh token originally issued under the expiring Testing configuration.
The narrow `drive.file` scope avoids broad access to the user's Drive; Google
Picker explicitly authorizes the selected folders.

### 2. Add the app-wide OAuth secrets locally

Add the following to the ignored `.streamlit/secrets.toml`:

```toml
app_password_hash = "scrypt$..."

[google_drive_oauth]
client_id = "CLIENT_ID.apps.googleusercontent.com"
client_secret = "CLIENT_SECRET"
redirect_uris = [
  "http://localhost:8501/",
  "http://127.0.0.1:8501/",
  "https://tabula-rasa.streamlit.app/",
]
picker_api_key = "PICKER_API_KEY"
project_number = "NUMERIC_CLOUD_PROJECT_NUMBER"
```

Never commit this file or paste its values into issues, logs, screenshots, or
the business-profile service-account JSON.

### 3. Connect every business profile

Run the loopback-only profile administration launcher:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_profile_admin.ps1
```

Then:

1. Sign in to Tabula Rosa and open **Business profiles**.
2. Re-enter the application password.
3. Under **Google Drive OAuth**, choose a local business profile.
4. Select **Connect Google Drive**.
5. Sign in with the human Google account that should own that business's Drive
   files and approve access.
6. Back in Tabula Rosa, use Google Picker to select the profile's receipt
   folder and backup folder.
7. Repeat for every profile. Profiles may authorize different Google accounts
   while sharing the same OAuth client.
8. Run `python scripts/export_streamlit_secrets.py` again and replace the
   hosted Streamlit Secrets document so the hosted app receives the new
   per-profile refresh tokens and folder IDs.

After a profile has a Google Drive backup folder, its **Synology recovery copy**
option can be enabled independently from the same local administration page.
The setting records only the expected NAS destination, Cloud Sync schedule, and
retention policy. It does not mount or connect to the NAS. Businesses that leave
the option disabled continue to use Google Drive backup without a NAS copy.
DSM must still be configured separately: the option is an operational record
shown in the app, not a control channel or proof that synchronization succeeded.

The receipt and backup folders can remain **Restricted** in Google Drive. They
do not need to be shared with the Sheets service account or with the Google
accounts used by other business profiles. Access comes from the human account
authorized for that profile and the folders explicitly selected with Picker.

Receipt and backup uploads currently support regular Google Drive folders owned
by the Google account authorized for that business profile. Organization-owned
Google Workspace Shared Drive folders are not a supported mode in this release.
Treat them as a separate future feature that needs its own Picker behavior,
permission model, ownership expectations, and end-to-end tests before relying
on it for business records.

Because Streamlit Community Cloud cannot safely write back to its Secrets,
connections, reconnections, folder changes, and disconnections are performed
locally and then exported. A revoked grant produces a reconnect message without
affecting the profile's Google Sheets service account.

Once a receipt folder is selected, open a saved transaction under
**Transactions > View & edit ledger > Receipt** to upload a PDF or image. Files
are named `[transaction-id]-[original-file-name]` and tagged with private
app-properties so retries update the same receipt rather than creating an
unintended duplicate. Each transaction stores the receipt's stable Drive file
ID and display name. Removing a receipt from a transaction only removes that
reference; the underlying file remains in Google Drive.

### Export profiles to Streamlit Community Cloud

Generate a temporary TOML document containing the app-level secrets and every
business profile:

```powershell
python scripts/export_streamlit_secrets.py
```

The command prints the path to a randomly named, ignored file under
`.streamlit/`. Paste its complete contents into
**Streamlit App settings > Secrets**, save, then delete the generated file
immediately. The command never prints credential values, never overwrites an
existing output, and does not include
`.streamlit/config.toml` because server configuration is not part of Streamlit
Secrets.

### Validate each business profile

Verify read access and the worksheet headers without displaying ledger rows:

```powershell
python scripts/validate_google_sheets.py --profile heathcote
```

Then run the reversible permission test. It creates, reads, updates, and
deletes a disposable worksheet without modifying ledger rows:

```powershell
python scripts/validate_google_sheets.py --profile heathcote --write-test
```

After both commands pass, start or redeploy the app, sign in, choose the new
business in the sidebar, and confirm that its workbook title is shown. Repeat
the validation for every configured profile.

Common failures:

- **Service-account authentication failed:** the uploaded JSON key may be
  invalid, disabled, revoked, or no longer active. Download a new key and
  replace the profile credential.
- **Workbook access failed:** confirm that the spreadsheet ID is correct, the
  Sheets API is enabled in the service account's project, and the spreadsheet
  is shared with that profile's exact `client_email`.
- **Workbook initialization failed:** confirm the service account has Editor
  access and the ledger tabs or header cells are not protected.
- **Workbook structure validation failed:** correct the named worksheet and
  first-row headers exactly as listed above.
- **Organization policy blocks sharing:** a Google Workspace administrator may
  need to permit sharing with the service-account address. Do not make the
  spreadsheet public as a workaround.
- **Service-account key creation is disabled:** consult the Workspace/Cloud
  administrator. Newer organizations may enforce this restriction by default.

## Run code quality checks

Install the development dependencies, then run Ruff and the isolated
authentication, UI workflow, Google storage, and reporting tests with:

```powershell
pip install -r requirements-dev.txt
ruff check .
python -m pytest
```

The UI tests use an in-memory Google workbook and a test-only password hash. They do not read the live ledger, application password, or Google credentials.

Run read-only end-to-end dashboard checks against the configured live workbook
in both secrets modes—split local files and the combined hosted Streamlit
Secrets export—with:

```powershell
python scripts/validate_app_google.py
```

## Spreadsheet reliability

- Related worksheet reads use one multi-range request when available, are
  cached for 10 seconds, and have their affected cache cleared immediately
  after every confirmed write.
- Edits, deletions, uniqueness checks, and reference checks force a fresh read before writing.
- Temporary network and quota failures are retried up to four times with exponential backoff.
- Identical completed submissions are suppressed for 10 seconds within the same application session.
- CSV imports and default seeding use batch appends after complete validation.
- Availability errors are generic and success is shown only after the Google API confirms the write.

An append-only audit worksheet was considered but deferred. A separate audit append cannot currently be guaranteed atomic with its ledger write, so it could create a misleading or incomplete history. Versioned ZIP backups are the current recovery record.

## Google Sheets backups

The **Data & backup** page can download a complete ZIP archive. Each archive
contains `Accounts.csv`, `Categories.csv`, `Transactions.csv`, `Mileage.csv`,
and a JSON manifest with the backup time, workbook title, worksheet headers,
row counts, and SHA-256 checksums. Restore remains compatible with older
version 2 backups created before mileage tracking was added.

Create and validate a timestamped backup from the command line with:

```powershell
python scripts/backup_google_sheets.py --profile heathcote --output-dir backups\heathcote --keep 30
```

By default, this writes to the ignored `backups/` directory, never overwrites an
existing archive, and retains the newest 30 generations. Backups contain private
ledger data and must not be committed. To place backups in a Google Drive
Desktop or NAS-synchronized folder, pass its local path:

```powershell
python scripts/backup_google_sheets.py --profile heathcote --keep 30
```

The configured Windows task runs at 10:00 PM every Monday, Tuesday, and
Wednesday. `--once-per-week` verifies existing archives before accessing Google
Sheets, so Tuesday and Wednesday act only as retry opportunities when the
week's earlier run did not succeed. If all three opportunities are missed or
fail, that week is skipped. The task runs interactively because Google Drive
Desktop and its mounted folder are available only in the signed-in Windows
session. The `G:` streaming mount does not remain available independently:
Google Drive for desktop must be running and signed in when the task starts. If
the app, computer, network, or mount is unavailable at 10:00 PM, no backup is
marked complete and the next scheduled Tuesday or Wednesday opportunity tries
again. Starting Drive after a missed run does not trigger an immediate catch-up.

Recreate or update the task with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_weekly_backup_task.ps1 -Profile heathcote -TaskName "Tabula Rosa Backup - Heathcote"
```

For local or NAS backups, register one task with a distinct backup directory
and task name for each profile. This prevents archives with identical
timestamps from different businesses being mixed together.

After connecting OAuth and choosing a backup folder, upload and verify a cloud
backup from **Data & backup**. The Drive uploader preserves the current ZIP
format and manifest, records the archive SHA-256 in private app-properties,
makes retries idempotent, and retains the newest 30 generations.

**Verify latest cloud backup** downloads the newest archive into the running app
only long enough to validate its manifest, checksums, and stored Drive hash. It
does not restore the archive, change the live workbook, or download a file to
the browser. Restoration remains the separate blank-workbook procedure below.

For unattended cloud-native backups, register the existing weekly task with
the Drive flag:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_weekly_backup_task.ps1 -Profile heathcote -GoogleDrive -TaskName "Tabula Rosa Cloud Backup - Heathcote"
```

The task uses the profile's stored refresh token and does not require Google
Drive Desktop to be running. The local Google Drive Desktop/NAS workflow remains
available as a fallback; omit `-GoogleDrive` to use it.

### Optional Synology recovery copy

The DS220j recovery destination is optional per business profile. An opted-in
profile uses a dedicated Synology Cloud Sync task to download its Google Drive
backup folder into a distinct NAS directory. The required direction is
**Download remote changes only**, with destination deletions disabled. Neither
Google Drive Desktop nor a permanently mounted NAS drive is required.

The normal data path is **Google Sheets → verified ZIP in Google Drive → Cloud
Sync download → profile-specific NAS folder**. Google accounts determine Cloud
Sync connections, while business folders determine tasks: businesses sharing a
Drive owner can use separate tasks under one connection; businesses with
different Drive owners need separate connections. DSM is the authoritative
place to monitor transfers and retry failures.

Follow [`docs/SYNOLOGY_RECOVERY.md`](docs/SYNOLOGY_RECOVERY.md) to enable a
profile, configure DSM, validate retained archives, test retry visibility, and
perform the blank-workbook restore drill. A copied NAS archive can be checked
without restoring it:

```powershell
python scripts/validate_google_sheets_backup.py C:\Safe-Recovery\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip
```

The initial DS220j deployment and restore drill for both configured business
profiles were completed on July 28, 2026. The runbook contains the sanitized
deployment record; private validation output and recovery workbook identifiers
remain outside Git.

### Restore drill

Current restore supports backup formats 2 and 3. Convert a historical format-1
archive offline before attempting a restore:

```powershell
python scripts/convert_backup_v1_to_v2.py backups\heathcote\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip
```

The converter fully validates the source, infers any missing account
classification, renames the legacy `Loan` account type to `Short-term debt`,
normalizes legacy active values, and creates a separate
`*-format2.zip` archive. It never modifies or overwrites the original. The
converted archive records the source SHA-256 hash and conversion timestamp in
its manifest and is revalidated by the current backup validator. Format 2
predates mileage tracking, so restoring it leaves the `Mileage` worksheet empty.

1. Create a new blank Google spreadsheet and share it with the service-account
   email as Editor.
2. Copy the new spreadsheet ID from its URL.
3. Restore a selected archive with:

```powershell
python scripts/restore_google_sheets_backup.py backups\heathcote\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip --profile heathcote --target-spreadsheet-id NEW_ID --initialize
```

The restore command verifies checksums, headers, IDs, relationships, and row
counts before writing. It refuses the configured live workbook and refuses any
target whose required ledger worksheets already contain data. After writing, it
rereads every restored row and verifies it against the archive.

## Credentials and recovery

- Local service-account credentials live only in the ignored
  `.streamlit/business_profiles.json` file. The ignored
  `.streamlit/secrets.toml` contains the application password hash and
  app-wide Google Drive OAuth client/Picker configuration. Per-profile Drive
  refresh tokens and folder IDs live in the ignored business profiles file.
- The hosted app uses a separate copy of those TOML values in Streamlit
  Community Cloud's encrypted Secrets settings.
- Hosted Secrets requires `app_password_hash` plus one or more
  `[business_profiles.PROFILE]` configurations. Never store their real values
  in Git, README files, issue trackers, or deployment logs.
- The original service-account JSON is not required after both secrets stores
  are configured. If retained for disaster recovery, keep it only in protected
  credential storage outside the repository.
- To rotate a Sheets credential, disable the old key in Google Cloud, create
  a replacement, update local and hosted secrets, verify access, and then delete
  the old key.
- To rotate the OAuth client secret, update `.streamlit/secrets.toml`, reconnect
  affected profiles if Google invalidates their grants, export hosted Secrets
  again, and only then retire the old secret.
- To replace a forgotten application password, run
  `python scripts/set_app_password.py`, then copy the new hash to the hosted
  Secrets settings.
- Recovery uses a verified versioned ZIP and
  `scripts/restore_google_sheets_backup.py` with a new blank workbook. Never
  test restoration against the live workbook.
- Google Drive holds the newest 30 generations. The optional DS220j Cloud Sync
  copy should use one-way download with destination deletions disabled.

## Notes

- Transfers change account balances but do not affect income or expenses.
- Mileage trips are maintained separately from financial transactions. The
  **Mileage** page records the trip date, total business miles, route, business
  purpose, optional vehicle, and notes; it also supports date filtering,
  editing, deletion, totals, and CSV export. Select **Round trip** while adding
  a trip to create two entries in one write: the outbound route and a return
  entry with the starting and ending locations reversed. Each entry receives
  the mileage entered in the form.
- Account names, balance-sheet classifications, and subtypes are stored in
  separate fields.
- Bank and Cash accounts are assets; Credit card and Short-term debt accounts are
  liabilities; Equity accounts are equity. The flexible Other subtype can be
  classified as an asset, liability, or equity.
- Asset opening balances should normally be positive. Liability and equity
  opening ledger balances should normally be negative; the balance-sheet report
  presents them as conventional positive balances.
- Current earnings are calculated from income minus expenses and included in
  total equity. The report flags any difference in the accounting equation
  `Assets = Liabilities + Equity`.
- CSV import validates account and category names before writing any rows.
- This is a record-keeping tool, not tax or accounting advice.

## Import from QuickBooks Online

In QuickBooks Online, open **Reports > Transaction Detail by Account**, choose
the desired date range, and export the report to CSV. The importer supports the
English-language column names `Date`, `Transaction Type`, `Num`, `Name`,
`Memo/Description`, `Account`, `Split`, and `Amount`. Remove report title,
subtotal, and footer rows before uploading; the first CSV row must be the header.

QuickBooks Self-Employed users can instead use **Settings > Export data**, turn
on **General ledger**, and select **Export to Excel**. Upload either the exported
ZIP or its `General_ledger.xlsx` file directly. The importer pairs the report's
debit and credit entries so each accounting event becomes one ledger transaction;
a separate chart-of-accounts export is not required.

Account and category names must already exist in Tabula Rosa (matching is
case-insensitive). `Account` maps to the source ledger account. For non-transfer
rows, `Split` maps to a category; positive amounts become income and negative or
parenthesized amounts become expenses. For `Transfer` or `Funds Transfer` rows,
`Split` maps to the destination account and the category is left blank. `Name`,
`Memo/Description`, and `Num` map to payee, description, and reference.

The upload screen validates every row and shows counts for income, expenses,
transfers, and duplicates before enabling import. A duplicate has the same date,
type, amount, source/destination account, category, payee, description, and
reference as an existing or earlier uploaded row; duplicates are skipped. Fix
all reported row errors and preview again before committing. Import writes all
validated rows in one batch.

Optionally enable **Automatically create missing accounts and categories** in
the preview. The preview lists every proposed addition. Imported accounts use a
zero opening balance and infer their classification and subtype from the name.
Bank, Cash, Credit card, Short-term debt, and common equity-style names are recognized;
other names use the flexible `Other` subtype and default to Asset. Review the
proposed classification and type before import. Category type is inferred from
the amount (`Income` for positive and `Expense` for negative). Existing names
are matched case-insensitively.

### Import QuickBooks mileage

In QuickBooks Online, open **Expenses & Bills > Mileage**, select the dropdown
next to **Add trip**, and choose **Download Trips**. QuickBooks downloads a CSV
containing the trip date, classification, purpose, vehicle, start and end
addresses, and distance. Upload it under **Data & backup > Import QuickBooks
mileage**.

Only rows classified as `Business` are imported. `Personal` and `Unreviewed`
rows are reported separately and skipped. Every business row must have a date,
trip purpose, start address, end address, and positive distance. Common
QuickBooks header variants are recognized, and distance columns explicitly
labeled in kilometers are converted to miles.

The preview reports ready, duplicate, personal, and unreviewed counts before
enabling import. A mileage duplicate has the same date, distance, vehicle,
start address, end address, and business purpose as an existing or earlier
uploaded trip. Fix all reported business-row errors before committing; valid
business trips are written to the `Mileage` worksheet in one batch.
