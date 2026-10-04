"""Receipt editor and post-create recovery rendering."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
import streamlit as st
from tabula_rasa.application.documents import DocumentError, DocumentValidationError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.receipt_manifest import MAX_RECEIPT_REFERENCES
from tabula_rasa.storage import StorageError
from tabula_rasa.storage import StorageNotFoundError
from .receipt_workflows import (
    RECEIPT_UPLOAD_TYPES,
    _cancel_editor_receipt_recovery,
    _configuration_changed_message,
    _editor_workflow,
    _finish_editor_receipt_workflow,
    _fresh_transaction_receipt_count,
    _fresh_transaction_receipt_references,
    _new_unresolved_receipt_count,
    _process_context_receipts,
    _receipt_folder,
    _reference_storage_key,
    _start_editor_receipt_workflow,
    _workflow_matches_configuration,
    creation_receipt_workflow,
    prepare_receipt_uploads,
    receipt_creation_counts,
    receipt_editor_upload_reset_key,
)


def render_receipt_uploader(
    *,
    key: str,
    disabled: bool = False,
    help_text: str | None = None,
) -> Sequence[Any] | None:
    """Render the shared multi-file receipt input for transaction surfaces."""
    return st.file_uploader(
        "Receipt (optional)",
        type=RECEIPT_UPLOAD_TYPES,
        accept_multiple_files=True,
        key=key,
        disabled=disabled,
        help=help_text
        or (
            "Select one or more PDF, PNG, JPG, JPEG, WEBP, or HEIC files. "
            "Each file must be non-empty and no larger than 20 MB; the "
            "selected batch must not exceed 200 MB total."
        ),
    )


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
    return render_receipt_uploader(
        key=f"receipt-upload-{transaction_id}",
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

def render_receipt_creation_recovery(context: TransactionsContext) -> bool:
    """Render the one pending post-create workflow for this profile."""
    workflow = creation_receipt_workflow(context)
    if workflow is None:
        return False
    return _render_receipt_recovery(
        context, str(workflow["transaction_id"]), _receipt_folder(context), saved=True,
    )


def _render_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
    receipt_folder: Mapping[str, object] | None,
) -> bool:
    workflow = _editor_workflow(context, transaction_id)
    # Creation recovery has its own form placement (including mixed-use).
    if workflow is not None and workflow.get("created"):
        return False
    return _render_receipt_recovery(context, transaction_id, receipt_folder, saved=False)


def _render_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
    receipt_folder: Mapping[str, object] | None,
    *,
    saved: bool,
) -> bool:
    workflow = _editor_workflow(context, transaction_id)
    if workflow is None:
        return False
    if not _workflow_matches_configuration(context, workflow, receipt_folder):
        _cancel_editor_receipt_recovery(context, transaction_id)
        st.warning(_configuration_changed_message())
        return False

    if saved:
        st.info(
            f"Transaction {transaction_id} is saved in Google Sheets. "
            "Receipt processing can be resumed independently."
        )
    _render_workflow_status(workflow, saved=saved)
    if workflow.get("receipts") and st.button(
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
            existing_ids = {_reference_storage_key(reference) for reference in fresh_references}
            if (
                len(fresh_references)
                + _new_unresolved_receipt_count(workflow["receipts"], existing_ids)
                > MAX_RECEIPT_REFERENCES
            ):
                raise DocumentValidationError(
                    "A transaction can reference no more than 100 receipts. "
                    "Remove an existing receipt reference before retrying."
                )
            if receipt_folder is None:
                raise DocumentValidationError(
                    "Connect Google Drive and configure this profile's receipt folder."
                )
            _process_context_receipts(context, workflow, receipt_folder)
            _finish_editor_receipt_workflow(context, transaction_id, workflow)
        except StorageNotFoundError:
            _cancel_editor_receipt_recovery(context, transaction_id)
            st.warning(
                "The saved transaction no longer exists. Receipt recovery was "
                "cleared; uploaded files remain available in Google Drive as "
                "unreferenced receipts."
            )
            return False
        except (DocumentError, StorageError) as error:
            workflow["error"] = str(error)
        st.rerun()
    if not saved and workflow.get("receipts") and st.button(
        "Cancel recovery",
        key=f"cancel-editor-receipts-{context.profile_key}-{transaction_id}",
    ):
        _cancel_editor_receipt_recovery(context, transaction_id)
        st.rerun()
    return True

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

def render_filtered_editor_receipt_recovery(
    context: TransactionsContext,
    transaction_id: str,
) -> bool:
    receipt_folder = _receipt_folder(context)
    return _render_editor_receipt_recovery(
        context,
        transaction_id,
        receipt_folder,
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
