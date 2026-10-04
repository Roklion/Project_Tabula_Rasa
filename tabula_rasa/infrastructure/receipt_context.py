"""Temporary bridge for receipt contexts while legacy page storage is removed."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from tabula_rasa.application.documents import DocumentValidationError, ReceiptService
from .google_drive_documents import GoogleDriveDocumentStore, document_from_receipt_reference
from .google_sheets_receipts import GoogleSheetsReceiptRepository


def receipt_service_for_context(context: Any) -> ReceiptService:
    services = getattr(context, "services", None)
    service = getattr(services, "receipts", None)
    if isinstance(service, ReceiptService):
        if service.profile_key != context.profile_key:
            raise DocumentValidationError("Receipt services belong to a different business profile.")
        # Mixed-use pages bind their legacy source-aware adapter to the same
        # document store. Ordinary contexts use the assembled graph directly.
        if isinstance(service.repository, GoogleSheetsReceiptRepository) and service.repository.storage is not context.storage:
            return service.with_repository(GoogleSheetsReceiptRepository(context.profile_key, context.storage))
        return service
    settings = context.profile_secrets.get("google_drive")
    folder = settings.get("receipt_folder") if isinstance(settings, Mapping) else None
    folder_id = str(folder.get("id", "")) if isinstance(folder, Mapping) else ""
    return ReceiptService(
        context.profile_key,
        GoogleSheetsReceiptRepository(context.profile_key, context.storage),
        GoogleDriveDocumentStore(context.profile_key, folder_id, lambda: context.get_drive_client(context.profile_key, context.configuration_revision)),
    )


def process_context_receipts(context: Any, workflow: MutableMapping[str, Any]) -> None:
    """Convert pre-extraction session references once, then use neutral recovery."""
    for receipt in workflow.get("receipts", []):
        if isinstance(receipt, MutableMapping) and isinstance(receipt.get("reference"), Mapping):
            receipt["reference"] = document_from_receipt_reference(context.profile_key, receipt["reference"])
    receipt_service_for_context(context).process_recovery(workflow)
