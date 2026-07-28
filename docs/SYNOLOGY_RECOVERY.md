# Optional Synology recovery copy

Each business profile can independently opt in to an isolated recovery copy on
the Synology DS220j. Tabula Rosa uploads verified, timestamped ZIP archives to
that profile's regular Google Drive backup folder. Synology Cloud Sync downloads
those archives directly to the NAS.

The application never mounts, authenticates to, or writes directly to the NAS.
The per-profile Synology fields are non-secret operational records of the Cloud
Sync task that an administrator must configure and monitor in DSM.

## Prerequisites

- A Google Drive backup folder selected for the business profile
- A verified format-version 3 backup in that folder
- DSM administrator access to the DS220j
- Synology Cloud Sync installed
- A protected shared folder with enough capacity for historical generations
- A local recovery location that is outside the repository
- A blank Google workbook for the restore drill

Use the Google account that owns the selected backup folder when authorizing
Cloud Sync. Do not use a folder visible only through **Shared with me**, a Drive
shortcut, the **Computers** area, or a Google Workspace Shared Drive.

## Choose which businesses use the NAS

Run the loopback-only profile administrator:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local_profile_admin.ps1
```

Open **Business profiles**, unlock administration, and find **Synology recovery
copy**. For each business:

1. Choose the business profile.
2. Select **Maintain an optional Synology recovery copy for this business**.
3. Record its absolute DSM destination, for example
   `/volume1/Backups/TabulaRasa/heathcote-advisory`.
4. Record the actual Cloud Sync schedule.
5. Record the NAS retention policy.
6. Save the choice.

Leaving the option cleared keeps that business on Google Drive backup only.
Disabling it later removes only the application's operational metadata. It does
not delete a DSM task or any NAS archive.

The hosted app can display the same per-profile status after running
`scripts/export_streamlit_secrets.py` and updating Streamlit Secrets. The
Synology fields contain no NAS username, password, hostname, token, or network
share credential.

## Configure one Cloud Sync task per opted-in business

Create a separate destination folder and task for every business. Do not point
multiple profiles at the same NAS directory.

| Setting | Required value |
| --- | --- |
| Cloud provider | Google Drive |
| Remote path | The profile's dedicated Google Drive backup folder |
| Local path | The profile's recorded NAS destination |
| Sync direction | **Download remote changes only** |
| Destination deletions | **Don't remove files in the destination folder when they are removed in the source folder** |
| Schedule | The value recorded in the business profile |
| Google document conversion | Disabled |

Use a dedicated remote folder containing only names in this form:

```text
tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip
```

The manifest is stored inside the ZIP. Never place service-account JSON,
Streamlit Secrets exports, OAuth tokens, temporary exports, receipt files, or
source accounting CSV files in the backup folder.

Google Drive retains the newest 30 app-managed generations. With destination
deletions disabled, older NAS copies remain until an administrator applies the
recorded NAS retention policy. A safe initial policy is:

> Retain all synchronized generations until a quarterly manual review. Never
> remove the only verified generation for a recovery period.

## Create and validate the first NAS copy

Create a fresh verified cloud backup for the selected profile:

```powershell
.\.venv\Scripts\python.exe scripts\backup_google_sheets.py --profile heathcote-advisory --google-drive --keep 30
```

Wait for Cloud Sync to report the task as up to date. Confirm that the archive
arrived in the business's distinct NAS folder and that no unrelated file
arrived.

Copy the archive from the NAS to a safe local recovery folder. SMB mapping is
optional; DSM File Station, a temporary UNC path, or a mapped drive can be used.
Do not validate or restore directly from a partially synchronized file.

Validate the copied archive:

```powershell
.\.venv\Scripts\python.exe scripts\validate_google_sheets_backup.py "C:\Safe-Recovery\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip"
```

Successful validation confirms the supported format, ZIP structure, manifest,
worksheet headers, SHA-256 checksums, IDs, relationships, and row counts. The
report must include Accounts, Categories, Transactions, and Mileage for a
format-version 3 archive.

## Validate history and retry behavior

1. Allow at least two timestamped backup generations to synchronize.
2. Confirm both remain on the NAS after the newer generation arrives.
3. Pause the Cloud Sync task.
4. Upload another verified backup.
5. Confirm DSM visibly reports that the task is paused or not current.
6. Resume the task and confirm the pending archive arrives intact.
7. Review the Cloud Sync log and record the successful retry.

This pause-and-resume drill avoids corrupting a real archive while demonstrating
that an interrupted task is visible and safely repeatable.

## Restore drill

Create a new blank Google spreadsheet, share it as Editor with the selected
profile's Sheets service-account email, and copy its spreadsheet ID. Never use
the live workbook as the restore target.

Restore the validated local copy:

```powershell
.\.venv\Scripts\python.exe scripts\restore_google_sheets_backup.py "C:\Safe-Recovery\tabula-rosa-backup-YYYYMMDDTHHMMSSZ.zip" --profile heathcote-advisory --target-spreadsheet-id NEW_ID --initialize
```

The command validates before writing, refuses the configured live workbook,
refuses populated or incompatible target worksheets, restores the archive, and
rereads the target to verify the restored rows.

Confirm the output reports the expected row counts. Open the recovery workbook
and spot-check worksheet headers and representative account, category,
transaction, and mileage relationships. Delete or clearly label the drill
workbook afterward so it cannot be mistaken for the live ledger.

## Completion evidence

Keep a private operational record for each opted-in business containing:

- Google Drive source folder name
- NAS destination path
- Cloud Sync direction, deletion protection, and schedule
- NAS retention policy
- First synchronized archive name and timestamp
- Validator output and expected row counts
- Evidence of multiple retained generations
- Cloud Sync pause/failure and successful retry log
- Recovery archive copy location
- Restore command output and recovery workbook ID
- Drill date and administrator

Do not put credentials, tokens, private ledger data, or full service-account
emails in the GitHub issue.
