"""Linked receipt and unreferenced Drive receipt display."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
import streamlit as st
from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file
from tabula_rasa.storage import decode_receipt_references
from tabula_rasa.storage import StorageError
from .receipt_workflows import (
    _mark_workbook_data_changed,
    _receipt_folder,
    _record_editor_receipt_linked,
    _remove_editor_receipt_from_recovery,
)
from .receipt_editor import (
    _render_editor_receipt_recovery,
)

def render_receipts(
    context: TransactionsContext,
    *,
    selected: Mapping[str, object],
    all_transactions: Sequence[Mapping[str, object]],
    edit_id: str,
) -> None:
    """Render linked receipts and the manual unreferenced-file recovery surface."""
    st.divider()
    st.subheader("Receipt")
    receipt_folder = _receipt_folder(context)
    if receipt_folder is None:
        _render_editor_receipt_recovery(
            context,
            edit_id,
            None,
        )
        st.info(
            "Connect Google Drive and select a receipt folder from the local "
            "Account settings page."
        )
        return
    try:
        receipt_drive = context.get_drive_client(
            context.profile_key,
            context.configuration_revision,
        )
    except GoogleDriveError as error:
        _render_editor_receipt_recovery(
            context,
            edit_id,
            receipt_folder,
        )
        st.error(str(error))
        return

    scope = f"{context.profile_key}-{edit_id}"
    candidate_key = f"receipt-unlink-candidate-{scope}"
    notice_key = f"receipt-notice-{scope}"
    _render_editor_receipt_recovery(context, edit_id, receipt_folder)
    if notice := st.session_state.pop(notice_key, None):
        st.success(str(notice))

    try:
        receipt_references = decode_receipt_references(
            selected.get("receipt_references", "")
        )
    except StorageError as error:
        st.error(str(error))
        return

    receipt_ids = {str(reference["id"]) for reference in receipt_references}
    if st.session_state.get(candidate_key) not in receipt_ids:
        st.session_state.pop(candidate_key, None)
    for reference in receipt_references:
        receipt_id = str(reference["id"])
        name = str(reference["name"])
        receipt_column, delete_column = st.columns([4, 1])
        with receipt_column:
            st.link_button(name, f"https://drive.google.com/open?id={receipt_id}")
        with delete_column:
            if st.button(
                "Remove receipt",
                key=f"receipt-unlink-request-{scope}-{receipt_id}",
                width="stretch",
            ):
                st.session_state[candidate_key] = receipt_id
                st.rerun()
        if st.session_state.get(candidate_key) != receipt_id:
            continue
        st.warning(
            f"Remove `{name}` from this transaction? The file will remain in Google Drive."
        )
        unlink_error = st.empty()
        cancel_column, confirm_column = st.columns(2)
        if cancel_column.button(
            "Cancel",
            key=f"receipt-unlink-cancel-{scope}-{receipt_id}",
            width="stretch",
        ):
            st.session_state.pop(candidate_key, None)
            st.rerun()
        if confirm_column.button(
            "Remove reference",
            type="primary",
            key=f"receipt-unlink-confirm-{scope}-{receipt_id}",
            width="stretch",
        ):
            try:
                context.storage.unlink_transaction_receipt(
                    edit_id,
                    file_id=receipt_id,
                )
            except StorageError as error:
                unlink_error.error(f"Receipt reference was not removed. {error}")
            else:
                _mark_workbook_data_changed(context)
                _remove_editor_receipt_from_recovery(
                    context,
                    edit_id,
                    receipt_id,
                )
                st.session_state.pop(candidate_key, None)
                st.session_state[notice_key] = (
                    f"Receipt removed: {name}. The file remains in Google Drive."
                )
                st.rerun()

    referenced_receipt_ids: set[str] = set()
    try:
        for transaction in all_transactions:
            referenced_receipt_ids.update(
                str(reference["id"])
                for reference in decode_receipt_references(
                    transaction.get("receipt_references", "")
                )
            )
    except StorageError as error:
        st.error(f"Receipt references could not be read. {error}")
        return

    try:
        profile_receipts = receipt_drive.list_profile_receipts(
            profile_key=context.profile_key,
            folder_id=str(receipt_folder["id"]),
        )
    except GoogleDriveError as error:
        st.error(f"Unreferenced Google Drive receipts could not be listed. {error}")
        return

    unreferenced_receipts: list[dict[str, Any]] = []
    receipts_needing_integrity = 0
    for receipt in profile_receipts:
        receipt_id = str(receipt.get("id", ""))
        if not receipt_id or receipt_id in referenced_receipt_ids:
            continue
        try:
            unreferenced_receipts.append(receipt_reference_from_drive_file(receipt))
        except ReceiptManifestError:
            receipts_needing_integrity += 1
    if receipts_needing_integrity:
        st.warning(
            f"{receipts_needing_integrity} receipt(s) need integrity metadata "
            "before they can be linked."
        )
    if not unreferenced_receipts:
        st.caption("No unreferenced receipts are available in Google Drive.")
        return

    unreferenced_by_id = {
        str(receipt["id"]): receipt for receipt in unreferenced_receipts
    }
    existing_receipt_id = st.selectbox(
        "Unreferenced receipt",
        list(unreferenced_by_id),
        format_func=lambda file_id: unreferenced_by_id[file_id]["name"],
        key=f"receipt-existing-select-{scope}",
        help=(
            "App-managed files in this profile's receipt folder that are not "
            "linked to another transaction."
        ),
    )
    link_error = st.empty()
    if st.button("Link selected receipt", key=f"receipt-existing-link-{scope}"):
        existing_receipt = unreferenced_by_id[existing_receipt_id]
        try:
            context.storage.link_transaction_receipt(
                edit_id,
                reference=existing_receipt,
            )
        except StorageError as error:
            link_error.error(f"The receipt could not be linked. {error}")
        else:
            _mark_workbook_data_changed(context)
            _record_editor_receipt_linked(
                context,
                edit_id,
                existing_receipt,
            )
            st.session_state[notice_key] = (
                f"Receipt linked: {existing_receipt['name']}"
            )
            st.rerun()
