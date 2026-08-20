"""Receipt management for an existing transaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import streamlit as st

from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import StorageError, decode_receipt_references


def render_receipts(
    context: TransactionsContext,
    *,
    selected: Mapping[str, object],
    all_transactions: Sequence[Mapping[str, object]],
    edit_id: str,
) -> None:
    """Render receipt links, unlinking, relinking, and upload for one row."""
    st.divider()
    st.subheader("Receipt")
    selected_profile = context.profile_secrets
    drive_settings = selected_profile.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    if not isinstance(receipt_folder, Mapping):
        st.info(
            "Connect Google Drive and select a receipt folder from "
            "the local Business profiles page. Until then, store the "
            f"receipt manually as `{edit_id}-original-file-name`."
        )
    else:
        try:
            receipt_drive = context.get_drive_client(
                context.profile_key,
                context.configuration_revision,
            )
        except GoogleDriveError as error:
            st.error(str(error))
        else:
            receipt_action_scope = (
                f"{context.profile_key}-{edit_id}"
            )
            receipt_candidate_key = (
                f"receipt-unlink-candidate-{receipt_action_scope}"
            )
            receipt_notice_key = (
                f"receipt-unlink-notice-{receipt_action_scope}"
            )
            receipt_notice = st.session_state.pop(
                receipt_notice_key,
                None,
            )
            if receipt_notice:
                st.success(str(receipt_notice))

            raw_receipt_references = selected.get(
                "receipt_references",
                "",
            )
            references_ready = True
            try:
                receipt_references = decode_receipt_references(
                    raw_receipt_references
                )
            except StorageError as error:
                references_ready = False
                receipt_references = []
                st.error(str(error))
            if references_ready and raw_receipt_references == "":
                try:
                    legacy_receipts = receipt_drive.list_receipts(
                        profile_key=context.profile_key,
                        transaction_id=edit_id,
                        folder_id=str(receipt_folder["id"]),
                    )
                    receipt_references = [
                        receipt_reference_from_drive_file(receipt)
                        for receipt in legacy_receipts
                        if receipt.get("id")
                    ]
                    context.storage.set_transaction_receipt_references(
                        edit_id,
                        receipt_references,
                    )
                except (
                    GoogleDriveError,
                    ReceiptManifestError,
                    StorageError,
                ) as error:
                    references_ready = False
                    st.error(
                        "Existing receipt references could not be "
                        f"initialized. {error}"
                    )

            receipt_ids = {
                reference["id"]
                for reference in receipt_references
            }
            if (
                st.session_state.get(receipt_candidate_key)
                not in receipt_ids
            ):
                st.session_state.pop(receipt_candidate_key, None)
            if references_ready and receipt_references:
                for reference in receipt_references:
                    receipt_id = reference["id"]
                    name = reference["name"]
                    link = (
                        "https://drive.google.com/open?id="
                        f"{receipt_id}"
                    )
                    receipt_column, delete_column = st.columns(
                        [4, 1]
                    )
                    with receipt_column:
                        if link:
                            st.link_button(name, link)
                        else:
                            st.caption(name)
                    with delete_column:
                        if receipt_id and st.button(
                            "Remove receipt",
                            key=(
                                "receipt-unlink-request-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            st.session_state[
                                receipt_candidate_key
                            ] = receipt_id
                            st.rerun()
                    if (
                        receipt_id
                        and st.session_state.get(
                            receipt_candidate_key
                        )
                        == receipt_id
                    ):
                        st.warning(
                            f"Remove `{name}` from this transaction? "
                            "The file will remain in Google Drive."
                        )
                        cancel_column, confirm_column = st.columns(2)
                        if cancel_column.button(
                            "Cancel",
                            key=(
                                "receipt-unlink-cancel-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            st.session_state.pop(
                                receipt_candidate_key,
                                None,
                            )
                            st.rerun()
                        if confirm_column.button(
                            "Remove reference",
                            type="primary",
                            key=(
                                "receipt-unlink-confirm-"
                                f"{receipt_action_scope}-{receipt_id}"
                            ),
                            width="stretch",
                        ):
                            try:
                                context.storage.unlink_transaction_receipt(
                                    edit_id,
                                    file_id=receipt_id,
                                )
                            except StorageError as error:
                                st.error(
                                    "Receipt reference was not "
                                    "removed. "
                                    f"{error}"
                                )
                            else:
                                st.session_state.pop(
                                    receipt_candidate_key,
                                    None,
                                )
                                st.session_state[
                                    receipt_notice_key
                                ] = (
                                    f"Receipt removed: {name}. "
                                    "The file remains in Google "
                                    "Drive."
                                )
                                st.rerun()
            if references_ready:
                referenced_receipt_ids: set[str] = set()
                uninitialized_transaction_ids: set[str] = set()
                for transaction in all_transactions:
                    if transaction["id"] == edit_id:
                        referenced_receipt_ids.update(
                            receipt_ids
                        )
                        continue
                    raw_references = transaction.get(
                        "receipt_references",
                        "",
                    )
                    if raw_references == "":
                        uninitialized_transaction_ids.add(
                            transaction["id"]
                        )
                        continue
                    if raw_references == "[]":
                        continue
                    try:
                        referenced_receipt_ids.update(
                            reference["id"]
                            for reference in (
                                decode_receipt_references(
                                    raw_references
                                )
                            )
                        )
                    except StorageError:
                        uninitialized_transaction_ids.add(
                            transaction["id"]
                        )
                try:
                    profile_receipts = (
                        receipt_drive.list_profile_receipts(
                            profile_key=context.profile_key,
                            folder_id=str(receipt_folder["id"]),
                        )
                    )
                except GoogleDriveError as error:
                    st.error(
                        "Unreferenced Google Drive receipts could "
                        f"not be listed. {error}"
                    )
                else:
                    unreferenced_receipts = []
                    receipts_needing_backfill = 0
                    for receipt in profile_receipts:
                        receipt_id = str(
                            receipt.get("id", "")
                        )
                        properties = receipt.get(
                            "appProperties"
                        )
                        legacy_transaction_id = (
                            str(
                                properties.get(
                                    "tabulaRasaTransaction",
                                    "",
                                )
                            )
                            if isinstance(properties, Mapping)
                            else ""
                        )
                        if (
                            receipt_id
                            and receipt_id
                            not in referenced_receipt_ids
                            and legacy_transaction_id
                            not in (
                                uninitialized_transaction_ids
                            )
                        ):
                            try:
                                unreferenced_receipts.append(
                                    receipt_reference_from_drive_file(
                                        receipt
                                    )
                                )
                            except ReceiptManifestError:
                                receipts_needing_backfill += 1
                    if receipts_needing_backfill:
                        st.warning(
                            f"{receipts_needing_backfill} receipt(s) "
                            "need integrity metadata before they can be linked."
                        )
                    if unreferenced_receipts:
                        unreferenced_by_id = {
                            receipt["id"]: receipt
                            for receipt in unreferenced_receipts
                        }
                        existing_receipt_id = st.selectbox(
                            "Unreferenced receipt",
                            list(unreferenced_by_id),
                            format_func=lambda file_id: (
                                unreferenced_by_id[file_id][
                                    "name"
                                ]
                            ),
                            key=(
                                "receipt-existing-select-"
                                f"{receipt_action_scope}"
                            ),
                            help=(
                                "App-managed files in this "
                                "profile's receipt folder that are "
                                "not linked to another transaction."
                            ),
                        )
                        if st.button(
                            "Link selected receipt",
                            key=(
                                "receipt-existing-link-"
                                f"{receipt_action_scope}"
                            ),
                        ):
                            existing_receipt = (
                                unreferenced_by_id[
                                    existing_receipt_id
                                ]
                            )
                            try:
                                context.storage.link_transaction_receipt(
                                    edit_id,
                                    reference=existing_receipt,
                                )
                            except StorageError as error:
                                st.error(
                                    "The receipt could not be "
                                    f"linked. {error}"
                                )
                            else:
                                st.session_state[
                                    receipt_notice_key
                                ] = (
                                    "Receipt linked: "
                                    f"{existing_receipt['name']}"
                                )
                                st.rerun()
                    else:
                        st.caption(
                            "No unreferenced receipts are "
                            "available in Google Drive."
                        )
                receipt_upload = st.file_uploader(
                    "Upload receipt",
                    type=[
                        "pdf",
                        "png",
                        "jpg",
                        "jpeg",
                        "webp",
                        "heic",
                    ],
                    accept_multiple_files=False,
                    key=f"receipt-upload-{edit_id}",
                )
                if receipt_upload is not None:
                    receipt_bytes = receipt_upload.getvalue()
                    st.caption(
                        "The original filename will be kept. If "
                        "that name already exists, a numeric "
                        "suffix will be added."
                    )
                    if st.button(
                        "Upload receipt to Google Drive",
                        type="primary",
                        key=f"receipt-upload-button-{edit_id}",
                    ):
                        try:
                            uploaded_receipt = (
                                receipt_drive.upload_receipt(
                                    profile_key=(
                                        context.profile_key
                                    ),
                                    transaction_id=edit_id,
                                    folder_id=str(
                                        receipt_folder["id"]
                                    ),
                                    original_name=(
                                        receipt_upload.name
                                    ),
                                    content=receipt_bytes,
                                    mime_type=(
                                        receipt_upload.type
                                        or "application/octet-stream"
                                    ),
                                )
                            )
                        except GoogleDriveError as error:
                            st.error(str(error))
                        else:
                            try:
                                context.storage.link_transaction_receipt(
                                    edit_id,
                                    reference=(
                                        receipt_reference_from_drive_file(
                                            uploaded_receipt
                                        )
                                    ),
                                )
                            except (
                                KeyError,
                                ReceiptManifestError,
                                StorageError,
                            ) as error:
                                st.error(
                                    "The receipt was uploaded to "
                                    "Google Drive but could not be "
                                    "linked to this transaction. "
                                    f"Retry the upload. {error}"
                                )
                            else:
                                st.success(
                                    "Receipt uploaded and linked: "
                                    f"{uploaded_receipt.get('name', receipt_upload.name)}"
                                )
                                st.rerun()

