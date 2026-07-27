# Tabula Rosa

A private Google Sheets-backed bookkeeping app for one person or a small group of businesses. Each business can use its own spreadsheet and Google service account while sharing one Streamlit deployment.

## Run it

1. Install Python 3.11 or newer.
2. Follow the profile setup below. Keep the application password hash in
   `.streamlit/secrets.toml`; all business settings and credentials live in
   `.streamlit/business_profiles.json`.
3. In this folder, run:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
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
4. Create these four worksheet tabs with the exact names and first-row headers
   below. Header spelling and capitalization must match; column order may
   differ.

   | Worksheet | Row 1 headers, from left to right |
   | --- | --- |
   | `Accounts` | `id`, `name`, `type`, `classification`, `opening_balance`, `active`, `created_at` |
   | `Categories` | `id`, `name`, `kind` |
   | `Transactions` | `id`, `txn_date`, `kind`, `amount`, `account_id`, `to_account_id`, `category_id`, `payee`, `description`, `reference`, `created_at` |
   | `Mileage` | `id`, `trip_date`, `miles`, `vehicle`, `start_location`, `destination`, `business_purpose`, `notes`, `created_at` |

   The default `Sheet1` tab may be deleted. Leave rows below the headers empty;
   the app seeds its initial account and categories on first access. When an
   existing three-tab workbook is opened after upgrading, the app creates the
   new empty `Mileage` worksheet automatically.
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
`.streamlit/secrets.toml` should contain only application-level secrets:

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

### 6. Validate before using the profile

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

- **Authentication or workbook access failed:** confirm that the profile's
  spreadsheet ID and complete JSON key belong together, the Sheets API is
  enabled in the service account's project, and the spreadsheet is shared as
  Editor with that profile's exact `client_email`.
- **Header mismatch or missing worksheet:** correct the four tab names and
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

- Worksheet reads are cached for 10 seconds and the affected cache is cleared immediately after every confirmed write.
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

Register one task with a distinct backup directory and task name for each
profile. This prevents archives with identical timestamps from different
businesses being mixed together.

An optional future upgrade is to replace the local mount with a cloud-native
Google Apps Script or Google user OAuth flow that uploads directly through the
Drive API. The service account remains appropriate for editing the existing
spreadsheet but cannot own newly created backup files in a personal My Drive.

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
  `.streamlit/secrets.toml` contains the application password hash.
- The hosted app uses a separate copy of those TOML values in Streamlit
  Community Cloud's encrypted Secrets settings.
- Hosted Secrets requires `app_password_hash` plus one or more
  `[business_profiles.PROFILE]` configurations. Never store their real values
  in Git, README files, issue trackers, or deployment logs.
- The original service-account JSON is not required after both secrets stores
  are configured. If retained for disaster recovery, keep it only in protected
  credential storage outside the repository.
- To rotate the Google credential, disable the old key in Google Cloud, create
  a replacement, update local and hosted secrets, verify access, and then delete
  the old key.
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
