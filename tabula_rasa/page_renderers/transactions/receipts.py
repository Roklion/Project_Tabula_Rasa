"""Compatibility facade for transaction receipt workflows and rendering."""

from collections.abc import Sequence
from typing import Any

from .receipt_display import render_receipts
from .receipt_editor import (
    prepare_editor_receipt_uploads,
    process_editor_receipt_uploads,
    render_receipt_uploader,
    render_editor_receipt_uploader,
    render_filtered_editor_receipt_recovery,
    render_receipt_creation_recovery,
)
from .receipt_workflows import (
    MAX_RECEIPT_UPLOAD_TOTAL_BYTES,
    RECEIPT_CREATION_WORKFLOW_KEY,
    RECEIPT_EDITOR_WORKFLOW_KEY,
    RECEIPT_UPLOAD_TYPES,
    UPLOADED_NOT_LINKED_MESSAGE,
    _cancel_editor_receipt_recovery,
    _fresh_transaction_receipt_count,
    _process_context_receipts,
    _receipt_folder,
    _record_editor_receipt_linked,
    clear_missing_editor_receipt_recoveries,
    clear_receipt_creation_recovery,
    editor_receipt_recovery_active,
    editor_receipt_recovery_transaction_ids,
    handle_confirmed_transaction_receipts,
    new_receipt_creation_workflow,
    prepare_receipt_uploads as _prepare_receipt_uploads,
    process_receipt_recovery,
    receipt_creation_counts,
    receipt_creation_workflow_key,
    receipt_editor_upload_reset_key,
    receipt_editor_workflow_key,
    receipt_editor_workflow_key_prefix,
)


def prepare_receipt_uploads(
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int = 0,
) -> list[dict[str, Any]]:
    """Preserve the facade's historical patchable upload-limit attribute."""
    return _prepare_receipt_uploads(
        uploaded_files,
        existing_reference_count=existing_reference_count,
        _max_upload_total_bytes=MAX_RECEIPT_UPLOAD_TOTAL_BYTES,
    )

__all__ = [
    "MAX_RECEIPT_UPLOAD_TOTAL_BYTES",
    "RECEIPT_CREATION_WORKFLOW_KEY",
    "RECEIPT_EDITOR_WORKFLOW_KEY",
    "RECEIPT_UPLOAD_TYPES",
    "UPLOADED_NOT_LINKED_MESSAGE",
    "receipt_creation_counts",
    "receipt_creation_workflow_key",
    "receipt_editor_workflow_key",
    "receipt_editor_workflow_key_prefix",
    "receipt_editor_upload_reset_key",
    "prepare_receipt_uploads",
    "new_receipt_creation_workflow",
    "process_receipt_recovery",
    "render_editor_receipt_uploader",
    "render_receipt_uploader",
    "prepare_editor_receipt_uploads",
    "process_editor_receipt_uploads",
    "clear_missing_editor_receipt_recoveries",
    "editor_receipt_recovery_active",
    "editor_receipt_recovery_transaction_ids",
    "render_filtered_editor_receipt_recovery",
    "clear_receipt_creation_recovery",
    "handle_confirmed_transaction_receipts",
    "render_receipt_creation_recovery",
    "render_receipts",
    "_cancel_editor_receipt_recovery",
    "_fresh_transaction_receipt_count",
    "_process_context_receipts",
    "_receipt_folder",
    "_record_editor_receipt_linked",
]
