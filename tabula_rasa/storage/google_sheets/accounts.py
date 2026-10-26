"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from typing import Any
from .schema import (
    ACCOUNT_TYPES,
    CATEGORY_KINDS,
)
from .errors import (
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _balance_amount,
    _clean_text,
    _validate_account_classification,
)


class AccountsMixin:
    """Mixin for the accounts storage boundary."""

    def list_accounts(
        self, *, active_only: bool = True, _force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        accounts = []
        account_ids: set[str] = set()
        for row in self._rows("Accounts", force_refresh=_force_refresh):
            record: dict[str, Any] = dict(row.values)
            record["id"] = _clean_text(record.get("id"), "ID", required=True)
            if record["id"] in account_ids:
                raise StorageValidationError(
                    "Account IDs must be unique after normalization"
                )
            account_ids.add(record["id"])
            record["name"] = _clean_text(
                record.get("name"), "Account name", required=True
            )
            record["parent_id"] = _clean_text(record.get("parent_id"), "Account parent")
            account_type = _clean_text(
                record.get("type"), "Account type", required=True
            )
            classification = _clean_text(
                record.get("classification"),
                "Account classification",
                required=True,
            )
            if account_type not in ACCOUNT_TYPES:
                raise StorageValidationError("Unknown account type")
            _validate_account_classification(account_type, classification)
            record["type"] = account_type
            record["classification"] = classification
            record["active"] = _as_bool(record.get("active", ""))
            record["opening_balance"] = float(
                _balance_amount(record.get("opening_balance", ""))
            )
            if not active_only or record["active"]:
                accounts.append(record)
        return sorted(accounts, key=lambda item: item["name"].casefold())


    def list_categories(
        self, kind: str | None = None, *, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        if kind is not None and kind not in CATEGORY_KINDS:
            raise StorageValidationError("Unknown category kind")
        categories = [
            dict(row.values)
            for row in self._rows("Categories", force_refresh=_force_refresh)
        ]
        category_ids: set[str] = set()
        for category in categories:
            category["id"] = _clean_text(category.get("id"), "ID", required=True)
            if category["id"] in category_ids:
                raise StorageValidationError(
                    "Category IDs must be unique after normalization"
                )
            category_ids.add(category["id"])
            category["name"] = _clean_text(
                category.get("name"), "Category name", required=True
            )
            category["parent_id"] = _clean_text(
                category.get("parent_id"), "Category parent"
            )
            category_kind = _clean_text(
                category.get("kind"), "Category kind", required=True
            ).title()
            if category_kind not in CATEGORY_KINDS:
                raise StorageValidationError("Category kind must be Income or Expense")
            category["kind"] = category_kind
        if kind is not None:
            categories = [item for item in categories if item["kind"] == kind]
        return sorted(
            categories, key=lambda item: (item["kind"], item["name"].casefold())
        )


__all__ = ["AccountsMixin"]
