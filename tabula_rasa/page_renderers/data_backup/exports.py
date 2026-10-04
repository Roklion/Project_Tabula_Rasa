"""Live workbook export workflow for the Data & backup page."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import csv
import io

import streamlit as st

from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.page_renderers.mileage import mileage_frame
from tabula_rasa.receipt_backfill import ReceiptPreparationError
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.errors import StorageError


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


def prepare_csv_exports(
    services: ApplicationServices,
    *,
    accounts: list[dict],
    tags: list[dict],
) -> dict[str, bytes]:
    """Build profile-local transaction and mileage CSV snapshots with Tags."""
    categories = services.categories.list()
    transactions = services.transactions.list()
    journals = services.journals.list()
    mileage_trips = [trip.as_record() for trip in services.mileage.list_trips()]
    transaction_frame = ledger_frame(
        transactions,
        accounts,
        categories,
        display_paths=False,
        tags=tags,
    )
    mileage_log = mileage_frame(mileage_trips, tags)
    journal_output = io.StringIO(newline="")
    journal_writer = csv.DictWriter(journal_output, fieldnames=[
        "Entry ID", "Date", "Memo", "Posting ID", "Position", "Account type",
        "Account ID", "Account", "Debit", "Credit", "Payee", "Description",
    ])
    journal_writer.writeheader()
    account_names = {row["id"]: row["name"] for row in accounts}
    category_names = {row["id"]: row["name"] for row in categories}
    for entry in journals:
        for line in entry["postings"]:
            names = account_names if line["target_type"] == "account" else category_names
            journal_writer.writerow({
                "Entry ID": entry["id"], "Date": entry["txn_date"], "Memo": entry["description"],
                "Posting ID": line["id"], "Position": line["position"],
                "Account type": line["target_type"], "Account ID": line["target_id"],
                "Account": names.get(line["target_id"], ""),
                "Debit": line["amount"] if line["side"] == "Debit" else "",
                "Credit": line["amount"] if line["side"] == "Credit" else "",
                "Payee": line.get("payee", ""), "Description": line["description"],
            })
    return {
        "transactions": transaction_frame.to_csv(index=False).encode("utf-8"),
        "journals": journal_output.getvalue().encode("utf-8"),
        "mileage": mileage_log.to_csv(index=False).encode("utf-8"),
    }


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
    prepare_error = st.empty()
    if st.button(prepare_label, type="primary", width="stretch"):
        with st.spinner("Preparing exports and validating workbook backup..."):
            backup_error = None
            try:
                receipt_manifest = context.receipt_manifest_for_backup(
                    context.workbook_admin,
                    profile_key=context.profile_key,
                    drive_settings=context.drive_settings,
                    configuration_revision=context.configuration_revision,
                )
            except (
                StorageError,
                GoogleDriveError,
                ReceiptManifestError,
                ReceiptPreparationError,
            ) as error:
                backup_error = str(error)
                receipt_manifest = None
            try:
                csv_exports = prepare_csv_exports(
                    context.services,
                    accounts=context.services.accounts.list(active_only=False),
                    tags=context.services.tags.list(),
                )
            except StorageError as error:
                prepare_error.error(str(error))
                prepared_exports = None
            else:
                prepared_exports = {
                    "backup_time": datetime.now(timezone.utc).isoformat(),
                    **csv_exports,
                }
                if receipt_manifest is None:
                    prepared_exports["backup_error"] = backup_error
                else:
                    try:
                        backup_zip = context.workbook_admin.export_backup_zip(receipt_manifest)
                        manifest = context.workbook_admin.validate_backup_zip(backup_zip)
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
                export_key = prepared_exports_key(
                    context.profile_key,
                    context.configuration_revision,
                    int(st.session_state.get("workbook_data_revision", 0)),
                )
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
        if "journals" in prepared_exports:
            st.download_button(
                "Download journal postings CSV", prepared_exports["journals"],
                f"tabula-rasa-journals-{date.today()}.csv", "text/csv", width="stretch",
            )
        st.caption("Transactions and journal postings are separate CSVs. The complete workbook backup includes both.")
        backup_export = prepared_exports.get("backup")
        if isinstance(backup_export, bytes):
            st.download_button(
                "Download complete workbook backup",
                backup_export,
                f"tabula-rasa-backup-{date.today()}.zip",
                "application/zip",
                width="stretch",
            )
