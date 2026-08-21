"""Receipt management for an existing transaction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Callable, MutableMapping

import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveError,
    validate_receipt_upload,
)
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import StorageError, decode_receipt_references


RECEIPT_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "heic"]
RECEIPT_CREATION_WORKFLOW_KEY = "transaction_receipt_creation_workflow"


def receipt_creation_workflow_key(profile_key: str) -> str:
    """Return the session key for one profile's in-progress recovery."""
    return f"{RECEIPT_CREATION_WORKFLOW_KEY}:{profile_key}"


def prepare_receipt_uploads(uploaded_files: Sequence[object]) -> list[dict[str, Any]]:
    """Copy and validate every selected file before the Sheets write."""
    prepared: list[dict[str, Any]] = []
    for index, uploaded_file in enumerate(uploaded_files):
        name = str(getattr(uploaded_file, "name", "") or "")
        content = uploaded_file.getvalue()
        validate_receipt_upload(name, content)
        prepared.append(
            {
                "key": f"{index}:{hashlib.sha256(content).hexdigest()}",
                "original_name": name,
                "mime_type": str(
                    getattr(uploaded_file, "type", "")
                    or "application/octet-stream"
                ),
                "content": content,
                "linked": False,
                "reference": None,
                "drive_file": None,
                "error": "",
            }
        )
    return prepared


def new_receipt_creation_workflow(
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    *,
    profile_key: str = "",
) -> dict[str, Any]:
    """Create session-only recovery state after a confirmed Sheets write."""
    return {
        "profile_key": profile_key,
        "transaction_id": transaction_id,
        "receipts": [dict(receipt) for receipt in receipts],
    }


def process_receipt_recovery(
    workflow: MutableMapping[str, Any],
    *,
    upload_receipt: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    link_receipt: Callable[[Mapping[str, Any]], object],
) -> None:
    """Upload and link unresolved receipts, retaining only retry pointers."""
    for receipt in workflow.get("receipts", []):
        if not isinstance(receipt, MutableMapping):
            continue
        if receipt.get("linked") is True:
            continue
        reference = receipt.get("reference")
        if not isinstance(reference, Mapping) and isinstance(
            receipt.get("drive_file"), Mapping
        ):
            try:
                reference = receipt_reference_from_drive_file(receipt["drive_file"])
            except Exception as error:  # noqa: BLE001 - preserve Drive recovery pointer
                receipt["error"] = (
                    "The Drive file was uploaded, but its receipt metadata "
                    f"could not be read: {error}"
                )
                continue
            receipt["reference"] = reference
        if not isinstance(reference, Mapping):
            try:
                drive_file = dict(upload_receipt(receipt))
            except Exception as error:  # noqa: BLE001 - keep other receipts moving
                receipt["error"] = str(error)
                continue
            receipt["drive_file"] = drive_file
            try:
                reference = receipt_reference_from_drive_file(drive_file)
            except Exception as error:  # noqa: BLE001 - preserve Drive recovery pointer
                receipt["error"] = (
                    "The Drive file was uploaded, but its receipt metadata "
                    f"could not be read: {error}"
                )
                continue
            receipt["reference"] = reference
        try:
            link_receipt(reference)
        except Exception as error:  # noqa: BLE001 - retain uploaded file for retry
            receipt["error"] = str(error)
        else:
            receipt["linked"] = True
            receipt["error"] = ""


def receipt_creation_counts(workflow: Mapping[str, Any]) -> tuple[int, int]:
    """Return linked and unresolved receipt counts."""
    receipts = workflow.get("receipts", [])
    linked = sum(item.get("linked") is True for item in receipts)
    unresolved = len(receipts) - linked
    return linked, unresolved


def _receipt_folder(context: TransactionsContext) -> Mapping[str, object] | None:
    drive_settings = context.profile_secrets.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    return receipt_folder if isinstance(receipt_folder, Mapping) else None


def _process_context_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    receipt_drive = context.get_drive_client(
        context.profile_key,
        context.configuration_revision,
    )
    transaction_id = str(workflow["transaction_id"])
    folder_id = str(receipt_folder["id"])
    process_receipt_recovery(
        workflow,
        upload_receipt=lambda receipt: receipt_drive.upload_receipt(
            profile_key=context.profile_key,
            transaction_id=transaction_id,
            folder_id=folder_id,
            original_name=str(receipt["original_name"]),
            content=bytes(receipt["content"]),
            mime_type=str(receipt["mime_type"]),
        ),
        link_receipt=lambda reference: context.storage.link_transaction_receipt(
            transaction_id,
            reference=reference,
        ),
    )


def _workflow_complete(workflow: Mapping[str, Any]) -> bool:
    return receipt_creation_counts(workflow)[1] == 0


def finish_receipt_creation_if_complete(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
) -> bool:
    """Clear successful recovery state and schedule the form reset."""
    if not _workflow_complete(workflow):
        return False
    linked, _unresolved = receipt_creation_counts(workflow)
    st.session_state.pop(
        receipt_creation_workflow_key(context.profile_key),
        None,
    )
    context.schedule_widget_reset("reset_add_transaction_form")
    notice = (
        f"Transaction saved and {linked} receipt(s) linked."
    )
    st.session_state["receipt_creation_success_notice"] = notice
    st.session_state["write_success_notice"] = notice
    return True


