"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from tabula_rasa.transaction import (
    reject_derived_transaction,
)
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from .schema import (
    TRANSACTION_KINDS,
)
from .errors import (
    StorageValidationError,
)
from .validation import (
    _clean_text,
    _iso_date,
    _normalize_tag_ids,
    _positive_amount,
    decode_receipt_references,
)


class TransactionsMixin:
    """Mixin for the transactions storage boundary."""

    @staticmethod
    def _sheet_column_index(headers: Sequence[str], column: str) -> int:
        try:
            return list(headers).index(column)
        except ValueError as exc:
            raise StorageValidationError(
                f"Transactions is missing the {column} header"
            ) from exc

    def _transactions_sheet_id(self) -> int:
        return self._sheet_id("Transactions")

    def _sheet_id(self, title: str) -> int:
        sheet_id = getattr(self._worksheet(title), "id", None)
        if sheet_id is None:
            raise StorageValidationError(f"{title} worksheet has no stable sheet ID")
        try:
            return int(sheet_id)
        except (TypeError, ValueError) as exc:
            raise StorageValidationError(
                f"{title} worksheet has an invalid sheet ID: {sheet_id}"
            ) from exc


    _reject_mixed_use_projection = staticmethod(reject_derived_transaction)


    def _account_lookup(
        self, *, force_refresh: bool = False
    ) -> dict[str, dict[str, Any]]:
        return {
            account["id"]: account
            for account in self.list_accounts(
                active_only=False, _force_refresh=force_refresh
            )
        }

    def _category_lookup(
        self, *, force_refresh: bool = False
    ) -> dict[str, dict[str, str]]:
        return {
            category["id"]: category
            for category in self.list_categories(_force_refresh=force_refresh)
        }


    def list_transactions(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        kind: str | None = None,
        account_ids: Iterable[str] | None = None,
        _force_refresh: bool = False,
    ) -> list[dict[str, str]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        selected_account_ids = (
            {str(account_id) for account_id in account_ids}
            if account_ids is not None
            else None
        )
        if kind is not None:
            kind = kind.title()
            if kind not in TRANSACTION_KINDS:
                raise StorageValidationError("Unknown transaction kind")
        transactions = []
        accounts = self._account_lookup(force_refresh=_force_refresh)
        categories = self._category_lookup(force_refresh=_force_refresh)
        payees = self._payee_lookup(force_refresh=_force_refresh)
        tags = self._tag_lookup(force_refresh=_force_refresh)
        raw_transactions = self._rows("Transactions", force_refresh=_force_refresh)
        for row in raw_transactions:
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Transaction ID", required=True)
            item["txn_date"] = _iso_date(item.get("txn_date"))
            item["kind"] = _clean_text(
                item.get("kind"), "Transaction kind", required=True
            ).title()
            if item["kind"] not in TRANSACTION_KINDS:
                raise StorageValidationError("Unknown transaction kind")
            source_type = str(item.get("source_type") or "").strip().lower()
            is_zero_depreciation = False
            if source_type == "depreciation":
                try:
                    is_zero_depreciation = Decimal(str(item.get("amount"))) == 0
                except (InvalidOperation, ValueError):
                    is_zero_depreciation = False
            item["amount"] = (
                "0.00" if is_zero_depreciation else _positive_amount(item.get("amount"))
            )
            item["account_id"] = _clean_text(
                item.get("account_id"), "Account", required=True
            )
            if item["account_id"] not in accounts:
                raise StorageValidationError("Source account does not exist")
            item["to_account_id"] = _clean_text(
                item.get("to_account_id"), "Destination account"
            )
            item["category_id"] = _clean_text(item.get("category_id"), "Category")
            if item["kind"] == "Transfer":
                if not item["to_account_id"]:
                    raise StorageValidationError("Destination account does not exist")
                if item["to_account_id"] not in accounts:
                    raise StorageValidationError("Destination account does not exist")
                if item["to_account_id"] == item["account_id"]:
                    raise StorageValidationError("Transfer accounts must be different")
                if item["category_id"]:
                    raise StorageValidationError("Transfers cannot have a category")
            else:
                if item["to_account_id"]:
                    raise StorageValidationError(
                        "Only transfers can have a destination account"
                    )
                if item["category_id"] not in categories:
                    raise StorageValidationError("Category does not exist")
                if categories[item["category_id"]]["kind"] != item["kind"]:
                    raise StorageValidationError(
                        "Category kind does not match transaction kind"
                    )
            item["payee_id"] = _clean_text(item.get("payee_id"), "Payee")
            item["source_type"] = source_type
            item["source_id"] = _clean_text(
                item.get("source_id"), "Transaction source ID"
            )
            if bool(item["source_type"]) != bool(item["source_id"]):
                raise StorageValidationError(
                    "Transaction source type and source ID must be provided together"
                )
            if item["source_type"] and item["source_type"] not in {
                MIXED_USE_SOURCE_TYPE,
                "depreciation",
            }:
                raise StorageValidationError("Transaction source type is unsupported")
            if not item["source_type"]:
                # Preserve the pre-Phase-A public shape for ordinary rows while
                # exposing both fields whenever a projection is present.
                item.pop("source_type")
                item.pop("source_id")
            if item["payee_id"] and item["payee_id"] not in payees:
                raise StorageValidationError("Payee does not exist")
            item["payee"] = payees.get(item["payee_id"], {}).get("name", "")
            normalized_tag_ids = _normalize_tag_ids(item.get("tag_ids", ""))
            if any(tag_id not in tags for tag_id in normalized_tag_ids):
                raise StorageValidationError("Tag does not exist")
            item["tag_ids"] = normalized_tag_ids
            item["tags"] = [tags[tag_id]["name"] for tag_id in normalized_tag_ids]
            decode_receipt_references(item.get("receipt_references", ""))
            if start_text and item["txn_date"] < start_text:
                continue
            if end_text and item["txn_date"] > end_text:
                continue
            if kind and item["kind"] != kind:
                continue
            if selected_account_ids is not None and not (
                {
                    item["account_id"],
                    item.get("to_account_id", ""),
                }
                & selected_account_ids
            ):
                continue
            transactions.append(item)
        return sorted(
            transactions,
            key=lambda item: (item["txn_date"], item["created_at"], item["id"]),
            reverse=True,
        )


__all__ = ["TransactionsMixin"]
