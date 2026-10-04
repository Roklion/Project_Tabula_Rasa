"""Resolve supplied receipt services and bind mixed-use source ownership."""

from collections.abc import Mapping, MutableMapping
from typing import Any

from tabula_rasa.receipt_records import (
    document_from_receipt_reference,
    document_to_receipt_reference,
)
from .documents import DocumentValidationError, ReceiptRepository, ReceiptService


def receipt_service_for_context(context: Any) -> ReceiptService:
    service = context.services.receipts
    if service.profile_key != context.profile_key:
        raise DocumentValidationError("Receipt services belong to a different business profile.")
    return service


def process_context_receipts(context: Any, workflow: MutableMapping[str, Any]) -> None:
    """Keep already prepared session references resumable through the service."""
    for receipt in workflow.get("receipts", []):
        if isinstance(receipt, MutableMapping) and isinstance(receipt.get("reference"), Mapping):
            receipt["reference"] = document_from_receipt_reference(context.profile_key, receipt["reference"])
    receipt_service_for_context(context).process_recovery(workflow)


class MixedUseReceiptRepository:
    """Bind existing source-aware receipt mutations to the neutral receipt port."""

    def __init__(
        self,
        repository: ReceiptRepository,
        source_service,
        source_id: str,
        expected_source: Mapping[str, object],
        on_source_changed=None,
    ):
        self._repository = repository
        self._source_service = source_service
        self._source_id = source_id
        self._expected_source = expected_source
        self._on_source_changed = on_source_changed

    def associations(self, profile_key, *, fresh=False):
        return self._repository.associations(profile_key, fresh=fresh)

    def references(self, profile_key, transaction_id, *, fresh=False):
        return self._repository.references(profile_key, transaction_id, fresh=fresh)

    def _refresh_expected_source(self) -> None:
        refreshed_source = self._source_service.get(self._source_id)
        self._expected_source = {
            **self._expected_source,
            "receipt_references": refreshed_source.get("receipt_references", ""),
        }
        if self._on_source_changed is not None:
            self._on_source_changed(self._expected_source)

    def link(self, profile_key, transaction_id, document):
        result = self._source_service.link_receipt(
            self._source_id,
            reference=document_to_receipt_reference(document),
            expected_source=self._expected_source,
        )
        self._refresh_expected_source()
        return result

    def unlink(self, profile_key, transaction_id, storage_key):
        result = self._source_service.unlink_receipt(
            self._source_id, file_id=storage_key, expected_source=self._expected_source
        )
        self._refresh_expected_source()
        return result
