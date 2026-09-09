"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.receipt_manifest import validate_receipt_reference
from .errors import (
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    _mutation_guidance,
)
from .validation import (
    _clean_text,
    _encode_receipt_references,
    decode_receipt_references,
)
from .base import (
    _MIXED_USE_CREATE_LOCK,
    _StoredRow,
)

class ReceiptsMixin:
    """Mixin for the receipts storage boundary."""

    def _replace_receipt_references(
        self,
        current: _StoredRow,
        encoded_references: str,
    ) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            return self._replace_receipt_references_locked(
                current, encoded_references
            )

    def _replace_receipt_references_locked(
        self,
        current: _StoredRow,
        encoded_references: str,
    ) -> dict[str, str]:
        """Replace receipt references while preserving mixed-use row parity."""
        transaction = current.values
        source_type = _clean_text(
            transaction.get("source_type"), "Transaction source type"
        )
        source_id = _clean_text(transaction.get("source_id"), "Transaction source ID")
        if bool(source_type) != bool(source_id):
            raise StorageValidationError(
                "Transaction source type and source ID must be provided together"
            )
        if not source_type:
            updated = dict(transaction)
            updated["receipt_references"] = encoded_references
            self._replace_row("Transactions", current, updated)
            return updated
        if source_type != MIXED_USE_SOURCE_TYPE:
            raise StorageValidationError(
                "Transaction source type and source ID are invalid"
            )
        source = self._find_row("MixedUseExpenses", source_id)
        transaction_id = _clean_text(transaction.get("id"), "Transaction ID", required=True)
        if source.values.get("linked_transaction_id") != transaction_id:
            raise StorageValidationError(
                "Mixed-use source and projection IDs do not match"
            )
        if str(source.values.get("receipt_references") or "") != str(
            transaction.get("receipt_references") or ""
        ):
            raise StorageConflictError(
                "The mixed-use receipt references changed; refresh before retrying."
            )
        fresh_transaction = self._find_row("Transactions", transaction_id)
        fresh_source = self._find_row("MixedUseExpenses", source_id)
        if not self._mixed_use_record_matches(
            "Transactions", fresh_transaction.values, transaction
        ) or not self._mixed_use_record_matches(
            "MixedUseExpenses", fresh_source.values, source.values
        ):
            raise StorageConflictError(
                "The mixed-use receipt pair changed; refresh before retrying."
            )
        current = fresh_transaction
        transaction = fresh_transaction.values
        source = fresh_source
        original_transaction_receipts = str(
            transaction.get("receipt_references") or ""
        )
        original_source_receipts = str(
            source.values.get("receipt_references") or ""
        )
        original_transaction = dict(transaction)
        original_source = dict(source.values)

        def build_requests(
            transaction_row: _StoredRow, source_row: _StoredRow
        ) -> list[dict[str, Any]]:
            return [
                self._managed_update_request(
                    "Transactions",
                    transaction_row,
                    "receipt_references",
                    encoded_references,
                ),
                self._managed_update_request(
                    "MixedUseExpenses",
                    source_row,
                    "receipt_references",
                    encoded_references,
                ),
            ]

        requests = build_requests(current, source)

        def refresh_requests() -> None:
            nonlocal current, source, requests
            current = self._find_row("Transactions", transaction_id)
            source = self._find_row("MixedUseExpenses", source_id)
            if not self._mixed_use_record_matches(
                "Transactions", current.values, original_transaction
            ) or not self._mixed_use_record_matches(
                "MixedUseExpenses", source.values, original_source
            ):
                raise StorageConflictError(
                    "The mixed-use receipt pair changed while the update was being retried."
                )
            requests = build_requests(current, source)

        def state() -> str:
            snapshot = self._snapshot(
                ["Transactions", "MixedUseExpenses"], force_refresh=True
            )
            confirmed_transaction = self._managed_rows_by_id(
                snapshot["Transactions"], "Transactions"
            ).get(transaction_id)
            confirmed_source = self._managed_rows_by_id(
                snapshot["MixedUseExpenses"], "MixedUseExpenses"
            ).get(source_id)
            if confirmed_transaction is None or confirmed_source is None:
                return "ambiguous"
            transaction_receipts = str(
                confirmed_transaction.values.get("receipt_references") or ""
            )
            source_receipts = str(
                confirmed_source.values.get("receipt_references") or ""
            )
            if transaction_receipts == encoded_references and source_receipts == encoded_references:
                return "applied"
            if transaction_receipts == original_transaction_receipts and source_receipts == original_source_receipts:
                return "unchanged"
            return "ambiguous"

        self._write_with_uncertain_readback(
            "mixed-use receipt update",
            lambda: self._batch_update_spreadsheet(requests),
            state,
            before_retry=refresh_requests,
            invalidate=("Transactions", "MixedUseExpenses"),
        )
        updated = dict(transaction)
        updated["receipt_references"] = encoded_references
        return updated

    def set_transaction_receipt_references(
        self,
        transaction_id: str,
        references: Any,
        *,
        expected_transaction: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Replace the Drive receipt references attached to one transaction."""
        with _MIXED_USE_CREATE_LOCK:
            transaction_id = _clean_text(transaction_id, "ID", required=True)
            transaction_rows = self._managed_rows_by_id(
                self._rows("Transactions", force_refresh=True),
                "Transactions",
            )
            current = transaction_rows.get(transaction_id)
            if current is None:
                raise StorageNotFoundError("Transaction no longer exists")
            self._reject_mixed_use_projection(current.values)
            encoded_references = _encode_receipt_references(references)
            self._reject_receipt_ownership_conflict(
                encoded_references,
                transaction_id=transaction_id,
                transactions=(row.values for row in transaction_rows.values()),
            )
            if expected_transaction is not None and not self._mixed_use_record_matches(
                "Transactions", current.values, expected_transaction
            ):
                raise StorageConflictError(
                    "The transaction changed; refresh before changing receipts."
                )
            return self._replace_receipt_references(
                current, encoded_references
            )

    def _mixed_use_receipt_pair(
        self,
        source_id: str,
        *,
        expected_source: Mapping[str, Any] | None = None,
    ) -> tuple[_StoredRow, _StoredRow]:
        """Freshly resolve a source/projection pair for receipt orchestration."""
        source_id = _clean_text(source_id, "Mixed-use source ID", required=True)
        source = self._find_row("MixedUseExpenses", source_id)
        transaction_id = _clean_text(
            source.values.get("linked_transaction_id"),
            "Linked transaction ID",
            required=True,
        )
        transaction = self._find_row("Transactions", transaction_id)
        if transaction.values.get("source_type") != MIXED_USE_SOURCE_TYPE or (
            transaction.values.get("source_id") != source_id
        ):
            raise StorageValidationError(
                "Mixed-use source and projection IDs do not match"
            )
        if expected_source is not None and not self._mixed_use_source_matches(
            source.values, expected_source, transaction.values
        ):
            raise StorageConflictError(
                "The mixed-use expense changed; refresh before changing receipts."
            )
        if str(source.values.get("receipt_references") or "") != str(
            transaction.values.get("receipt_references") or ""
        ):
            raise StorageConflictError(
                "The mixed-use receipt pair changed; refresh before retrying."
            )
        return source, transaction

    def set_mixed_use_receipt_references(
        self,
        source_id: str,
        references: Any,
        *,
        expected_source: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Replace paired receipt references through a source-aware path."""
        with _MIXED_USE_CREATE_LOCK:
            _source, transaction = self._mixed_use_receipt_pair(
                source_id, expected_source=expected_source
            )
            encoded = _encode_receipt_references(references)
            self._reject_receipt_ownership_conflict(
                encoded, transaction_id=transaction.values["id"]
            )
            return self._replace_receipt_references(transaction, encoded)

    def link_transaction_receipt(
        self,
        transaction_id: str,
        *,
        file_id: str = "",
        name: str = "",
        reference: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Attach or refresh one Drive file reference on a transaction."""
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Transactions", transaction_id)
            self._reject_mixed_use_projection(current.values)
            try:
                normalized_reference = validate_receipt_reference(
                    reference if reference is not None else {"id": file_id, "name": name}
                )
            except ReceiptManifestError as exc:
                raise StorageValidationError(str(exc)) from exc
            for transaction in self.list_transactions(_force_refresh=True):
                if transaction["id"] == transaction_id:
                    continue
                if any(
                    item["id"] == normalized_reference["id"]
                    for item in decode_receipt_references(
                        transaction.get("receipt_references", "")
                    )
                ):
                    raise StorageConflictError(
                        "That receipt is already linked to another transaction"
                    )
            references = decode_receipt_references(
                current.values.get("receipt_references", "")
            )
            references = [
                item
                for item in references
                if item["id"] != normalized_reference["id"]
            ]
            references.append(normalized_reference)
            return self._replace_receipt_references(
                current, _encode_receipt_references(references)
            )

    def link_mixed_use_receipt(
        self,
        source_id: str,
        *,
        reference: Mapping[str, Any],
        expected_source: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Link one receipt while authorizing the mixed-use source pair."""
        with _MIXED_USE_CREATE_LOCK:
            try:
                normalized = validate_receipt_reference(reference)
            except ReceiptManifestError as exc:
                raise StorageValidationError(str(exc)) from exc
            _source, transaction = self._mixed_use_receipt_pair(
                source_id, expected_source=expected_source
            )
            self._reject_receipt_ownership_conflict(
                _encode_receipt_references([normalized]),
                transaction_id=transaction.values["id"],
            )
            references = decode_receipt_references(
                transaction.values.get("receipt_references", "")
            )
            references = [
                item for item in references if item["id"] != normalized["id"]
            ]
            references.append(normalized)
            return self._replace_receipt_references(
                transaction, _encode_receipt_references(references)
            )

    def remap_transaction_receipt(
        self,
        transaction_id: str,
        *,
        old_file_id: str,
        reference: Mapping[str, Any],
    ) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            return self._remap_transaction_receipt(
                transaction_id, old_file_id=old_file_id, reference=reference
            )

    def _remap_transaction_receipt(
        self,
        transaction_id: str,
        *,
        old_file_id: str,
        reference: Mapping[str, Any],
    ) -> dict[str, str]:
        """Replace one recovered old Drive ID with a verified new reference."""
        current = self._find_row("Transactions", transaction_id)
        self._reject_mixed_use_projection(current.values)
        try:
            normalized_reference = validate_receipt_reference(
                reference,
                allow_legacy=False,
            )
        except ReceiptManifestError as exc:
            raise StorageValidationError(str(exc)) from exc
        transactions = self.list_transactions(_force_refresh=True)
        for transaction in transactions:
            if transaction["id"] == transaction_id:
                continue
            if any(
                item["id"] == normalized_reference["id"]
                for item in decode_receipt_references(
                    transaction.get("receipt_references", "")
                )
            ):
                raise StorageConflictError(
                    "That receipt is already linked to another transaction"
                )
        references = decode_receipt_references(
            current.values.get("receipt_references", "")
        )
        replacement_indexes = [
            index
            for index, item in enumerate(references)
            if item["id"] in {str(old_file_id), normalized_reference["id"]}
            or (
                item.get("receipt_id") == normalized_reference["receipt_id"]
                and item.get("sha256") == normalized_reference["sha256"]
            )
        ]
        if not replacement_indexes:
            raise StorageNotFoundError(
                "The transaction no longer contains the receipt being recovered"
            )
        first_index = replacement_indexes[0]
        retained = [
            item
            for index, item in enumerate(references)
            if index not in replacement_indexes
        ]
        retained.insert(first_index, normalized_reference)
        return self._replace_receipt_references(
            current, _encode_receipt_references(retained)
        )

    def remap_mixed_use_receipt(
        self,
        source_id: str,
        *,
        old_file_id: str,
        reference: Mapping[str, Any],
        expected_source: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Replace a recovered receipt through the source-aware path."""
        with _MIXED_USE_CREATE_LOCK:
            try:
                normalized = validate_receipt_reference(
                    reference, allow_legacy=False
                )
            except ReceiptManifestError as exc:
                raise StorageValidationError(str(exc)) from exc
            _source, transaction = self._mixed_use_receipt_pair(
                source_id, expected_source=expected_source
            )
            self._reject_receipt_ownership_conflict(
                _encode_receipt_references([normalized]),
                transaction_id=transaction.values["id"],
            )
            references = decode_receipt_references(
                transaction.values.get("receipt_references", "")
            )
            indexes = [
                index
                for index, item in enumerate(references)
                if item["id"] in {str(old_file_id), normalized["id"]}
                or (
                    item.get("receipt_id") == normalized.get("receipt_id")
                    and item.get("sha256") == normalized.get("sha256")
                )
            ]
            if not indexes:
                raise StorageNotFoundError(
                    "The mixed-use receipt is no longer available for recovery"
                )
            first = indexes[0]
            retained = [
                item for index, item in enumerate(references) if index not in indexes
            ]
            retained.insert(first, normalized)
            return self._replace_receipt_references(
                transaction, _encode_receipt_references(retained)
            )

    def apply_receipt_recovery_plan(
        self,
        expected_transactions: Sequence[Mapping[str, Any]],
        updates: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> tuple[bool, list[dict[str, str]]]:
        with _MIXED_USE_CREATE_LOCK:
            return self._apply_receipt_recovery_plan(
                expected_transactions, updates
            )

    def _apply_receipt_recovery_plan(
        self,
        expected_transactions: Sequence[Mapping[str, Any]],
        updates: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> tuple[bool, list[dict[str, str]]]:
        """Apply receipt-cell updates when the live receipt snapshot is unchanged.

        A fresh full transaction read authorizes both cached no-op conclusions
        and the write. Only receipt-reference cells are written, in one batch,
        to reduce the remaining read/write race and preserve unrelated manual
        edits. When receipt state drifted, the fresh snapshot is returned for
        the caller's next bounded reconciliation attempt.
        """
        current_rows = self._rows("Transactions", force_refresh=True)
        current_transactions = [dict(row.values) for row in current_rows]

        expected_by_id = {
            str(transaction["id"]): transaction
            for transaction in expected_transactions
        }
        current_by_id = {
            str(transaction["id"]): transaction
            for transaction in current_transactions
        }
        if len(expected_by_id) != len(expected_transactions) or len(
            current_by_id
        ) != len(current_transactions):
            raise StorageValidationError(
                "Receipt recovery found duplicate live transaction IDs."
            )

        expected_receipts = {
            transaction_id: str(
                transaction.get("receipt_references") or ""
            )
            for transaction_id, transaction in expected_by_id.items()
        }
        current_receipts = {
            transaction_id: str(
                transaction.get("receipt_references") or ""
            )
            for transaction_id, transaction in current_by_id.items()
        }
        intended_values = {
            str(transaction_id): _encode_receipt_references(references)
            for transaction_id, references in updates.items()
        }
        expected_after_updates = dict(expected_receipts)
        if any(transaction_id not in expected_after_updates for transaction_id in intended_values):
            return False, current_transactions
        expected_after_updates.update(intended_values)
        if current_receipts not in (expected_receipts, expected_after_updates):
            return False, current_transactions

        rows_by_id = {
            str(row.values["id"]): row for row in current_rows
        }
        unknown = sorted(set(updates) - set(rows_by_id))
        if unknown:
            raise StorageNotFoundError(
                "A transaction disappeared during receipt recovery."
            )
        mixed_source_ids: set[str] = set()
        for transaction_id in intended_values:
            transaction = current_by_id[transaction_id]
            source_type = _clean_text(
                transaction.get("source_type"),
                "Transaction source type",
            )
            source_id = _clean_text(
                transaction.get("source_id"),
                "Transaction source ID",
            )
            if bool(source_type) != bool(source_id):
                raise StorageValidationError(
                    "Receipt recovery found incomplete transaction provenance."
                )
            if not source_type:
                expected_source_type = _clean_text(
                    expected_by_id[transaction_id].get("source_type"),
                    "Expected transaction source type",
                )
                expected_source_id = _clean_text(
                    expected_by_id[transaction_id].get("source_id"),
                    "Expected transaction source ID",
                )
                if expected_source_type or expected_source_id:
                    return False, current_transactions
                continue
            if source_type != MIXED_USE_SOURCE_TYPE:
                raise StorageValidationError(
                    "Receipt recovery found invalid transaction provenance."
                )
            mixed_source_ids.add(source_id)

        mixed_source_rows: dict[str, _StoredRow] = {}
        if mixed_source_ids:
            source_rows = self._rows("MixedUseExpenses", force_refresh=True)
            for row in source_rows:
                source_id = _clean_text(row.values.get("id"), "Mixed-use source ID")
                if source_id in mixed_source_ids:
                    if source_id in mixed_source_rows:
                        raise StorageValidationError(
                            "Receipt recovery found duplicate mixed-use source IDs."
                        )
                    mixed_source_rows[source_id] = row
            for source_id in mixed_source_ids:
                if source_id not in mixed_source_rows:
                    raise StorageValidationError(
                        "Receipt recovery found a missing mixed-use source."
                    )
            for transaction_id in intended_values:
                transaction = current_by_id[transaction_id]
                source_id = _clean_text(
                    transaction.get("source_id"), "Transaction source ID"
                )
                if not source_id:
                    continue
                source_row = mixed_source_rows.get(source_id)
                if source_row is None:
                    raise AssertionError("Mixed-use source lookup lost a validated ID")
                if source_row.values.get("linked_transaction_id") != transaction_id:
                    raise StorageValidationError(
                        "Receipt recovery found a mismatched mixed-use projection."
                    )
                if str(source_row.values.get("receipt_references") or "") != str(
                    transaction.get("receipt_references") or ""
                ):
                    latest_rows = self._rows("Transactions", force_refresh=True)
                    return False, [dict(row.values) for row in latest_rows]

            latest_snapshot = self._snapshot(
                ["Transactions", "MixedUseExpenses"], force_refresh=True
            )
            latest_transaction_rows = latest_snapshot["Transactions"]
            latest_transactions_by_id: dict[str, _StoredRow] = {}
            for row in latest_transaction_rows:
                transaction_id = _clean_text(
                    row.values.get("id"), "Transaction ID", required=True
                )
                if transaction_id in latest_transactions_by_id:
                    raise StorageValidationError(
                        "Receipt recovery found duplicate live transaction IDs."
                    )
                latest_transactions_by_id[transaction_id] = row
            latest_transactions = [
                dict(row.values) for row in latest_transaction_rows
            ]
            latest_receipts = {
                transaction_id: str(row.values.get("receipt_references") or "")
                for transaction_id, row in latest_transactions_by_id.items()
            }
            if latest_receipts not in (current_receipts, expected_after_updates):
                return False, latest_transactions
            latest_source_rows = latest_snapshot["MixedUseExpenses"]
            latest_sources_by_id: dict[str, _StoredRow] = {}
            for row in latest_source_rows:
                source_id = _clean_text(
                    row.values.get("id"), "Mixed-use source ID", required=True
                )
                if source_id in latest_sources_by_id:
                    raise StorageValidationError(
                        "Receipt recovery found duplicate mixed-use source IDs."
                    )
                latest_sources_by_id[source_id] = row
            for source_id, source_row in mixed_source_rows.items():
                latest_source = latest_sources_by_id.get(source_id)
                if latest_source is None or latest_source.values != source_row.values:
                    return False, latest_transactions
            current_rows = latest_transaction_rows
            current_transactions = latest_transactions
            current_by_id = {
                str(transaction["id"]): transaction
                for transaction in current_transactions
            }
            rows_by_id = latest_transactions_by_id
            mixed_source_rows = {
                source_id: latest_sources_by_id[source_id]
                for source_id in mixed_source_rows
            }

        if not intended_values:
            return True, current_transactions

        headers = self._headers("Transactions")
        transaction_reference_column = self._sheet_column_index(
            headers, "receipt_references"
        )
        transaction_sheet_id = self._transactions_sheet_id()
        source_reference_column: int | None = None
        source_sheet_id: int | None = None
        if mixed_source_rows:
            source_headers = self._headers("MixedUseExpenses")
            source_reference_column = self._sheet_column_index(
                source_headers, "receipt_references"
            )
            source_sheet_id = self._sheet_id("MixedUseExpenses")
        requests: list[dict[str, Any]] = []
        transaction_batch: list[dict[str, Any]] = []
        transaction_reference_column_number = transaction_reference_column + 1
        transaction_column_name = ""
        while transaction_reference_column_number:
            transaction_reference_column_number, remainder = divmod(
                transaction_reference_column_number - 1, 26
            )
            transaction_column_name = chr(65 + remainder) + transaction_column_name
        for transaction_id, value in intended_values.items():
            current_transaction = current_by_id[transaction_id]
            if str(current_transaction.get("receipt_references") or "") != value:
                transaction_batch.append(
                    {
                        "range": (
                            f"{transaction_column_name}"
                            f"{rows_by_id[transaction_id].row_number}"
                        ),
                        "values": [[value]],
                    }
                )
                requests.append(
                    {
                        "updateCells": {
                            "range": {
                                "sheetId": transaction_sheet_id,
                                "startRowIndex": rows_by_id[transaction_id].row_number - 1,
                                "endRowIndex": rows_by_id[transaction_id].row_number,
                                "startColumnIndex": transaction_reference_column,
                                "endColumnIndex": transaction_reference_column + 1,
                            },
                            "rows": [
                                {"values": [{"userEnteredValue": {"stringValue": value}}]}
                            ],
                            "fields": "userEnteredValue",
                        }
                    }
                )
            source_id = _clean_text(
                current_transaction.get("source_id"), "Transaction source ID"
            )
            if not source_id:
                continue
            source_row = mixed_source_rows[source_id]
            if str(source_row.values.get("receipt_references") or "") == value:
                continue
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": source_sheet_id,
                            "startRowIndex": source_row.row_number - 1,
                            "endRowIndex": source_row.row_number,
                            "startColumnIndex": source_reference_column,
                            "endColumnIndex": source_reference_column + 1,
                        },
                        "rows": [
                            {"values": [{"userEnteredValue": {"stringValue": value}}]}
                        ],
                        "fields": "userEnteredValue",
                    }
                }
            )
        if not requests:
            return True, current_transactions
        try:
            if mixed_source_rows:
                self._batch_update_spreadsheet(requests)
            else:
                self._api(
                    lambda: self._worksheet("Transactions").batch_update(
                        transaction_batch, raw=True
                    ),
                    retry_safe=False,
                )
        except StorageUnavailableError as error:
            confirmed_rows = self._rows("Transactions", force_refresh=True)
            confirmed_by_id = {
                str(row.values["id"]): row.values for row in confirmed_rows
            }
            confirmed_transactions = [
                dict(row.values) for row in confirmed_rows
            ]
            if len(confirmed_by_id) != len(confirmed_rows):
                if error.retryable:
                    return False, confirmed_transactions
                raise StorageValidationError(
                    "Receipt recovery found duplicate live transaction IDs."
                )
            confirmed_sources: dict[str, dict[str, str]] = {}
            if mixed_source_rows:
                try:
                    confirmed_source_rows = self._rows(
                        "MixedUseExpenses", force_refresh=True
                    )
                except StorageError as read_error:
                    self._invalidate("Transactions")
                    self._invalidate("MixedUseExpenses")
                    raise StorageUnavailableError(
                        _mutation_guidance("receipt recovery"), retryable=False
                    ) from read_error
                confirmed_sources = {
                    str(row.values["id"]): dict(row.values)
                    for row in confirmed_source_rows
                }
            def mixed_source_receipts_confirmed() -> bool:
                for transaction_id, value in intended_values.items():
                    source_id = _clean_text(
                        current_by_id[transaction_id].get("source_id"),
                        "Transaction source ID",
                    )
                    if not source_id:
                        continue
                    if (
                        source_id not in confirmed_sources
                        or str(
                            confirmed_sources[source_id].get("receipt_references")
                            or ""
                        )
                        != value
                    ):
                        return False
                return True

            if all(
                transaction_id in confirmed_by_id
                and
                str(
                    confirmed_by_id[transaction_id].get(
                        "receipt_references"
                    )
                    or ""
                )
                == value
                for transaction_id, value in intended_values.items()
            ) and mixed_source_receipts_confirmed():
                self._invalidate("Transactions")
                if mixed_source_rows:
                    self._invalidate("MixedUseExpenses")
                return True, confirmed_transactions
            if error.retryable:
                self._invalidate("Transactions")
                if mixed_source_rows:
                    self._invalidate("MixedUseExpenses")
                return False, confirmed_transactions
            raise
        self._invalidate("Transactions")
        if mixed_source_rows:
            self._invalidate("MixedUseExpenses")
        return True, current_transactions

    def unlink_transaction_receipt(
        self,
        transaction_id: str,
        *,
        file_id: str,
    ) -> dict[str, str]:
        """Remove one Drive reference without modifying the Drive file."""
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Transactions", transaction_id)
            self._reject_mixed_use_projection(current.values)
            references = decode_receipt_references(
                current.values.get("receipt_references", "")
            )
            retained = [
                item for item in references if item["id"] != str(file_id)
            ]
            if retained == references:
                if _clean_text(current.values.get("source_type"), "Transaction source type"):
                    return self._replace_receipt_references(
                        current, _encode_receipt_references(references)
                    )
                return dict(current.values)
            return self._replace_receipt_references(
                current, _encode_receipt_references(retained)
            )

    def unlink_mixed_use_receipt(
        self,
        source_id: str,
        *,
        file_id: str,
        expected_source: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Remove one receipt reference through the source-aware path."""
        with _MIXED_USE_CREATE_LOCK:
            _source, transaction = self._mixed_use_receipt_pair(
                source_id, expected_source=expected_source
            )
            references = decode_receipt_references(
                transaction.values.get("receipt_references", "")
            )
            retained = [
                item for item in references if item["id"] != str(file_id)
            ]
            return self._replace_receipt_references(
                transaction, _encode_receipt_references(retained)
            )

__all__ = ["ReceiptsMixin"]
