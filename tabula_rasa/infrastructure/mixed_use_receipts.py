"""Transitional source-aware receipt context for the existing document adapter."""

from collections.abc import Mapping


class MixedUseReceiptStorage:
    """Narrow receipt-storage capability scoped to one source record."""

    def __init__(
        self,
        storage,
        source_id: str,
        expected_source: Mapping[str, object],
        on_source_changed=None,
        source_service=None,
    ):
        self._storage = storage
        from tabula_rasa.infrastructure.google_sheets_mixed_use import (
            mixed_use_service_for_storage,
        )

        self._source_service = (
            source_service
            if source_service is not None
            else mixed_use_service_for_storage(storage)
        )
        self._source_id = source_id
        self._expected_source = expected_source
        self._on_source_changed = on_source_changed

    def _refresh_expected_source(self) -> None:
        refreshed_source = self._source_service.get(self._source_id)
        self._expected_source = {
            **self._expected_source,
            "receipt_references": refreshed_source.get("receipt_references", ""),
        }
        if self._on_source_changed is not None:
            self._on_source_changed(self._expected_source)

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def link_transaction_receipt(self, transaction_id, *, reference):
        result = self._source_service.link_receipt(
            self._source_id, reference=reference, expected_source=self._expected_source
        )
        self._refresh_expected_source()
        return result

    def unlink_transaction_receipt(self, transaction_id, *, file_id):
        result = self._source_service.unlink_receipt(
            self._source_id, file_id=file_id, expected_source=self._expected_source
        )
        self._refresh_expected_source()
        return result
