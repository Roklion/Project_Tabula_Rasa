"""Receipt upload, linking, and manual recovery workflows."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any, MutableMapping

import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
    GoogleDriveError,
    validate_receipt_upload,
)
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import (
    MAX_RECEIPT_REFERENCES,
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    StorageError,
    StorageNotFoundError,
)


RECEIPT_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "heic"]
RECEIPT_CREATION_WORKFLOW_KEY = "transaction_receipt_creation_workflow"
RECEIPT_EDITOR_WORKFLOW_KEY = "transaction_receipt_editor_workflow"
MAX_RECEIPT_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024
UPLOADED_NOT_LINKED_MESSAGE = (
    "The receipt is uploaded in Google Drive but could not be linked in Google "
    "Sheets. If it is not already linked, the file remains available from "
    "Unreferenced receipts."
)


def receipt_creation_workflow_key(profile_key: str) -> str:
    return f"{RECEIPT_CREATION_WORKFLOW_KEY}:{profile_key}"


def receipt_editor_workflow_key(profile_key: str, transaction_id: str) -> str:
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:{transaction_id}"


def receipt_editor_workflow_key_prefix(profile_key: str) -> str:
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:"


def receipt_editor_upload_reset_key(profile_key: str, transaction_id: str) -> str:
    return f"reset-receipt-editor:{profile_key}:{transaction_id}"


def prepare_receipt_uploads(
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int = 0,
) -> list[dict[str, Any]]:
    """Copy and validate every selected file before the Sheets write."""
    if existing_reference_count < 0:
        raise ValueError("Existing receipt reference count cannot be negative")
    if existing_reference_count + len(uploaded_files) > MAX_RECEIPT_REFERENCES:
        raise GoogleDriveAccessError(
            "A transaction can reference no more than 100 receipts. "
            "Remove an existing receipt reference or select fewer files."
        )
    prepared: list[dict[str, Any]] = []
    total_bytes = 0
    for index, uploaded_file in enumerate(uploaded_files):
        name = str(getattr(uploaded_file, "name", "") or "")
        content = uploaded_file.getvalue()
        total_bytes += len(content)
        if total_bytes > MAX_RECEIPT_UPLOAD_TOTAL_BYTES:
            raise GoogleDriveAccessError(
                "Selected receipt files cannot exceed 200 MB total. "
                "Select fewer or smaller files."
            )
        validate_receipt_upload(name, content)
        content_sha256 = hashlib.sha256(content).hexdigest()
        prepared.append(
            {
                "key": f"{index}:{content_sha256}",
                "receipt_id": secrets.token_hex(16),
                "sha256": content_sha256,
                "original_name": name,
                "mime_type": str(
                    getattr(uploaded_file, "type", "")
                    or "application/octet-stream"
                ),
                "content": content,
                "reference": None,
                "error": "",
            }
        )
    return prepared


def new_receipt_creation_workflow(
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    *,
    spreadsheet_id: str = "",
    receipt_folder_id: str = "",
    mixed_use_source_id: str = "",
) -> dict[str, Any]:
    """Create the minimal state needed to resume unresolved receipt work."""
    workflow: dict[str, Any] = {
        "transaction_id": transaction_id,
        "spreadsheet_id": spreadsheet_id,
        "receipt_folder_id": receipt_folder_id,
        "linked_count": 0,
        "receipts": [dict(receipt) for receipt in receipts],
        "error": "",
    }
    if mixed_use_source_id:
        workflow["mixed_use_source_id"] = mixed_use_source_id
    return workflow


def process_receipt_recovery(
    workflow: MutableMapping[str, Any],
    *,
    upload_receipt: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    link_receipt: Callable[[Mapping[str, Any]], object],
) -> None:
    """Process each pending receipt once and retain only unresolved work."""
    unresolved: list[dict[str, Any]] = []
    linked_count = int(workflow.get("linked_count", 0))
    for pending in workflow.get("receipts", []):
        if not isinstance(pending, Mapping):
            continue
        receipt = dict(pending)
        reference = receipt.get("reference")
        if not isinstance(reference, Mapping):
            try:
                drive_file = upload_receipt(receipt)
                reference = receipt_reference_from_drive_file(drive_file)
            except Exception as error:  # noqa: BLE001 - retain resumable input
                receipt["error"] = str(error)
                unresolved.append(receipt)
                continue
            receipt["reference"] = dict(reference)
            receipt["content"] = b""
        try:
            link_receipt(reference)
        except Exception as error:  # noqa: BLE001 - Drive file remains recoverable
            receipt["error"] = f"{UPLOADED_NOT_LINKED_MESSAGE} {error}"
            unresolved.append(receipt)
        else:
            linked_count += 1
    workflow["linked_count"] = linked_count
    workflow["receipts"] = unresolved


def receipt_creation_counts(workflow: Mapping[str, Any]) -> tuple[int, int]:
    receipts = workflow.get("receipts", [])
    return int(workflow.get("linked_count", 0)), len(receipts)


def _receipt_folder(context: TransactionsContext) -> Mapping[str, object] | None:
    drive_settings = context.profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        return None
    receipt_folder = drive_settings.get("receipt_folder")
    return receipt_folder if isinstance(receipt_folder, Mapping) else None


def _workflow_matches_configuration(
    context: TransactionsContext,
    workflow: Mapping[str, Any],
    receipt_folder: Mapping[str, object] | None,
) -> bool:
    """Require the exact workbook and Drive folder that created the workflow."""
    return (
        str(workflow.get("spreadsheet_id", ""))
        == str(context.profile_secrets.get("spreadsheet_id", ""))
        and str(workflow.get("receipt_folder_id", ""))
        == str((receipt_folder or {}).get("id", ""))
    )


def _configuration_changed_message() -> str:
    return (
        "The profile's Google Sheets workbook or Drive receipt folder changed, "
        "so the pending receipt workflow was cleared. Uploaded files remain in "
        "Google Drive as unreferenced receipts; select any local-only files again."
    )


def _mark_workbook_data_changed(context: TransactionsContext) -> None:
    callback = getattr(context, "mark_workbook_data_changed", None)
    if callable(callback):
        callback()


def _process_context_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    linked_before, _ = receipt_creation_counts(workflow)
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
            folder_id=folder_id,
            original_name=str(receipt["original_name"]),
            content=bytes(receipt["content"]),
            mime_type=str(receipt["mime_type"]),
            receipt_id=str(receipt["receipt_id"]),
        ),
        link_receipt=lambda reference: context.storage.link_transaction_receipt(
            transaction_id,
            reference=reference,
        ),
    )
    linked_after, _ = receipt_creation_counts(workflow)
    if linked_after > linked_before:
        _mark_workbook_data_changed(context)


def _editor_workflow(
    context: TransactionsContext,
    transaction_id: str,
) -> MutableMapping[str, Any] | None:
    workflow = st.session_state.get(
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    )
    return workflow if isinstance(workflow, MutableMapping) else None


def _workflow_complete(workflow: Mapping[str, Any]) -> bool:
    return not workflow.get("receipts")


def _fresh_transaction_receipt_references(
    context: TransactionsContext,
    transaction_id: str,
) -> list[dict[str, Any]]:
    for transaction in context.storage.list_transactions(_force_refresh=True):
        if str(transaction.get("id", "")) == transaction_id:
            return decode_receipt_references(
                transaction.get("receipt_references", "")
            )
    raise StorageNotFoundError(
        "The selected transaction no longer exists. Refresh the ledger before "
        "uploading receipts."
    )


def _fresh_transaction_receipt_count(
    context: TransactionsContext,
    transaction_id: str,
) -> int:
    return len(_fresh_transaction_receipt_references(context, transaction_id))


def _new_unresolved_receipt_count(
    unresolved_receipts: Sequence[Mapping[str, Any]],
    existing_receipt_ids: set[str],
) -> int:
    return sum(
        not isinstance(receipt.get("reference"), Mapping)
        or str(receipt["reference"].get("id", "")) not in existing_receipt_ids
        for receipt in unresolved_receipts
    )


def _start_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    receipt_folder: Mapping[str, object],
) -> MutableMapping[str, Any]:
    workflow = new_receipt_creation_workflow(
        transaction_id,
        receipts,
        spreadsheet_id=str(context.profile_secrets.get("spreadsheet_id", "")),
        receipt_folder_id=str(receipt_folder.get("id", "")),
    )
    st.session_state[
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    ] = workflow
    try:
        _process_context_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["error"] = str(error)
    return workflow


def _finish_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    workflow: MutableMapping[str, Any],
) -> bool:
    if not _workflow_complete(workflow):
        return False
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )
    context.schedule_widget_reset(
        receipt_editor_upload_reset_key(context.profile_key, transaction_id)
    )
    return True


def _cancel_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )
    context.schedule_widget_reset(
        receipt_editor_upload_reset_key(context.profile_key, transaction_id)
    )


def _render_workflow_status(workflow: Mapping[str, Any], *, saved: bool) -> None:
    linked, unresolved = receipt_creation_counts(workflow)
    if unresolved:
        prefix = "The transaction is saved: " if saved else ""
        st.warning(
            f"{prefix}{linked} receipt(s) complete and {unresolved} receipt(s) "
            "unresolved."
        )
        for receipt in workflow.get("receipts", []):
            if isinstance(receipt, Mapping) and receipt.get("error"):
                st.caption(
                    f"{receipt.get('original_name', 'Receipt')}: {receipt['error']}"
                )
    if workflow.get("error"):
        st.error(str(workflow["error"]))


def _render_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
    receipt_folder: Mapping[str, object] | None,
    *,
    retry_available: bool = True,
) -> bool:
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return False
    if not _workflow_matches_configuration(context, workflow, receipt_folder):
        _cancel_editor_receipt_recovery(context, transaction_id)
        st.warning(_configuration_changed_message())
        return False

    _render_workflow_status(workflow, saved=False)
    if retry_available and workflow.get("receipts") and st.button(
        "Retry unresolved receipts",
        type="primary",
        key=f"retry-editor-receipts-{context.profile_key}-{transaction_id}",
    ):
        workflow["error"] = ""
        try:
            fresh_references = _fresh_transaction_receipt_references(
                context,
                transaction_id,
            )
            existing_ids = {str(reference["id"]) for reference in fresh_references}
            if (
                len(fresh_references)
                + _new_unresolved_receipt_count(workflow["receipts"], existing_ids)
                > MAX_RECEIPT_REFERENCES
            ):
                raise GoogleDriveAccessError(
                    "A transaction can reference no more than 100 receipts. "
                    "Remove an existing receipt reference before retrying."
                )
            if receipt_folder is None:
                raise GoogleDriveAccessError(
                    "Connect Google Drive and configure this profile's receipt folder."
                )
            _process_context_receipts(context, workflow, receipt_folder)
            _finish_editor_receipt_workflow(context, transaction_id, workflow)
        except (GoogleDriveError, StorageError) as error:
            workflow["error"] = str(error)
        st.rerun()
    if workflow.get("receipts") and st.button(
        "Cancel recovery",
        key=f"cancel-editor-receipts-{context.profile_key}-{transaction_id}",
    ):
        _cancel_editor_receipt_recovery(context, transaction_id)
        st.rerun()
    return True


def render_editor_receipt_uploader(
    context: TransactionsContext,
    transaction_id: str,
) -> Sequence[Any] | None:
    receipt_folder = _receipt_folder(context)
    if receipt_folder is None or not receipt_folder.get("id"):
        return None
    if _editor_workflow(context, transaction_id) is not None:
        return None
    context.reset_widget_state_if_requested(
        receipt_editor_upload_reset_key(context.profile_key, transaction_id),
        keys=(f"receipt-upload-{transaction_id}",),
    )
    return st.file_uploader(
        "Upload receipt",
        type=RECEIPT_UPLOAD_TYPES,
        accept_multiple_files=True,
        key=f"receipt-upload-{transaction_id}",
        help=(
            "Select one or more PDF, PNG, JPG, JPEG, WEBP, or HEIC files. "
            "Each file must be non-empty and no larger than 20 MB; the "
            "selected batch must not exceed 200 MB total."
        ),
    )


def prepare_editor_receipt_uploads(
    context: TransactionsContext,
    transaction_id: str,
    uploaded_files: Sequence[Any],
) -> list[dict[str, Any]]:
    return prepare_receipt_uploads(
        uploaded_files,
        existing_reference_count=_fresh_transaction_receipt_count(
            context,
            transaction_id,
        ),
    )


def process_editor_receipt_uploads(
    context: TransactionsContext,
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    receipt_folder: Mapping[str, object],
) -> None:
    workflow = _start_editor_receipt_workflow(
        context,
        transaction_id,
        receipts,
        receipt_folder,
    )
    _finish_editor_receipt_workflow(context, transaction_id, workflow)


def clear_missing_editor_receipt_recoveries(
    context: TransactionsContext,
    transactions: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Clear workflows whose profile storage or target no longer matches."""
    transaction_ids = {
        str(transaction.get("id", ""))
        for transaction in transactions
        if str(transaction.get("id", ""))
    }
    notices: list[str] = []
    prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    receipt_folder = _receipt_folder(context)
    for key in list(st.session_state):
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        workflow = st.session_state.get(key)
        if not isinstance(workflow, Mapping):
            st.session_state.pop(key, None)
            continue
        transaction_id = str(workflow.get("transaction_id", ""))
        if not _workflow_matches_configuration(context, workflow, receipt_folder):
            _cancel_editor_receipt_recovery(context, transaction_id)
            notices.append(_configuration_changed_message())
        elif transaction_id not in transaction_ids:
            _cancel_editor_receipt_recovery(context, transaction_id)
            notices.append(
                "The transaction no longer exists. Uploaded files remain in "
                "Google Drive and can be linked as unreferenced receipts."
            )
    return notices


