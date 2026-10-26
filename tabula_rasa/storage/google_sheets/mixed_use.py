"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any
from .schema import (
    MIXED_USE_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageConflictError,
    StorageValidationError,
)
from .validation import (
    _clean_text,
    _iso_date,
    _normalize_tag_ids,
    _validate_mixed_use_tables,
    decode_receipt_references,
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


__all__ = ["_MixedUseMixin"]
