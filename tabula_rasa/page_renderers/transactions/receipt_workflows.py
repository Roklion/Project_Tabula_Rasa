"""Receipt upload preparation, persistence, and recovery state."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import MutableMapping
import streamlit as st
from tabula_rasa.application.documents import (
    DocumentError, DocumentReference, DocumentUpload, DocumentValidationError,
    MAX_RECEIPT_UPLOAD_TOTAL_BYTES,
    RECEIPT_UPLOAD_TYPES as RECEIPT_UPLOAD_TYPES,
    UPLOADED_NOT_LINKED_MESSAGE as UPLOADED_NOT_LINKED_MESSAGE,
    prepare_receipt_uploads as prepare_document_uploads,
)
from tabula_rasa.infrastructure.receipt_context import process_context_receipts, receipt_service_for_context
from tabula_rasa.page_renderers.transactions.context import TransactionsContext

RECEIPT_CREATION_WORKFLOW_KEY = "transaction_receipt_creation_workflow"

RECEIPT_EDITOR_WORKFLOW_KEY = "transaction_receipt_editor_workflow"


def _workflow_complete(workflow: Mapping[str, Any]) -> bool:
    return not workflow.get("receipts")

def _process_context_receipts(
    context: TransactionsContext,
    workflow: MutableMapping[str, Any],
    receipt_folder: Mapping[str, object],
) -> None:
    linked_before, _ = receipt_creation_counts(workflow)
    process_context_receipts(context, workflow)
    linked_after, _ = receipt_creation_counts(workflow)
    if linked_after > linked_before:
        _mark_workbook_data_changed(context)

def _fresh_transaction_receipt_references(
    context: TransactionsContext,
    transaction_id: str,
) -> list[DocumentReference]:
    return list(receipt_service_for_context(context).references(transaction_id, fresh=True))


def _reference_storage_key(reference: object) -> str:
    if isinstance(reference, DocumentReference):
        return reference.storage_key
    # Recovery state prepared before this extraction remains resumable.
    return str(reference.get("id", "")) if isinstance(reference, Mapping) else ""

def _new_unresolved_receipt_count(
    unresolved_receipts: Sequence[Mapping[str, Any]],
    existing_receipt_ids: set[str],
) -> int:
    return sum(
        not _reference_storage_key(receipt.get("reference"))
        or _reference_storage_key(receipt["reference"]) not in existing_receipt_ids
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
            and _reference_storage_key(receipt.get("reference")) == file_id
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
    reference: DocumentReference | Mapping[str, Any],
) -> None:
    _remove_editor_receipt_from_recovery(
        context,
        transaction_id,
        _reference_storage_key(reference),
        record_linked=True,
    )

def receipt_editor_workflow_key_prefix(profile_key: str) -> str:
    return f"{RECEIPT_EDITOR_WORKFLOW_KEY}:{len(profile_key)}:{profile_key}:"

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
    scope = receipt_service_for_context(context).document_scope
    return {"id": scope} if scope else None

def receipt_editor_upload_reset_key(profile_key: str, transaction_id: str) -> str:
    return f"reset-receipt-editor:{profile_key}:{transaction_id}"

def prepare_receipt_uploads(
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int = 0,
    _max_upload_total_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Copy and validate every selected file before the Sheets write."""
    max_upload_total_bytes = (
        MAX_RECEIPT_UPLOAD_TOTAL_BYTES
        if _max_upload_total_bytes is None
        else _max_upload_total_bytes
    )
    return prepare_document_uploads(
        [DocumentUpload("", str(getattr(file, "name", "") or ""), str(getattr(file, "type", "") or "application/octet-stream"), "", file.getvalue()) for file in uploaded_files],
        existing_reference_count=existing_reference_count,
        max_upload_total_bytes=max_upload_total_bytes,
    )

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
            raise DocumentValidationError(
                "Google Drive receipt storage is not configured for this profile."
            )
        _process_context_receipts(context, workflow, receipt_folder)
    except DocumentError as error:
        workflow["error"] = str(error)
    return workflow

def receipt_creation_counts(workflow: Mapping[str, Any]) -> tuple[int, int]:
    receipts = workflow.get("receipts", [])
    return int(workflow.get("linked_count", 0)), len(receipts)

def editor_receipt_recovery_active(context: TransactionsContext) -> bool:
    prefix = receipt_editor_workflow_key_prefix(context.profile_key)
    return any(isinstance(key, str) and key.startswith(prefix) for key in st.session_state)