def handle_confirmed_transaction_receipts(
    context: TransactionsContext,
    transaction: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    """Upload/link selected receipts after the Sheets write is confirmed."""
    workflow = new_receipt_creation_workflow(
        str(transaction["id"]),
        receipts,
        profile_key=context.profile_key,
    )
    st.session_state[receipt_creation_workflow_key(context.profile_key)] = workflow
    receipt_folder = _receipt_folder(context)
    if receipt_folder is None:
        workflow["configuration_error"] = (
            "Google Drive receipt storage is not configured for this profile."
        )
        return
    try:
        _process_context_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["configuration_error"] = str(error)
    finish_receipt_creation_if_complete(context, workflow)


def _render_receipt_workflow_status(workflow: Mapping[str, Any]) -> None:
    linked, unresolved = receipt_creation_counts(workflow)
    if unresolved:
        st.warning(
            f"The transaction is saved: {linked} receipt(s) complete and "
            f"{unresolved} receipt(s) unresolved. Click Retry unresolved "
            "receipts to continue."
        )
        for receipt in workflow.get("receipts", []):
            if receipt.get("linked") is not True and receipt.get("error"):
                st.caption(
                    f"{receipt.get('original_name', 'Receipt')}: "
                    f"{receipt['error']}"
                )


def render_receipt_creation_recovery(context: TransactionsContext) -> bool:
    """Render and optionally resume the current session's receipt recovery."""
    workflow = st.session_state.get(
        receipt_creation_workflow_key(context.profile_key)
    )
    if not isinstance(workflow, MutableMapping):
        return False
    transaction_id = str(workflow.get("transaction_id", ""))
    if not transaction_id:
        st.session_state.pop(
            receipt_creation_workflow_key(context.profile_key),
            None,
        )
        return False
    st.info(
        f"Transaction {transaction_id} is saved in Google Sheets. "
        "Receipt processing can be resumed independently."
    )
    if workflow.get("configuration_error"):
        st.error(str(workflow["configuration_error"]))
    _render_receipt_workflow_status(workflow)
    if not _workflow_complete(workflow) and st.button(
        "Retry unresolved receipts",
        type="primary",
        key=f"retry-receipts-{transaction_id}",
    ):
        receipt_folder = _receipt_folder(context)
        if receipt_folder is None:
            st.error(
                "Connect Google Drive and configure the profile's receipt "
                "folder before retrying."
            )
        else:
            workflow.pop("configuration_error", None)
            try:
                _process_context_receipts(context, workflow, receipt_folder)
            except GoogleDriveError as error:
                workflow["configuration_error"] = str(error)
            if finish_receipt_creation_if_complete(context, workflow):
                st.rerun()
            else:
                st.rerun()
    return True


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
            receipt_link_recovery_key = (
                f"receipt-link-recovery-{receipt_action_scope}"
            )
            receipt_notice = st.session_state.pop(
                receipt_notice_key,
                None,
            )
            if receipt_notice:
                st.success(str(receipt_notice))
            link_recovery = st.session_state.get(receipt_link_recovery_key)
            recovery_reference: Mapping[str, object] | None = None
            if isinstance(link_recovery, Mapping):
                candidate_reference = link_recovery.get("reference")
                if isinstance(candidate_reference, Mapping):
                    recovery_reference = candidate_reference
                if isinstance(recovery_reference, Mapping):
                    st.warning(
                        "This receipt is already uploaded to Google Drive. "
                        "Retry linking the existing file before uploading another copy. "
                        f"{link_recovery.get('error', '')}"
                    )
                    if st.button(
                        "Retry linking uploaded receipt",
                        type="primary",
                        key=(
                            "receipt-link-retry-"
                            f"{receipt_action_scope}"
                        ),
                    ):
                        try:
                            context.storage.link_transaction_receipt(
                                edit_id,
                                reference=recovery_reference,
                            )
                        except StorageError as error:
                            st.error(
                                "The existing receipt could not be linked. "
                                f"{error}"
                            )
                        else:
                            st.session_state.pop(
                                receipt_link_recovery_key,
                                None,
                            )
                            st.session_state[receipt_notice_key] = (
                                "Receipt linked: "
                                f"{recovery_reference['name']}"
                            )
                            st.rerun()

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
                                if isinstance(
                                    recovery_reference,
                                    Mapping,
                                ) and recovery_reference.get("id") == (
                                    existing_receipt_id
                                ):
                                    st.session_state.pop(
                                        receipt_link_recovery_key,
                                        None,
                                    )
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
                receipt_upload = None
                if not isinstance(
                    link_recovery,
                    Mapping,
                ):
                    receipt_upload = st.file_uploader(
                        "Upload receipt",
                        type=RECEIPT_UPLOAD_TYPES,
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
                                uploaded_reference = (
                                    receipt_reference_from_drive_file(
                                        uploaded_receipt
                                    )
                                )
                                context.storage.link_transaction_receipt(
                                    edit_id,
                                    reference=uploaded_reference,
                                )
                            except (
                                KeyError,
                                ReceiptManifestError,
                                StorageError,
                            ) as error:
                                if "uploaded_reference" in locals():
                                    st.session_state[receipt_link_recovery_key] = {
                                        "reference": uploaded_reference,
                                        "error": str(error),
                                    }
                                    st.rerun()
                                st.error(
                                    "The receipt was uploaded to Google Drive "
                                    "but its integrity metadata could not be "
                                    "linked. Use the Unreferenced receipt "
                                    f"workflow. {error}"
                                )
                            else:
                                st.success(
                                    "Receipt uploaded and linked: "
                                    f"{uploaded_receipt.get('name', receipt_upload.name)}"
                                )
                                st.rerun()
