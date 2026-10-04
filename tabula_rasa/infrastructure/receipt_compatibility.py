"""Historical receipt facade adapters; new page flows use neutral services."""

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import Any

from tabula_rasa.application.documents import (
    DocumentValidationError, process_pending_receipts,
)
from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file


def process_receipt_recovery(
    workflow: MutableMapping[str, Any],
    *,
    upload_receipt: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    link_receipt: Callable[[Mapping[str, Any]], object],
) -> None:
    """Reuse the neutral recovery owner with the historical callback format."""
    process_pending_receipts(
        workflow,
        upload_receipt=lambda receipt: receipt_reference_from_drive_file(upload_receipt(receipt)),
        link_receipt=link_receipt,
    )


def prepare_legacy_receipt_uploads(
    prepare: Callable[..., list[dict[str, Any]]],
    uploaded_files: Sequence[Any],
    *,
    existing_reference_count: int,
    max_upload_total_bytes: int,
) -> list[dict[str, Any]]:
    try:
        return prepare(uploaded_files, existing_reference_count=existing_reference_count, _max_upload_total_bytes=max_upload_total_bytes)
    except DocumentValidationError as error:
        raise GoogleDriveAccessError(str(error)) from error
