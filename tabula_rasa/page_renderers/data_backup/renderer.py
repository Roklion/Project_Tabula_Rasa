"""Data & backup page rendering."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import io
import zipfile

import pandas as pd
import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveError,
    backup_filename_and_hash,
)
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.page_renderers.mileage import mileage_frame
from tabula_rasa.presentation import render_page_header
from tabula_rasa.quickbooks_import import (
    REQUIRED_COLUMNS as QUICKBOOKS_REQUIRED_COLUMNS,
    general_ledger_rows,
)
from tabula_rasa.quickbooks_mileage_import import (
    missing_required_columns as missing_quickbooks_mileage_columns,
)
from tabula_rasa.receipt_backfill import ReceiptPreparationError
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
    StorageValidationError,
)
from tabula_rasa.synology_recovery import (
    DESTINATION_DELETIONS,
    SYNC_DIRECTION,
    SynologyRecoveryConfigurationError,
    validate_synology_recovery_settings,
)


def alert_list(title: str, messages: list[str]) -> str:
    """Format multiple alert messages as a readable Markdown list."""
    return f"**{title}**\n\n- " + "\n- ".join(messages)


def render_data_backup(context: DataBackupContext) -> None:
    """Render cloud backup, recovery, export, and import workflows."""
    render_page_header(
        "Data & backup",
        "Your live records are stored in the private Google Sheets workbook.",
    )
    drive_settings = context.profile_secrets.get("google_drive")
    storage_root = (
        drive_settings.get("storage_root")
        if isinstance(drive_settings, Mapping)
        else None
    )
    backup_folder = (
        drive_settings.get("backup_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    recovery_receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    backup_drive = None
    latest_cloud = None
    st.subheader("Google Drive backup")
    if not isinstance(backup_folder, Mapping):
        st.info(
            "Connect Google Drive and select a backup folder from the local "
            "Account settings to enable cloud-native backups."
        )
    else:
        try:
            backup_drive = context.get_drive_client(context.profile_key, context.configuration_revision)
            cloud_backups = backup_drive.list_backups(
                profile_key=context.profile_key,
                folder_id=str(backup_folder["id"]),
                limit=30,
            )
        except GoogleDriveError as error:
            st.error(str(error))
        else:
            st.caption(
                f"Destination: {backup_folder.get('name', 'Google Drive folder')}"
            )
            if cloud_backups:
                latest_cloud = cloud_backups[0]
                st.caption(
                    "Latest cloud backup: "
                    f"{latest_cloud.get('name', 'Unknown')} "
                    f"({latest_cloud.get('createdTime', 'time unavailable')})"
                )
            else:
                st.warning("No cloud backup has been uploaded for this profile.")
            st.caption(
                "Verification downloads the latest backup into the app only to "
                "check its integrity. It does not restore or change the live workbook."
            )
            upload_column, verify_column = st.columns(2)
            if upload_column.button(
                "Upload fresh backup now",
                type="primary",
                width="stretch",
            ):
                try:
                    receipt_manifest = context.receipt_manifest_for_backup(
                        context.storage,
                        profile_key=context.profile_key,
                        profile_secrets=context.profile_secrets,
                        configuration_revision=context.configuration_revision,
                    )
                    backup_zip = context.storage.export_backup_zip(receipt_manifest)
                    manifest = context.storage.validate_backup_zip(backup_zip)
                    cloud_filename, cloud_sha256 = backup_filename_and_hash(
                        backup_zip,
                        manifest,
                    )
                    uploaded_backup = backup_drive.upload_backup(
                        profile_key=context.profile_key,
                        folder_id=str(backup_folder["id"]),
                        filename=cloud_filename,
                        content=backup_zip,
                        sha256=cloud_sha256,
                        backup_time=str(manifest["backup_time"]),
                        keep=30,
                    )
                except (
                    StorageError,
                    GoogleDriveError,
                    ReceiptManifestError,
                    RuntimeError,
                ) as error:
                    if isinstance(error, StorageError):
                        context.report_storage_error(error)
                    else:
                        st.error(str(error))
                else:
                    st.success(
                        "Verified backup uploaded to Google Drive: "
                        f"{uploaded_backup.get('name', cloud_filename)}"
                    )
                    st.rerun()
            if verify_column.button(
                "Verify latest cloud backup",
                disabled=latest_cloud is None,
                width="stretch",
            ):
                try:
                    downloaded_backup = backup_drive.download_file(
                        str(latest_cloud["id"])
                    )
                    verified_manifest = GoogleSheetsStorage.validate_backup_zip(
                        downloaded_backup
                    )
                    expected_sha256 = (
                        latest_cloud.get("appProperties", {}).get(
                            "tabulaRasaSha256",
                            "",
                        )
                    )
                    if (
                        expected_sha256
                        and hashlib.sha256(downloaded_backup).hexdigest()
                        != str(expected_sha256)
                    ):
                        raise RuntimeError(
                            "The downloaded cloud backup hash does not match."
                        )
                except (GoogleDriveError, RuntimeError, KeyError) as error:
                    st.error(str(error))
                else:
                    st.success(
                        "Latest cloud backup downloaded and verified: "
                        f"{verified_manifest['backup_time']}."
                    )
                # Verification is deliberately Drive-only. Do not continue
                # into the live Sheets reads and fresh backup generation below.
                st.stop()
    
    st.subheader("Synology recovery copy")
    raw_synology_recovery = context.profile_secrets.get("synology_recovery")
    if raw_synology_recovery is None:
        st.info(
            "No local Synology recovery record is available in this runtime. NAS "
            "settings are intentionally excluded from hosted Secrets; configure "
            "or review them from the loopback-only Account settings page and DSM."
        )
    else:
        try:
            synology_recovery = validate_synology_recovery_settings(
                raw_synology_recovery
            )
        except SynologyRecoveryConfigurationError as error:
            st.error(str(error))
            synology_recovery = None
        if synology_recovery is None:
            st.caption(
                "Repair this profile from the loopback-only Account settings page."
            )
        else:
            if not isinstance(backup_folder, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does not have a "
                    "Google Drive backup folder selected."
                )
            if not isinstance(recovery_receipt_folder, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does not have a "
                    "Google Drive receipt folder selected."
                )
            if not isinstance(storage_root, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does "
                    "not have a Google Drive storage root selected."
                )
            root_source_name = (
                str(storage_root.get("name", "Google Drive storage root"))
                if isinstance(storage_root, Mapping)
                else "Not configured"
            )
            source_lines = (
                "- **Cloud Sync task:** One recursive profile-root task",
                f"- **Remote source:** {root_source_name}",
                "- **Expected NAS children:** Receipts and Ledger Backups",
            )
            st.markdown(
                "\n".join(
                    (
                        *source_lines,
                        "- **Cloud Sync direction:** " + SYNC_DIRECTION,
                        "- **Destination deletions:** " + DESTINATION_DELETIONS,
                        "- **NAS destination:** "
                        + synology_recovery["destination_path"],
                        "- **Schedule:** " + synology_recovery["schedule"],
                        "- **Retention:** " + synology_recovery["retention_policy"],
                    )
                )
            )
            st.caption(
                "These are the expected per-business settings. Project Tabula Rasa does not "
                "connect to the NAS; confirm transfers, failures, and retries in DSM "
                "Cloud Sync with destination deletions disabled is the independent "
                "second-layer copy. Optional versioned retention can protect both "
                "synchronized children with another recovery point."
            )
    
    st.subheader("Live workbook exports")
    prepared_exports_key = (
        "prepared-live-exports:"
        f"{context.profile_key}:{context.configuration_revision}:"
        f"{st.session_state.get('workbook_data_revision', 0)}"
    )
    prepared_exports = st.session_state.get(prepared_exports_key)
    prepare_label = (
        "Refresh downloadable exports"
        if isinstance(prepared_exports, Mapping)
        else "Prepare downloadable exports"
    )
    if st.button(prepare_label, width="stretch"):
        try:
            accounts = context.storage.list_accounts(active_only=False)
            categories = context.storage.list_categories()
            transactions = context.storage.list_transactions()
            mileage_trips = context.storage.list_mileage_trips()
            all_transactions = ledger_frame(
                transactions,
                accounts,
                categories,
                display_paths=False,
            )
            all_mileage = mileage_frame(mileage_trips)
        except StorageError as error:
            context.report_storage_error(error)
        else:
            prepared_exports: dict[str, object] = {
                "backup_time": datetime.now(timezone.utc).isoformat(),
                "transactions": all_transactions.to_csv(index=False).encode(
                    "utf-8"
                ),
                "mileage": all_mileage.to_csv(index=False).encode("utf-8"),
            }
            try:
                receipt_manifest = context.receipt_manifest_for_backup(
                    context.storage,
                    profile_key=context.profile_key,
                    profile_secrets=context.profile_secrets,
                    configuration_revision=context.configuration_revision,
                )
                backup_zip = context.storage.export_backup_zip(receipt_manifest)
                manifest = context.storage.validate_backup_zip(backup_zip)
            except (
                StorageError,
                GoogleDriveError,
                ReceiptManifestError,
                ReceiptPreparationError,
            ) as error:
                prepared_exports["backup_error"] = str(error)
            else:
                prepared_exports["backup"] = backup_zip
                prepared_exports["backup_time"] = str(manifest["backup_time"])
            st.session_state[prepared_exports_key] = prepared_exports
            if "backup" in prepared_exports:
                st.success("Fresh downloadable exports are ready.")
            else:
                st.success("Fresh CSV exports are ready.")
    if isinstance(prepared_exports, Mapping):
        st.caption(f"Prepared from workbook data at {prepared_exports['backup_time']}.")
        backup_error = prepared_exports.get("backup_error")
        if backup_error:
            st.warning(
                "The complete workbook backup is unavailable: "
                f"{backup_error}"
            )
        st.download_button(
            "Download transactions CSV",
            prepared_exports["transactions"],
            f"tabula-rosa-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        st.download_button(
            "Download mileage CSV",
            prepared_exports["mileage"],
            f"tabula-rosa-mileage-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        backup_export = prepared_exports.get("backup")
        if isinstance(backup_export, bytes):
            st.download_button(
                "Download complete workbook backup",
                backup_export,
                f"tabula-rosa-backup-{date.today()}.zip",
                "application/zip",
                width="stretch",
            )
    with st.expander("Import Project Tabula Rasa CSV"):
        st.write(
            "Upload a CSV with: Date, Type, Amount, Account, Category, Payee, "
            "Description, Reference. Type must be Income or Expense."
        )
        plain_upload = st.file_uploader(
            "CSV file",
            type="csv",
            key=f"transaction_csv_upload_{context.profile_key}",
        )
        if plain_upload:
            try:
                plain_incoming = pd.read_csv(plain_upload).where(
                    lambda frame: frame.notna(), ""
                )
                plain_required = {"Date", "Type", "Amount", "Account", "Category"}
                plain_missing = plain_required - set(plain_incoming.columns)
                if plain_missing:
                    st.error(f"Missing columns: {', '.join(sorted(plain_missing))}")
                else:
                    st.dataframe(plain_incoming.head(20), hide_index=True, width="stretch")
                    if st.button("Import rows", type="primary"):
                        plain_records = plain_incoming.to_dict(orient="records")
                        context.confirmed_write(
                            "import_csv_transactions",
                            {"rows": plain_records},
                            lambda: context.storage.import_csv_transactions(plain_records),
                            lambda imported: f"Imported {len(imported)} transactions.",
                        )
            except StorageValidationError as error:
                context.report_storage_error(error)
            except (ValueError, pd.errors.ParserError, UnicodeError):
                st.error("Could not read this CSV file. Check its format and encoding.")
    st.subheader("Import QuickBooks transactions")
    st.write(
        "Upload a QuickBooks Online **Transaction Detail by Account** CSV, "
        "or a QuickBooks Self-Employed **General ledger** XLSX or ZIP export. "
        "Review the validation results and summary before committing."
    )
    upload = st.file_uploader(
        "QuickBooks export",
        type=["csv", "xlsx", "zip"],
        key=f"quickbooks_transaction_upload_{context.profile_key}",
    )
    if upload:
        try:
            upload_bytes = upload.getvalue()
            upload_name = upload.name.casefold()
            conversion_errors: list[str] = []
            if upload_name.endswith(".csv"):
                incoming = pd.read_csv(io.BytesIO(upload_bytes)).where(lambda frame: frame.notna(), "")
            else:
                if upload_name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(upload_bytes)) as archive:
                        workbooks = [name for name in archive.namelist() if name.casefold().endswith(".xlsx") and not name.startswith("__MACOSX/")]
                        if len(workbooks) != 1:
                            raise ValueError("The ZIP must contain exactly one QuickBooks .xlsx workbook")
                        if archive.getinfo(workbooks[0]).file_size > 25 * 1024 * 1024:
                            raise ValueError("The QuickBooks workbook is larger than 25 MB")
                        workbook_bytes = archive.read(workbooks[0])
                else:
                    workbook_bytes = upload_bytes
                ledger = pd.read_excel(io.BytesIO(workbook_bytes), sheet_name="General Ledger", header=None).where(lambda frame: frame.notna(), "")
                records, conversion_errors = general_ledger_rows(ledger.values.tolist())
                incoming = pd.DataFrame(records, columns=sorted(QUICKBOOKS_REQUIRED_COLUMNS))
            missing = QUICKBOOKS_REQUIRED_COLUMNS - set(incoming.columns)
            if missing:
                st.error(f"Missing columns: {', '.join(sorted(missing))}")
            else:
                records = incoming.to_dict(orient="records")
                auto_create = st.checkbox(
                    "Automatically create missing accounts and categories",
                    help="New accounts use an inferred type and zero opening balance. Category type is inferred from the amount.",
                )
                preview = context.storage.preview_quickbooks_transactions(
                    records, auto_create=auto_create
                )
                summary = preview["summary"]
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Ready", summary["ready"])
                c2.metric("Duplicates", summary["duplicates"])
                c3.metric("Income", summary["Income"])
                c4.metric("Expenses", summary["Expense"])
                c5.metric("Transfers", summary["Transfer"])
                if preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these import errors before continuing:",
                            preview["errors"],
                        )
                    )
                if conversion_errors:
                    st.error(
                        alert_list(
                            "Some QuickBooks rows could not be converted:",
                            conversion_errors,
                        )
                    )
                if auto_create and (preview["new_accounts"] or preview["new_categories"]):
                    additions = [
                        (
                            f"Account name: {name} — Classification: "
                            f"{preview['new_account_classifications'][name]} — "
                            f"Type: {preview['new_account_types'][name]}"
                        )
                        for name in preview["new_accounts"]
                    ]
                    additions += [f"{kind} category: {name}" for name, kind in preview["new_categories"]]
                    st.info("Will create:\n\n- " + "\n- ".join(additions))
                if preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated rows will be skipped: "
                        + ", ".join(map(str, preview["duplicate_rows"]))
                    )
                st.dataframe(incoming.head(50), hide_index=True, width="stretch")
                if st.button(
                    "Import validated rows",
                    type="primary",
                    disabled=bool(preview["errors"] or conversion_errors) or not summary["ready"],
                ):
                    context.confirmed_write(
                        "import_quickbooks_transactions",
                        {"rows": records, "auto_create": auto_create},
                        lambda: context.storage.import_quickbooks_transactions(
                            records, auto_create=auto_create
                        ),
                        lambda imported: f"Imported {len(imported)} transactions.",
                    )
        except StorageValidationError as error:
            context.report_storage_error(error)
        except (ValueError, KeyError, zipfile.BadZipFile, pd.errors.ParserError, UnicodeError):
            st.error("Could not read this QuickBooks export. Check its format and file integrity.")
    
    st.subheader("Import QuickBooks mileage")
    st.write(
        "In QuickBooks Online, open **Expenses & Bills > Mileage**, use the "
        "dropdown next to **Add trip**, and select **Download Trips**. Upload "
        "that CSV here. Business trips are imported; Personal and Unreviewed "
        "trips are skipped."
    )
    mileage_upload = st.file_uploader(
        "QuickBooks mileage CSV",
        type="csv",
        key="quickbooks_mileage_upload",
    )
    if mileage_upload:
        try:
            mileage_incoming = pd.read_csv(mileage_upload).where(
                lambda frame: frame.notna(), ""
            )
            mileage_missing = missing_quickbooks_mileage_columns(
                mileage_incoming.columns
            )
            if mileage_missing:
                st.error(
                    "Missing QuickBooks mileage columns: "
                    + ", ".join(mileage_missing)
                )
            else:
                mileage_records = mileage_incoming.to_dict(orient="records")
                mileage_preview = context.storage.preview_quickbooks_mileage(
                    mileage_records
                )
                mileage_summary = mileage_preview["summary"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mileage ready", mileage_summary["ready"])
                c2.metric(
                    "Mileage duplicates", mileage_summary["duplicates"]
                )
                c3.metric(
                    "Personal skipped",
                    mileage_summary["personal_skipped"],
                )
                c4.metric(
                    "Unreviewed skipped",
                    mileage_summary["unreviewed_skipped"],
                )
                if mileage_preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these mileage import errors before continuing:",
                            mileage_preview["errors"],
                        )
                    )
                if mileage_preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated mileage rows will be "
                        "skipped: "
                        + ", ".join(
                            map(str, mileage_preview["duplicate_rows"])
                        )
                    )
                if mileage_preview["personal_rows"]:
                    st.info(
                        "Personal mileage rows will be skipped: "
                        + ", ".join(map(str, mileage_preview["personal_rows"]))
                    )
                if mileage_preview["unreviewed_rows"]:
                    st.info(
                        "Unreviewed mileage rows will be skipped: "
                        + ", ".join(
                            map(str, mileage_preview["unreviewed_rows"])
                        )
                    )
                st.dataframe(
                    mileage_incoming.head(50),
                    hide_index=True,
                    width="stretch",
                )
                if st.button(
                    "Import validated mileage",
                    type="primary",
                    disabled=bool(mileage_preview["errors"])
                    or not mileage_summary["ready"],
                ):
                    context.confirmed_write(
                        "import_quickbooks_mileage",
                        {"rows": mileage_records},
                        lambda: context.storage.import_quickbooks_mileage(
                            mileage_records
                        ),
                        lambda imported: (
                            f"Imported {len(imported)} mileage trips."
                        ),
                    )
        except StorageValidationError as error:
            context.report_storage_error(error)
        except (ValueError, pd.errors.ParserError, UnicodeError):
            st.error(
                "Could not read this QuickBooks mileage CSV. "
                "Check its format and encoding."
            )
