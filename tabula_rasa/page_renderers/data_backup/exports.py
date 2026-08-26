"""Live workbook export workflow for the Data & backup page."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

import streamlit as st

from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.page_renderers.mileage import mileage_frame
from tabula_rasa.receipt_backfill import ReceiptPreparationError
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.storage import StorageError


def prepared_exports_key(
    profile_key: str,
    configuration_revision: str,
    workbook_data_revision: int,
) -> str:
    """Return the session key for one confirmed workbook snapshot."""
    return (
        "prepared-live-exports:"
        f"{profile_key}:{configuration_revision}:{workbook_data_revision}"
    )


def render_exports(context: DataBackupContext) -> None:
    """Render staged CSV and complete-workbook downloads."""
    st.subheader("Exports")
    st.caption("Live workbook exports")
    export_key = prepared_exports_key(
        context.profile_key,
        context.configuration_revision,
        int(st.session_state.get("workbook_data_revision", 0)),
    )
    prepared_exports = st.session_state.get(export_key)
    prepare_label = (
        "Refresh downloadable exports"
        if isinstance(prepared_exports, Mapping)
        else "Prepare downloadable exports"
    )
    if st.button(prepare_label, type="primary", width="stretch"):
        with st.spinner("Preparing exports and validating workbook backup..."):
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
                prepared_exports = {
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
                        drive_settings=context.drive_settings,
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
                st.session_state[export_key] = prepared_exports
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
            f"tabula-rasa-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        st.download_button(
            "Download mileage CSV",
            prepared_exports["mileage"],
            f"tabula-rasa-mileage-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        backup_export = prepared_exports.get("backup")
        if isinstance(backup_export, bytes):
            st.download_button(
                "Download complete workbook backup",
                backup_export,
                f"tabula-rasa-backup-{date.today()}.zip",
                "application/zip",
                width="stretch",
            )
