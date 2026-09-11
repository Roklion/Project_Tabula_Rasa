"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any
from uuid import uuid4
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.mixed_use import MixedUseAllocationError
from tabula_rasa.mixed_use import validate_mixed_use_allocation
from .schema import (
    MIXED_USE_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
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
    _iso_date,
    _normalize_tag_ids,
    _utc_now,
    _validate_mixed_use_tables,
    decode_receipt_references,
    mixed_use_ledger_description,
)

class _MixedUseMixin:
    """Mixin for the mixed use storage boundary."""

    def _raw_mixed_use_snapshot(
        self,
        *,
        force_refresh: bool = True,
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        snapshot = self._snapshot(
            ["MixedUseExpenses", "Transactions"], force_refresh=force_refresh
        )
        sources: dict[str, dict[str, str]] = {}
        for row in snapshot["MixedUseExpenses"]:
            source = dict(row.values)
            source_id = _clean_text(
                source.get("id"), "Mixed-use source ID", required=True
            )
            if source_id in sources:
                raise StorageValidationError("Mixed-use source IDs must be unique")
            sources[source_id] = source
        transactions: dict[str, dict[str, str]] = {}
        for row in snapshot["Transactions"]:
            transaction = dict(row.values)
            transaction_id = _clean_text(
                transaction.get("id"), "Transaction ID", required=True
            )
            if transaction_id in transactions:
                raise StorageValidationError("Transaction IDs must be unique")
            transactions[transaction_id] = transaction
        return sources, transactions

    def _validate_mixed_use_references(
        self,
        source: Mapping[str, Any],
        *,
        accounts: Mapping[str, Mapping[str, Any]] | None = None,
        categories: Mapping[str, Mapping[str, str]] | None = None,
        payees: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        accounts = accounts or self._account_lookup(force_refresh=True)
        categories = categories or self._category_lookup(force_refresh=True)
        payees = payees or self._payee_lookup(force_refresh=True)
        account_id = _clean_text(source.get("account_id"), "Account", required=True)
        if account_id not in accounts:
            raise StorageValidationError("Source account does not exist")
        category_id = _clean_text(source.get("category_id"), "Category", required=True)
        if category_id not in categories:
            raise StorageValidationError("Category does not exist")
        if categories[category_id]["kind"] != "Expense":
            raise StorageValidationError("Category kind does not match transaction kind")
        payee_id = _clean_text(source.get("payee_id"), "Payee")
        if payee_id and payee_id not in payees:
            raise StorageValidationError("Payee does not exist")
        decode_receipt_references(source.get("receipt_references", ""))
        _iso_date(source.get("txn_date"))

    def _reject_receipt_ownership_conflict(
        self,
        references: Any,
        *,
        transaction_id: str | None = None,
        transactions: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        receipt_ids = {
            item["id"] for item in decode_receipt_references(references)
        }
        if not receipt_ids:
            return
        if transactions is None:
            transactions = self.list_transactions(_force_refresh=True)
        for transaction in transactions:
            if transaction["id"] == transaction_id:
                continue
            if receipt_ids.intersection(
                item["id"]
                for item in decode_receipt_references(
                    transaction.get("receipt_references", "")
                )
            ):
                raise StorageConflictError(
                    "That receipt is already linked to another transaction"
                )

    @staticmethod
    def _mixed_use_record_matches(
        title: str,
        actual: Mapping[str, Any] | None,
        expected: Mapping[str, Any],
    ) -> bool:
        if actual is None:
            return False
        return all(
            (
                _normalize_tag_ids(actual.get(header, ""))
                == _normalize_tag_ids(expected.get(header, ""))
                if header == "tag_ids"
                else str(actual.get(header, "") or "")
                == str(expected.get(header, "") or "")
            )
            for header in WORKSHEET_HEADERS[title]
        )

    @staticmethod
    def _mixed_use_source_matches(
        actual_source: Mapping[str, Any] | None,
        expected_source: Mapping[str, Any],
        actual_transaction: Mapping[str, Any] | None = None,
    ) -> bool:
        """Match source fields and, when available, its displayed tag baseline."""
        if not _MixedUseMixin._mixed_use_record_matches(
            "MixedUseExpenses", actual_source, expected_source
        ):
            return False
        if actual_transaction is None or "tag_ids" not in expected_source:
            return True
        return _normalize_tag_ids(actual_transaction.get("tag_ids", "")) == _normalize_tag_ids(
            expected_source.get("tag_ids", "")
        )

    def _mixed_use_mutation_state(
        self,
        *,
        source_id: str,
        transaction_id: str,
        expected_source: Mapping[str, Any],
        expected_transaction: Mapping[str, Any],
        deletion: bool = False,
        original_source: Mapping[str, Any] | None = None,
        original_transaction: Mapping[str, Any] | None = None,
    ) -> str:
        """Classify a fresh mixed-use pair snapshot for the common write policy."""
        sources, transactions = self._raw_mixed_use_snapshot()
        actual_source = sources.get(source_id)
        actual_transaction = transactions.get(transaction_id)
        if deletion:
            applied = actual_source is None and actual_transaction is None
            unchanged = self._mixed_use_record_matches(
                "MixedUseExpenses", actual_source, expected_source
            ) and self._mixed_use_record_matches(
                "Transactions", actual_transaction, expected_transaction
            )
        else:
            applied = self._mixed_use_record_matches(
                "MixedUseExpenses", actual_source, expected_source
            ) and self._mixed_use_record_matches(
                "Transactions", actual_transaction, expected_transaction
            )
            if original_source is not None:
                source_unchanged = self._mixed_use_record_matches(
                    "MixedUseExpenses", actual_source, original_source
                )
                if original_transaction is None:
                    transaction_unchanged = actual_transaction is None
                else:
                    transaction_unchanged = self._mixed_use_record_matches(
                        "Transactions", actual_transaction, original_transaction
                    )
                unchanged = source_unchanged and transaction_unchanged
            else:
                unchanged = actual_source is None and actual_transaction is None
        if applied:
            return "applied"
        if unchanged:
            return "unchanged"
        return "ambiguous"

    def _prepare_mixed_use_expense(
        self,
        data: Mapping[str, Any],
        *,
        source_id: str | None = None,
        linked_transaction_id: str | None = None,
        created_at: str | None = None,
        original_transaction: Mapping[str, Any] | None = None,
        preserve_existing_payee: bool = False,
    ) -> tuple[dict[str, str], dict[str, str]]:
        try:
            allocation = validate_mixed_use_allocation(
                data.get("total_expense"),
                data.get("business_use_percentage"),
            )
        except MixedUseAllocationError as exc:
            raise StorageValidationError(str(exc)) from exc
        rationale = _clean_text(
            data.get("allocation_rationale"),
            "Allocation rationale",
            required=True,
        )
        source_id = _clean_text(
            source_id if source_id is not None else data.get("source_id", data.get("id")),
            "Mixed-use source ID",
        ) or str(uuid4())
        linked_transaction_id = _clean_text(
            linked_transaction_id
            if linked_transaction_id is not None
            else data.get("linked_transaction_id"),
            "Linked transaction ID",
        ) or str(uuid4())
        original_description = _clean_text(data.get("description"), "Description")
        transaction = self._prepare_transaction(
            {
                **data,
                "kind": "Expense",
                "amount": allocation.allocated_amount,
                "description": original_description,
            },
            created_at=(
                original_transaction.get("created_at")
                if original_transaction is not None
                else None
            ),
            original_transaction=original_transaction,
            preserve_existing_payee=preserve_existing_payee,
        )
        source = {
            "id": source_id,
            "txn_date": transaction["txn_date"],
            "kind": "Expense",
            "total_expense": allocation.total_expense,
            "business_use_percentage": allocation.business_use_percentage,
            "allocated_amount": allocation.allocated_amount,
            "account_id": transaction["account_id"],
            "category_id": transaction["category_id"],
            "payee_id": transaction["payee_id"],
            "description": original_description,
            "reference": transaction["reference"],
            "receipt_references": transaction["receipt_references"],
            "allocation_rationale": rationale,
            "linked_transaction_id": linked_transaction_id,
            "tag_ids": transaction["tag_ids"],
            "created_at": created_at or _utc_now(),
        }
        for field in (
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_source_kind",
            "recurring_occurrence_type",
        ):
            value = _clean_text(transaction.get(field), field.replace("_", " ").title())
            if value:
                source[field] = value
        projection = {
            **transaction,
            "id": linked_transaction_id,
            "description": mixed_use_ledger_description(
                original_description, rationale
            ),
            "source_type": MIXED_USE_SOURCE_TYPE,
            "source_id": source_id,
        }
        return source, projection

    def list_mixed_use_expenses(
        self, *, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        sources, transactions = self._raw_mixed_use_snapshot(
            force_refresh=_force_refresh
        )
        tables = {
            "MixedUseExpenses": (MIXED_USE_WORKSHEET_HEADERS, list(sources.values())),
            "Transactions": (
                WORKSHEET_HEADERS["Transactions"],
                list(transactions.values()),
            ),
        }
        _validate_mixed_use_tables(tables)
        accounts = self._account_lookup(force_refresh=_force_refresh)
        categories = self._category_lookup(force_refresh=_force_refresh)
        payees = self._payee_lookup(force_refresh=_force_refresh)
        result = []
        for source in sources.values():
            self._validate_mixed_use_references(
                source,
                accounts=accounts,
                categories=categories,
                payees=payees,
            )
            item = dict(source)
            item["payee"] = payees.get(item["payee_id"], {}).get("name", "")
            linked_transaction = transactions.get(
                str(item.get("linked_transaction_id") or "")
            )
            source_has_tag_metadata = "tag_ids" in item
            source_tag_ids = _normalize_tag_ids(item.get("tag_ids", ""))
            if not source_has_tag_metadata and linked_transaction is not None:
                # Sources written before tag persistence was introduced can
                # still recover their tags from the linked projection.
                source_tag_ids = _normalize_tag_ids(
                    linked_transaction.get("tag_ids", "")
                )
            item["tag_ids"] = source_tag_ids
            item["ledger_status"] = "linked"
            result.append(item)
        return sorted(
            result,
            key=lambda item: (item["txn_date"], item["created_at"], item["id"]),
            reverse=True,
        )

    def list_mixed_use_expense_sources(
        self, *, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        """Return cached source rows for lightweight reference-count displays."""
        return [
            dict(row.values)
            for row in self._rows("MixedUseExpenses", force_refresh=_force_refresh)
        ]

    def get_mixed_use_expense(
        self, source_id: str, *, _force_refresh: bool = False
    ) -> dict[str, str]:
        source_id = _clean_text(source_id, "Mixed-use source ID", required=True)
        if _force_refresh:
            sources, transactions = self._raw_mixed_use_snapshot(force_refresh=True)
            source = sources.get(source_id)
            if source is None:
                raise StorageNotFoundError("Mixed-use expense no longer exists")
            transaction_id = _clean_text(
                source.get("linked_transaction_id"),
                "Linked transaction ID",
                required=True,
            )
            transaction = transactions.get(transaction_id)
            if transaction is None:
                raise StorageValidationError(
                    "Mixed-use source references a missing projection transaction"
                )
            _validate_mixed_use_tables(
                {
                    "MixedUseExpenses": (
                        MIXED_USE_WORKSHEET_HEADERS,
                        [source],
                    ),
                    "Transactions": (
                        WORKSHEET_HEADERS["Transactions"],
                        [transaction],
                    ),
                }
            )
            accounts = self._account_lookup(force_refresh=True)
            categories = self._category_lookup(force_refresh=True)
            payees = self._payee_lookup(force_refresh=True)
            self._validate_mixed_use_references(
                source,
                accounts=accounts,
                categories=categories,
                payees=payees,
            )
            item = dict(source)
            item["payee"] = payees.get(item["payee_id"], {}).get("name", "")
            source_has_tag_metadata = "tag_ids" in item
            source_tag_ids = _normalize_tag_ids(item.get("tag_ids", ""))
            if not source_has_tag_metadata:
                source_tag_ids = _normalize_tag_ids(transaction.get("tag_ids", ""))
            item["tag_ids"] = source_tag_ids
            item["ledger_status"] = "linked"
            return item
        for source in self.list_mixed_use_expenses():
            if source["id"] == source_id:
                return source
        raise StorageNotFoundError("Mixed-use expense no longer exists")

    def resolve_mixed_use_expense(self, source_id: str) -> dict[str, str]:
        """Resolve one source record through its durable projection link."""
        return self.get_mixed_use_expense(source_id)

    def create_mixed_use_expense(self, **data: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            return self._create_mixed_use_expense(**data)

    def _create_mixed_use_expense(self, **data: Any) -> dict[str, str]:
        requested_source_id = _clean_text(
            data.get("source_id", data.get("id")), "Mixed-use source ID"
        )
        requested_transaction_id = _clean_text(
            data.get("linked_transaction_id"), "Linked transaction ID"
        )
        sources, transactions = self._raw_mixed_use_snapshot()
        existing_source = (
            sources.get(requested_source_id) if requested_source_id else None
        )
        if existing_source is None and not requested_source_id and requested_transaction_id:
            matching_sources = [
                source
                for source in sources.values()
                if _clean_text(
                    source.get("linked_transaction_id"),
                    "Linked transaction ID",
                )
                == requested_transaction_id
            ]
            if len(matching_sources) > 1:
                raise StorageValidationError(
                    "Mixed-use source linked transaction IDs must be unique"
                )
            if matching_sources:
                existing_source = matching_sources[0]
                requested_source_id = _clean_text(
                    existing_source.get("id"),
                    "Mixed-use source ID",
                    required=True,
                )
        existing_transaction = (
            transactions.get(requested_transaction_id)
            if requested_transaction_id
            else None
        )
        original_transaction = existing_transaction
        if existing_source is not None:
            persisted_transaction_id = _clean_text(
                existing_source.get("linked_transaction_id"),
                "Linked transaction ID",
                required=True,
            )
            if (
                requested_transaction_id
                and requested_transaction_id != persisted_transaction_id
            ):
                raise StorageConflictError(
                    "The mixed-use source is already linked to another transaction ID"
                )
            if not requested_transaction_id:
                requested_transaction_id = persisted_transaction_id
                existing_transaction = transactions.get(requested_transaction_id)
            original_transaction = existing_transaction or {
                "account_id": existing_source.get("account_id"),
                "payee_id": existing_source.get("payee_id"),
                "tag_ids": existing_source.get("tag_ids", ""),
            }
        if existing_transaction is not None and existing_source is None:
            raise StorageConflictError(
                "The mixed-use source or linked transaction ID is already in use"
            )
        self._reject_receipt_ownership_conflict(
            data.get("receipt_references", ""),
            transaction_id=requested_transaction_id,
        )
        source, projection = self._prepare_mixed_use_expense(
            data,
            source_id=requested_source_id or None,
            linked_transaction_id=requested_transaction_id or None,
            original_transaction=original_transaction,
            preserve_existing_payee=(
                existing_source is not None or existing_transaction is not None
            ),
        )
        source_id = source["id"]
        transaction_id = projection["id"]
        source_append_confirmed = False
        if existing_source is not None:
            # A source-only retry must compare against the persisted source,
            # including its original timestamp, rather than regenerate it.
            source["created_at"] = str(existing_source.get("created_at", ""))
        if existing_transaction is not None:
            # A fully-applied retry must also compare against the projection's
            # persisted timestamp, which is generated independently of the source.
            projection["created_at"] = str(
                existing_transaction.get("created_at", "")
            )
        if existing_source is not None or existing_transaction is not None:
            if self._mixed_use_record_matches(
                "MixedUseExpenses", existing_source, source
            ) and self._mixed_use_record_matches(
                "Transactions", existing_transaction, projection
            ):
                return self.get_mixed_use_expense(source_id)
            if (
                self._mixed_use_record_matches(
                    "MixedUseExpenses", existing_source, source
                )
                and existing_transaction is None
            ):
                raise StorageValidationError(
                    "The mixed-use source exists without its ledger projection. "
                    "Inspect the source and ledger before retrying or repairing it."
                )
            raise StorageConflictError(
                "The mixed-use source or linked transaction ID is already in use"
            )
        try:
            self._append("MixedUseExpenses", source)
            source_append_confirmed = True
            persisted_source = self._find_row("MixedUseExpenses", source_id)
            if not self._mixed_use_record_matches(
                "MixedUseExpenses", persisted_source.values, source
            ):
                raise StorageConflictError(
                    "The mixed-use source ID is already in use with different data"
                )
            self._append("Transactions", projection)
        except StorageConflictError:
            self._invalidate("MixedUseExpenses")
            self._invalidate("Transactions")
            raise
        except (StorageError, OSError) as error:
            if isinstance(error, StorageUnavailableError):
                if not error.retryable:
                    self._invalidate("MixedUseExpenses")
                    self._invalidate("Transactions")
                    if source_append_confirmed:
                        raise StorageUnavailableError(
                            _mutation_guidance("mixed-use create"), retryable=False
                        ) from error
                    raise
                try:
                    state = self._mixed_use_mutation_state(
                        source_id=source_id,
                        transaction_id=transaction_id,
                        expected_source=source,
                        expected_transaction=projection,
                    )
                except StorageError as read_error:
                    self._invalidate("MixedUseExpenses")
                    self._invalidate("Transactions")
                    raise StorageUnavailableError(
                        _mutation_guidance("mixed-use create"), retryable=False
                    ) from read_error
                if state == "applied":
                    return self.get_mixed_use_expense(source_id)
                self._invalidate("MixedUseExpenses")
                self._invalidate("Transactions")
                raise StorageUnavailableError(
                    _mutation_guidance("mixed-use create"), retryable=False
                ) from error
            self._invalidate("MixedUseExpenses")
            self._invalidate("Transactions")
            raise
        return self.get_mixed_use_expense(source_id)

    def edit_mixed_use_expense(
        self,
        source_id: str,
        *,
        expected_source: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        with self._workbook_locks.ledger:
            return self._edit_mixed_use_expense(
                source_id,
                expected_source=expected_source,
                expected=expected,
                **changes,
            )

    def _edit_mixed_use_expense(
        self,
        source_id: str,
        *,
        expected_source: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        source_id = _clean_text(source_id, "Mixed-use source ID", required=True)
        expected_source = expected_source or expected
        sources, transactions = self._raw_mixed_use_snapshot()
        current_source = sources.get(source_id)
        if current_source is None:
            raise StorageNotFoundError("Mixed-use expense no longer exists")
        transaction_id = _clean_text(
            current_source.get("linked_transaction_id"),
            "Linked transaction ID",
            required=True,
        )
        current_transaction = transactions.get(transaction_id)
        if current_transaction is None:
            raise StorageValidationError(
                "Mixed-use source has no linked projection transaction"
            )
        if expected_source is not None and not self._mixed_use_source_matches(
            current_source, expected_source, current_transaction
        ):
            raise StorageConflictError(
                "The mixed-use expense changed; refresh it before editing."
            )
        _validate_mixed_use_tables(
            {
                "MixedUseExpenses": (
                    MIXED_USE_WORKSHEET_HEADERS,
                    list(sources.values()),
                ),
                "Transactions": (
                    WORKSHEET_HEADERS["Transactions"],
                    list(transactions.values()),
                ),
            }
        )
        if "id" in changes or "source_id" in changes or "linked_transaction_id" in changes:
            raise StorageValidationError("Mixed-use source IDs cannot be edited")
        for field in (
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_source_kind",
            "recurring_occurrence_type",
        ):
            if field in changes and str(changes[field] or "") != str(current_source.get(field, "") or ""):
                raise StorageValidationError("Recurring provenance cannot be changed")
        merged = {**current_source, **changes}
        if "tag_ids" not in changes:
            merged["tag_ids"] = current_transaction.get("tag_ids", "")
        if "receipt_references" in changes:
            self._reject_receipt_ownership_conflict(
                merged.get("receipt_references", ""), transaction_id=transaction_id
            )
        updated_source, updated_transaction = self._prepare_mixed_use_expense(
            merged,
            source_id=source_id,
            linked_transaction_id=transaction_id,
            created_at=current_source.get("created_at"),
            original_transaction=current_transaction,
        )
        fresh_transaction = self._find_row("Transactions", transaction_id)
        fresh_source = self._find_row("MixedUseExpenses", source_id)
        if not self._mixed_use_record_matches(
            "Transactions", fresh_transaction.values, current_transaction
        ) or not self._mixed_use_record_matches(
            "MixedUseExpenses", fresh_source.values, current_source
        ):
            raise StorageConflictError(
                "The mixed-use expense changed; refresh it before editing."
            )
        def write() -> None:
            self._replace_rows_atomically(
                [
                    ("Transactions", fresh_transaction, updated_transaction),
                    ("MixedUseExpenses", fresh_source, updated_source),
                ]
            )

        def refresh_rows() -> None:
            nonlocal fresh_transaction, fresh_source
            fresh_transaction = self._find_row("Transactions", transaction_id)
            fresh_source = self._find_row("MixedUseExpenses", source_id)
            if not self._mixed_use_record_matches(
                "Transactions", fresh_transaction.values, current_transaction
            ) or not self._mixed_use_record_matches(
                "MixedUseExpenses", fresh_source.values, current_source
            ):
                raise StorageConflictError(
                    "The mixed-use expense changed while the edit was being retried."
                )

        self._write_with_uncertain_readback(
            "mixed-use edit",
            write,
            lambda: self._mixed_use_mutation_state(
                source_id=source_id,
                transaction_id=transaction_id,
                expected_source=updated_source,
                expected_transaction=updated_transaction,
                original_source=current_source,
                original_transaction=current_transaction,
            ),
            before_retry=refresh_rows,
            invalidate=("Transactions", "MixedUseExpenses"),
        )
        return self.get_mixed_use_expense(source_id)

    def delete_mixed_use_expense(
        self,
        source_id: str,
        *,
        expected_source: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> None:
        with self._workbook_locks.ledger:
            self._delete_mixed_use_expense(
                source_id,
                expected_source=expected_source,
                expected=expected,
            )

    def _delete_mixed_use_expense(
        self,
        source_id: str,
        *,
        expected_source: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> None:
        source_id = _clean_text(source_id, "Mixed-use source ID", required=True)
        expected_source = expected_source or expected
        sources, transactions = self._raw_mixed_use_snapshot()
        source = sources.get(source_id)
        if source is None:
            raise StorageNotFoundError("Mixed-use expense no longer exists")
        transaction_id = _clean_text(
            source.get("linked_transaction_id"),
            "Linked transaction ID",
            required=True,
        )

        transaction = transactions.get(transaction_id)
        if transaction is None:
            if expected_source is not None and not self._mixed_use_record_matches(
                "MixedUseExpenses", source, expected_source
            ):
                raise StorageConflictError(
                    "The mixed-use expense changed; refresh it before deleting."
                )
            raise StorageValidationError(
                "The mixed-use source exists without its ledger projection. "
                "Inspect the source and ledger before deleting or repairing it."
            )
        if expected_source is not None and not self._mixed_use_source_matches(
            source, expected_source, transaction
        ):
            raise StorageConflictError(
                "The mixed-use expense changed; refresh it before deleting."
            )
        _validate_mixed_use_tables(
            {
                "MixedUseExpenses": (MIXED_USE_WORKSHEET_HEADERS, list(sources.values())),
                "Transactions": (WORKSHEET_HEADERS["Transactions"], list(transactions.values())),
            }
        )
        fresh_transaction = self._find_row("Transactions", transaction_id)
        fresh_source = self._find_row("MixedUseExpenses", source_id)
        if not self._mixed_use_record_matches(
            "Transactions", fresh_transaction.values, transaction
        ) or not self._mixed_use_record_matches(
            "MixedUseExpenses", fresh_source.values, source
        ):
            raise StorageConflictError(
                "The mixed-use expense changed; refresh it before deleting."
            )

        requests = [
            self._managed_delete_request("Transactions", fresh_transaction),
            self._managed_delete_request("MixedUseExpenses", fresh_source),
        ]

        def refresh_requests() -> None:
            nonlocal requests, fresh_transaction, fresh_source
            fresh_transaction = self._find_row("Transactions", transaction_id)
            fresh_source = self._find_row("MixedUseExpenses", source_id)
            if not self._mixed_use_record_matches(
                "Transactions", fresh_transaction.values, transaction
            ) or not self._mixed_use_record_matches(
                "MixedUseExpenses", fresh_source.values, source
            ):
                raise StorageConflictError(
                    "The mixed-use expense changed while deletion was being retried."
                )
            requests = [
                self._managed_delete_request("Transactions", fresh_transaction),
                self._managed_delete_request("MixedUseExpenses", fresh_source),
            ]

        self._write_with_uncertain_readback(
            "mixed-use deletion",
            lambda: self._batch_update_spreadsheet(requests),
            lambda: self._mixed_use_mutation_state(
                source_id=source_id,
                transaction_id=transaction_id,
                expected_source=source,
                expected_transaction=transaction,
                deletion=True,
            ),
            before_retry=refresh_requests,
            invalidate=("Transactions", "MixedUseExpenses"),
        )

__all__ = ["_MixedUseMixin"]
