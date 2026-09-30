# OAuth-only Sheets migration runbook

Issue #215 changes authentication, not ledger data or workbook schema. One
existing shared Google Cloud project and web OAuth client serve all businesses.
Keep every profile's workbook ID, grant, account identity, and Drive destinations
separate. The application password remains shared across the deployment.

| When | Manual operator action | Completion evidence |
| --- | --- | --- |
| In parallel with development; before any commit/merge | In the existing OAuth project, enable Sheets API alongside Drive and Picker. Verify Picker key restrictions, project number, local/hosted origins and exact redirect URIs. Use `drive.file`; no broad Sheets scope or per-business Cloud project is needed. | Shared configuration is ready for local setup. |
| In parallel with development | Give the intended human Google account Editor access to each existing ledger. Record profile keys, workbook IDs and current root/Receipts/Ledger Backups IDs. Confirm OAuth production audience or test-user status. Keep an access-controlled copy of current deployment configuration for recovery. | Every account and destination is known; existing app still works. |
| Once this branch is available locally; can happen before commit/merge | Stop the local app. Work on a protected copy of `.streamlit/business_profiles.json`, using this branch's code. Run `python scripts/migrate_profile_oauth.py --profiles PATH_TO_COPY`. Place the converted version 2 file at the new local deployment's configured profile path. | Obsolete Sheets private-key fields removed; grants, workbook IDs and destinations preserved. |
| After local conversion; before hosted cutover | Launch the new local administrator. Reauthenticate; for each profile open Google setup, connect/reconnect if needed, and select the **existing** ledger in Picker. Confirm its ID before proceeding. Select Validate ledger, then Run readiness check under Recovery. Preserve existing Drive folders; do not create replacements unless needed. | Profile OAuth can open the ledger; current schema and configured destinations pass. |
| After Picker/readiness; before hosted cutover | Run `python scripts/validate_google_sheets.py --profile PROFILE_KEY --write-test` for each profile. This intentionally creates, reads, updates, and deletes a disposable worksheet. Do not run concurrently with ordinary ledger use. | OAuth read/write permission confirmed without changing ledger rows. |
| After local validation; before deployment | Generate the complete hosted document with `python scripts/export_streamlit_secrets.py`. Keep it protected and inspect it locally: shared OAuth client plus profile grants/resources, no `gcp_service_account`. | Hosted projection matches every intended profile. |
| After merge, during a brief maintenance window | Pause hosted use. Deploy the OAuth-only code **and** replace hosted Secrets with the complete new document together; then restart. Neither format works with the other release. Do not roll out one half to an active application. | Hosted app starts on the new code/configuration pair. |
| Immediately after cutover | Sign in and validate **every** profile's workbook, accounts, balances, receipts, cloud backup, and a controlled ledger operation. Check profiles using different Google accounts and any using the same account. | Correct ledger/destinations and working supported operations for all profiles. |
| Only after successful hosted validation | Remove obsolete service-account workbook sharing; disable/delete its Sheets keys. Retire protected copies containing old key material and delete the generated Secrets handoff file. Keep the unrelated Maps quota reader when configured. | Old Sheets identity is retired and no longer required. |

A Git commit by itself requires no live configuration changes. Merge does not
perform Cloud setup, Picker authorization, hosted Secrets replacement, or key
retirement. The operator must coordinate those steps with deployment.

## Failure and recovery

If conversion fails, the original profile file is not replaced. Version 1 is
accepted only by the explicit conversion command, never by normal runtime.
If OAuth refresh fails, reconnect that profile. If file access fails, confirm
Editor permission and select the workbook through Picker; an ID alone cannot
grant access. Reconnection keeps folders only when the account can validate them.

Keep the old service-account access until the new hosted deployment passes. If
cutover fails, pause use and restore the previous **code and configuration pair**
from protected operator storage. Do not mix old/new Secrets, use dual-auth mode,
or change workbook data to solve an authentication failure. Retry the cutover
only after local OAuth validation succeeds.

## Recovery and historical schema migration

Use Google setup > Authorize a recovery or migration workbook to grant access
to a candidate without selecting it as the active ledger. Existing restore
commands still reject any configured live workbook and require a blank target.
Authentication conversion does not run historical workbook conversion.

See [Setup](SETUP.md), [Google OAuth/Picker](GOOGLE_DRIVE.md), and
[Backup and recovery](BACKUP_RECOVERY.md) for the canonical workflows.

For genuinely new profiles only, Create ledger spreadsheet provisions the blank
ledger during local onboarding. It can run as soon as the new code is available
locally (before commit/merge) and before the hosted export. Existing profiles
must select their existing ledger during migration, preserving their data.
