"""Receipt metadata/relationship adapter for the current workbook format."""

from __future__ import annotations

from typing import Any

from tabula_rasa.application.documents import DocumentReference, ReceiptAssociation
from tabula_rasa.storage import StorageNotFoundError, StorageValidationError, decode_receipt_references
from .google_drive_documents import document_from_receipt_reference, document_to_receipt_reference


class GoogleSheetsReceiptRepository:
    """Delegate fresh mutations, cache invalidation, and pair parity to Sheets.

    A source-aware receipt facade can be supplied for mixed-use expenses, so
    it retains its expected-source check and refresh callback.
    """

    def __init__(self, profile_key: str, storage: Any) -> None:
        self.profile_key = profile_key
        self.storage = storage

    def _check_profile(self, profile_key: str) -> None:
        if profile_key != self.profile_key:
            raise StorageValidationError("Receipt metadata belongs to a different business profile.")

    def associations(self, profile_key: str, *, fresh: bool = False) -> tuple[ReceiptAssociation, ...]:
        self._check_profile(profile_key)
        return tuple(
            ReceiptAssociation(str(transaction["id"]), document_from_receipt_reference(profile_key, reference))
            for transaction in self.storage.list_transactions(_force_refresh=fresh)
            for reference in decode_receipt_references(transaction.get("receipt_references", ""))
        )

    def references(self, profile_key: str, transaction_id: str, *, fresh: bool = False) -> tuple[DocumentReference, ...]:
        self._check_profile(profile_key)
        for transaction in self.storage.list_transactions(_force_refresh=fresh):
            if str(transaction.get("id", "")) == transaction_id:
                return tuple(document_from_receipt_reference(profile_key, item) for item in decode_receipt_references(transaction.get("receipt_references", "")))
        raise StorageNotFoundError("The selected transaction no longer exists. Refresh the ledger before uploading receipts.")

    def link(self, profile_key: str, transaction_id: str, document: DocumentReference) -> None:
        self._check_profile(profile_key)
        if document.profile_key != profile_key:
            raise StorageValidationError("The receipt belongs to a different business profile.")
        self.storage.link_transaction_receipt(transaction_id, reference=document_to_receipt_reference(document))

    def unlink(self, profile_key: str, transaction_id: str, storage_key: str) -> None:
        self._check_profile(profile_key)
        self.storage.unlink_transaction_receipt(transaction_id, file_id=storage_key)
