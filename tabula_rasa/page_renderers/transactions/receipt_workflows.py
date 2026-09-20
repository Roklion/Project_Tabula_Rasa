"""Receipt upload preparation, persistence, and recovery state."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import MutableMapping
import streamlit as st
from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.google_drive import validate_receipt_upload
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import MAX_RECEIPT_REFERENCES
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file
from tabula_rasa.storage import decode_receipt_references
from tabula_rasa.storage import StorageNotFoundError

RECEIPT_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "heic"]

RECEIPT_CREATION_WORKFLOW_KEY = "transaction_receipt_creation_workflow"

RECEIPT_EDITOR_WORKFLOW_KEY = "transaction_receipt_editor_workflow"

MAX_RECEIPT_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024

UPLOADED_NOT_LINKED_MESSAGE = (
    "The receipt is uploaded in Google Drive but could not be linked in Google "
    "Sheets. If it is not already linked, the file remains available from "
    "Unreferenced receipts."
)

def _workflow_complete(workflow: Mapping[str, Any]) -> bool:
    return not workflow.get("receipts")

def _process_context_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    linked_before, _ = receipt_creation_counts(workflow)
    receipt_drive = None
    transaction_id = str(workflow["transaction_id"])
    folder_id = str(receipt_folder["id"])

    def upload_receipt(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal receipt_drive
        if receipt_drive is None:
            receipt_drive = context.get_drive_client(
                context.profile_key,
                context.configuration_revision,
            )
        return receipt_drive.upload_receipt(
            profile_key=context.profile_key,
            folder_id=folder_id,
            original_name=str(receipt["original_name"]),
            content=bytes(receipt["content"]),
            mime_type=str(receipt["mime_type"]),
            receipt_id=str(receipt["receipt_id"]),
        )

    process_receipt_recovery(
        workflow,
        upload_receipt=upload_receipt,
        link_receipt=lambda reference: context.storage.link_transaction_receipt(
            transaction_id,
            reference=reference,
        ),
    )
    linked_after, _ = receipt_creation_counts(workflow)
    if linked_after > linked_before:
        _mark_workbook_data_changed(context)

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

def _new_unresolved_receipt_count(
    unresolved_receipts: Sequence[Mapping[str, Any]],
    existing_receipt_ids: set[str],
) -> int:
    return sum(
        not isinstance(receipt.get("reference"), Mapping)
        or str(receipt["reference"].get("id", "")) not in existing_receipt_ids
        for receipt in unresolved_receipts
    )

def _remove_editor_receipt_from_recovery(
    context: TransactionsContext,
    transaction_id: str,
    file_id: str,
    *,
    record_linked: bool = False,
) -> None:
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return
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
        return
    workflow["receipts"] = remaining
    if record_linked:
        workflow["linked_count"] = int(workflow.get("linked_count", 0)) + 1
    _finish_editor_receipt_workflow(context, transaction_id, workflow)

def _mark_workbook_data_changed(context: TransactionsContext) -> None:
    callback = getattr(context, "mark_workbook_data_changed", None)
    if callable(callback):
        callback()

def _fresh_transaction_receipt_count(
    context: TransactionsContext,
    transaction_id: str,
) -> int:
    return len(_fresh_transaction_receipt_references(context, transaction_id))

def _editor_workflow(
    context: TransactionsContext,
    transaction_id: str,
) -> MutableMapping[str, Any] | None:
    workflow = st.session_state.get(
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    )
    return workflow if isinstance(workflow, MutableMapping) else None

def _record_editor_receipt_linked(
    context: TransactionsContext,
    transaction_id: str,
    reference: Mapping[str, Any],
) -> None:
    _remove_editor_receipt_from_recovery(
        context,
        transaction_id,
        str(reference.get("id", "")),
        record_linked=True,
    )

def receipt_editor_workflow_key_prefix(profile_key: str) -> str:
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:"

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

def _configuration_changed_message() -> str:
    return (
        "The profile's Google Sheets workbook or Drive receipt folder changed, "
        "so the pending receipt workflow was cleared. Uploaded files remain in "
        "Google Drive as unreferenced receipts; select any local-only files again."
    )

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

def clear_receipt_creation_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    _cancel_editor_receipt_recovery(context, transaction_id)


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

def handle_confirmed_transaction_receipts(
    context: TransactionsContext,
    transaction: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    mixed_use_source_id: str = "",
) -> None:
    transaction_id = str(transaction["id"])
    # This form pointer holds no recovery data; the transaction key owns it all.
    st.session_state[receipt_creation_workflow_key(context.profile_key)] = transaction_id
    workflow = _start_editor_receipt_workflow(
        context, transaction_id, receipts, _receipt_folder(context),
    )
    workflow["created"] = True
    if mixed_use_source_id:
        workflow["mixed_use_source_id"] = mixed_use_source_id
    _finish_editor_receipt_workflow(context, transaction_id, workflow)


def creation_receipt_workflow(context: TransactionsContext) -> MutableMapping[str, Any] | None:
    transaction_id = st.session_state.get(receipt_creation_workflow_key(context.profile_key))
    return _editor_workflow(context, str(transaction_id)) if transaction_id else None


def _cancel_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> None:
    st.session_state.pop(receipt_editor_workflow_key(context.profile_key, transaction_id), None)
    pointer = receipt_creation_workflow_key(context.profile_key)
    if st.session_state.get(pointer) == transaction_id:
        st.session_state.pop(pointer, None)
        context.schedule_widget_reset("reset_add_transaction_form")
    else:
        context.schedule_widget_reset(
            receipt_editor_upload_reset_key(context.profile_key, transaction_id)
        )


def _finish_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    workflow: MutableMapping[str, Any],
) -> bool:
    if not _workflow_complete(workflow):
        return False
    _cancel_editor_receipt_recovery(context, transaction_id)
    if workflow.get("created"):
        linked, _ = receipt_creation_counts(workflow)
        st.session_state["write_success_notice"] = (
            f"Transaction saved and {linked} receipt(s) linked."
        )
    return True


def receipt_creation_workflow_key(profile_key: str) -> str:
    return f"{RECEIPT_CREATION_WORKFLOW_KEY}:{profile_key}"

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
        # The mixed-use tab owns source/projection existence checks and messages.
        if workflow.get("mixed_use_source_id"):
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

def receipt_editor_workflow_key(profile_key: str, transaction_id: str) -> str:
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:{transaction_id}"

def _receipt_folder(context: TransactionsContext) -> Mapping[str, object] | None:
    drive_settings = context.profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        return None
    receipt_folder = drive_settings.get("receipt_folder")
    return receipt_folder if isinstance(receipt_folder, Mapping) else None

def receipt_editor_upload_reset_key(profile_key: str, transaction_id: str) -> str:
    return f"reset-receipt-editor:{profile_key}:{transaction_id}"

def prepare_receipt_uploads(
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int = 0,
    _max_upload_total_bytes: int | None = None,
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
    max_upload_total_bytes = (
        MAX_RECEIPT_UPLOAD_TOTAL_BYTES
        if _max_upload_total_bytes is None
        else _max_upload_total_bytes
    )
    total_bytes = 0
    for index, uploaded_file in enumerate(uploaded_files):
        name = str(getattr(uploaded_file, "name", "") or "")
        content = uploaded_file.getvalue()
        total_bytes += len(content)
        if total_bytes > max_upload_total_bytes:
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

def _start_editor_receipt_workflow(
    context: TransactionsContext,
    transaction_id: str,
    receipts: Sequence[Mapping[str, Any]],
    receipt_folder: Mapping[str, object] | None,
) -> MutableMapping[str, Any]:
    workflow = new_receipt_creation_workflow(
        transaction_id,
        receipts,
        spreadsheet_id=str(context.profile_secrets.get("spreadsheet_id", "")),
        receipt_folder_id=str((receipt_folder or {}).get("id", "")),
    )
    st.session_state[
        receipt_editor_workflow_key(context.profile_key, transaction_id)
    ] = workflow
    try:
        if receipt_folder is None:
            raise GoogleDriveAccessError(
                "Google Drive receipt storage is not configured for this profile."
            )
        _process_context_receipts(context, workflow, receipt_folder)
    except GoogleDriveError as error:
        workflow["error"] = str(error)
    return workflow

def receipt_creation_counts(workflow: Mapping[str, Any]) -> tuple[int, int]:
    receipts = workflow.get("receipts", [])
    return int(workflow.get("linked_count", 0)), len(receipts)

def editor_receipt_recovery_active(context: TransactionsContext) -> bool:
    prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    return any(isinstance(key, str) and key.startswith(prefix) for key in st.session_state)