def editor_receipt_recovery_active(context: TransactionsContext) -> bool:
    prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    return any(isinstance(key, str) and key.startswith(prefix) for key in st.session_state)


def editor_receipt_recovery_transaction_ids(
    context: TransactionsContext,
) -> list[str]:
    prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    transaction_ids = {
        str(workflow.get("transaction_id", ""))
        for key in list(st.session_state)
        if isinstance(key, str)
        and key.startswith(prefix)
        and isinstance((workflow := st.session_state.get(key)), Mapping)
        and str(workflow.get("transaction_id", ""))
    }
    return sorted(transaction_ids)


def render_filtered_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> bool:
    receipt_folder = _receipt_folder(context)
    retry_available = receipt_folder is not None
    if retry_available:
        try:
            context.get_drive_client(
                context.profile_key,
                context.configuration_revision,
            )
        except GoogleDriveError as error:
            st.error(str(error))
            retry_available = False
    return _render_editor_receipt_recovery(
        context,
        transaction_id,
        receipt_folder,
        retry_available=retry_available,
    )


def finish_receipt_creation_if_complete(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
) -> bool:
    if not _workflow_complete(workflow):
        return False
    linked, _ = receipt_creation_counts(workflow)
    st.session_state.pop(receipt_creation_workflow_key(context.profile_key), None)
    context.schedule_widget_reset("reset_add_transaction_form")
    st.session_state["write_success_notice"] = (
        f"Transaction saved and {linked} receipt(s) linked."
    )
    return True


