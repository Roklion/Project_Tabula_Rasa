# OAuth-only Sheets migration runbook

OAuth migration changes authentication while preserving ledger data and workbook schema. One
existing shared Google Cloud project and web OAuth client serve all businesses.
Keep every profile's workbook ID, grant, account identity, and Drive destinations
separate. The application password remains shared across the deployment.

| When | Manual operator action | Completion evidence |
| --- | --- | --- |
| In parallel with development; before any commit/merge | In the existing OAuth project, enable Sheets API alongside Drive and Picker. Verify Picker key restrictions, project number, local/hosted origins and exact redirect URIs. Use `drive.file`; no broad Sheets scope or per-business Cloud project is needed. | Shared configuration is ready for local setup. |
| In parallel with development | Give the intended human Google account Editor access to each existing ledger. Record profile keys, workbook IDs and current root/Receipts/Ledger Backups IDs. Confirm OAuth production audience or test-user status. Keep an access-controlled copy of current deployment configuration for recovery. | Every account and destination is known; existing app still works. |
| Before an approved OAuth-only configuration transition | Stop the local app. Work on a protected copy of `.streamlit/business_profiles.json`, using the supported converter. Run `python scripts/migrate_profile_oauth.py --profiles PATH_TO_COPY`. Place the converted version 2 file at the new local deployment's configured profile path. | Obsolete Sheets private-key fields removed; grants, workbook IDs and destinations preserved. |
| After local conversion; before local use | Launch the new local administrator. Reauthenticate; for each profile open Google setup, connect/reconnect if needed, and select the **existing** ledger in Picker. Confirm its ID before proceeding. Select Validate ledger, then Run readiness check under Recovery. Preserve existing Drive folders; do not create replacements unless needed. | Profile OAuth can open the ledger; current schema and configured destinations pass. |
| After Picker/readiness; before local use | Run `python scripts/validate_google_sheets.py --profile PROFILE_KEY --write-test` for each profile. This intentionally creates, reads, updates, and deletes a disposable worksheet. Do not run concurrently with ordinary ledger use. | OAuth read/write permission confirmed without changing ledger rows. |
| Only after successful local validation | Remove obsolete service-account workbook sharing; disable/delete its Sheets keys. Retire obsolete key-material copies only through the approved credential-custody process. Keep the unrelated Maps quota reader when configured. | Old Sheets identity is retired and no longer required. |

A Git commit does not perform Google setup, Picker authorization or key
retirement. Streamlit Cloud Secrets export is retired. Commercial encrypted
grant provisioning and named Owner activation follow the separate
[connection procedure](identity/CONNECTIONS_AND_CLAIMS.md).

For converter eligibility, frozen-source restrictions and the per-script retention
decision, follow [explicit source preparation](accounting/SHEETS_MIGRATION.md#explicit-source-preparation-tools).
This runbook applies to a separately approved internal OAuth configuration
transition; it is not a rollback procedure for active PostgreSQL books.

## Failure and recovery

If conversion fails, the original profile file is not replaced. Version 1 is
accepted only by the explicit conversion command, never by normal runtime.
If OAuth refresh fails, reconnect that profile. If file access fails, confirm
Editor permission and select the workbook through Picker; an ID alone cannot
grant access. Reconnection keeps folders only when the account can validate them.

Keep the old service-account access until the new local configuration passes.
If local configuration conversion fails validation, pause use and retain the
protected original for operator investigation. Do not reintroduce old credential
formats into runtime, use dual-auth mode or change workbook data to solve an
authentication failure. Retry only after local OAuth validation succeeds.

## Recovery and the final Sheets source

Use Google setup > Authorize a recovery or migration workbook to grant access
to a candidate without selecting it as the active ledger. Existing restore
commands still reject any configured live workbook and require a blank target.
Authentication conversion preserves profile settings and grants independently
of the [frozen format-13 Sheets boundary](SHEETS_SOURCE_CONTRACT.md). Earlier
ledger/workbook and archive formats are unsupported; their converters are
retired. OAuth/profile conversion itself remains supported.

See [Setup](SETUP.md), [Google OAuth/Picker](GOOGLE_DRIVE.md), and
[Backup and recovery](BACKUP_RECOVERY.md) for the canonical workflows.

For genuinely new profiles only, Create ledger spreadsheet provisions the blank
ledger during local onboarding. It can run as soon as the new code is available
locally during approved setup. Existing profiles
must select their existing ledger during migration, preserving their data.