def clear_receipt_creation_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    workflow = st.session_state.get(receipt_creation_workflow_key(context.profile_key))
    if isinstance(workflow, Mapping) and str(workflow.get("transaction_id", "")) == str(
        transaction_id
    ):
        st.session_state.pop(receipt_creation_workflow_key(context.profile_key), None)
    st.session_state.pop(
        receipt_editor_workflow_key(context.profile_key, transaction_id),
        None,
    )


def handle_confirmed_transaction_receipts(
    context: TransactionsContext,
    transaction: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    mixed_use_source_id: str = "",
) -> None:
    receipt_folder = _receipt_folder(context)
    workflow = new_receipt_creation_workflow(
        str(transaction["id"]),
        receipts,
        spreadsheet_id=str(context.profile_secrets.get("spreadsheet_id", "")),
        receipt_folder_id=str((receipt_folder or {}).get("id", "")),
        mixed_use_source_id=mixed_use_source_id,
    )
    st.session_state[receipt_creation_workflow_key(context.profile_key)] = workflow
    if receipt_folder is None:
        workflow["error"] = (
            "Google Drive receipt storage is not configured for this profile."
        )
        return
    try:
        _process_context_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["error"] = str(error)
    finish_receipt_creation_if_complete(context, workflow)


def render_receipt_creation_recovery(context: TransactionsContext) -> bool:
    """Render the one pending post-create workflow for this profile."""
    key = receipt_creation_workflow_key(context.profile_key)
    workflow = st.session_state.get(key)
    if not isinstance(workflow, MutableMapping):
        return False
    transaction_id = str(workflow.get("transaction_id", ""))
    receipt_folder = _receipt_folder(context)
    if not transaction_id:
        st.session_state.pop(key, None)
        return False
    if not _workflow_matches_configuration(context, workflow, receipt_folder):
        st.session_state.pop(key, None)
        st.warning(_configuration_changed_message())
        return False

    st.info(
        f"Transaction {transaction_id} is saved in Google Sheets. "
        "Receipt processing can be resumed independently."
    )
    _render_workflow_status(workflow, saved=True)
    if workflow.get("receipts") and st.button(
        "Retry unresolved receipts",
        type="primary",
        key=f"retry-receipts-{transaction_id}",
    ):
        workflow["error"] = ""
        try:
            _fresh_transaction_receipt_references(context, transaction_id)
            if receipt_folder is None:
                raise GoogleDriveAccessError(
                    "Connect Google Drive and configure this profile's receipt folder."
                )
            _process_context_receipts(context, workflow, receipt_folder)
        except StorageNotFoundError:
            st.session_state.pop(key, None)
            context.schedule_widget_reset("reset_add_transaction_form")
            st.warning(
                "The saved transaction no longer exists. Receipt recovery was "
                "cleared; uploaded files remain available in Google Drive as "
                "unreferenced receipts."
            )
            return False
        except (GoogleDriveError, StorageError) as error:
            workflow["error"] = str(error)
        finish_receipt_creation_if_complete(context, workflow)
        st.rerun()
    return True


def _record_editor_receipt_linked(
    context: TransactionsContext,
    transaction_id: str,
    reference: Mapping[str, Any],
) -> bool:
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return False
    file_id = str(reference.get("id", ""))
    remaining = [
        receipt
        for receipt in workflow.get("receipts", [])
        if not (
            isinstance(receipt, Mapping)
            and isinstance(receipt.get("reference"), Mapping)
            and str(receipt["reference"].get("id", "")) == file_id
        )
    ]
    if len(remaining) == len(workflow.get("receipts", [])):
        return False
    workflow["receipts"] = remaining
    workflow["linked_count"] = int(workflow.get("linked_count", 0)) + 1
    return _finish_editor_receipt_workflow(context, transaction_id, workflow)


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
            retry_available=False,
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
            retry_available=False,
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
            if not _record_editor_receipt_linked(
                context,
                edit_id,
                existing_receipt,
            ):
                st.session_state[notice_key] = (
                    f"Receipt linked: {existing_receipt['name']}"
                )
            st.rerun()
