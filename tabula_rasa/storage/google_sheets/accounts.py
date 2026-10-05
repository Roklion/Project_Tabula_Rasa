"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from typing import Any
from .baselines import ACCOUNT_FIELDS, CATEGORY_FIELDS, check_expected_snapshot
from uuid import uuid4
from tabula_rasa.quickbooks_import import suggested_account_classification
from .schema import (
    ACCOUNT_TYPES,
    CATEGORY_KINDS,
)
from .errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _balance_amount,
    _clean_text,
    _utc_now,
    _validate_account_classification,
    _validate_hierarchy_records,
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

    def create_account(
        self,
        name: str,
        account_type: str,
        opening_balance: Any = 0,
        *,
        classification: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        name = _clean_text(name, "Account name", required=True)
        account_type = _clean_text(account_type, "Account type", required=True)
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError("Unknown account type")
        classification = _clean_text(
            classification
            if classification is not None
            else suggested_account_classification(name, account_type),
            "Account classification",
            required=True,
        ).title()
        _validate_account_classification(account_type, classification)
        existing_accounts = self.list_accounts(active_only=False, _force_refresh=True)
        if any(
            account["name"].casefold() == name.casefold()
            for account in existing_accounts
        ):
            raise StorageConflictError("Account names must be unique")
        record = {
            "id": str(uuid4()),
            "name": name,
            "type": account_type,
            "classification": classification,
            "opening_balance": _balance_amount(opening_balance),
            "active": "TRUE",
            "created_at": _utc_now(),
            "parent_id": _clean_text(parent_id, "Account parent"),
        }
        _validate_hierarchy_records(
            [*existing_accounts, record],
            compatibility_field="classification",
            item_label="Account",
        )
        self._append("Accounts", record)
        return dict(record)

    def edit_account(self, account_id: str, *, expected_account=None, **changes: Any) -> dict[str, Any]:
        with self._workbook_locks.ledger:
            return self._edit_account(account_id, expected_account=expected_account, **changes)

    def _edit_account(self, account_id: str, *, expected_account=None, **changes: Any) -> dict[str, Any]:
        current = self._find_row("Accounts", account_id)
        check_expected_snapshot(current.values, expected_account, fields=ACCOUNT_FIELDS, label="account")
        account_id = _clean_text(current.values.get("id"), "Account ID", required=True)
        updated = dict(current.values)
        existing_accounts = self.list_accounts(active_only=False)
        name = _clean_text(
            changes.get("name", updated["name"]), "Account name", required=True
        )
        account_type = _clean_text(
            changes.get("type", updated["type"]), "Account type", required=True
        )
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError("Unknown account type")
        classification = _clean_text(
            changes.get("classification", updated["classification"]),
            "Account classification",
            required=True,
        ).title()
        _validate_account_classification(account_type, classification)
        if (account_type != "Other" or classification != "Asset") and any(
            _clean_text(
                row.values.get("accumulated_depreciation_account_id"), "Account ID"
            )
            == account_id
            for row in self._rows("Assets", force_refresh=True)
        ):
            raise StorageConflictError(
                "An asset's accumulated depreciation account must remain Other / Asset"
            )
        if any(
            account["id"] != account_id
            and account["name"].casefold() == name.casefold()
            for account in existing_accounts
        ):
            raise StorageConflictError("Account names must be unique")
        updated.update(
            {
                "name": name,
                "type": account_type,
                "classification": classification,
                "opening_balance": _balance_amount(
                    changes.get("opening_balance", updated["opening_balance"])
                ),
                "active": "TRUE"
                if _as_bool(changes.get("active", updated["active"]))
                else "FALSE",
                "parent_id": _clean_text(
                    changes.get("parent_id", updated.get("parent_id", "")),
                    "Account parent",
                ),
            }
        )
        _validate_hierarchy_records(
            [
                updated if account["id"] == account_id else account
                for account in existing_accounts
            ],
            compatibility_field="classification",
            item_label="Account",
        )
        self._replace_row("Accounts", current, updated)
        return updated

    def deactivate_account(self, account_id: str) -> dict[str, Any]:
        return self.edit_account(account_id, active=False)

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

    def create_category(
        self,
        name: str,
        kind: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, str]:
        name = _clean_text(name, "Category name", required=True)
        kind = _clean_text(kind, "Category kind", required=True).title()
        if kind not in CATEGORY_KINDS:
            raise StorageValidationError("Category kind must be Income or Expense")
        existing_categories = self.list_categories(_force_refresh=True)
        if any(
            category["name"].casefold() == name.casefold() and category["kind"] == kind
            for category in existing_categories
        ):
            raise StorageConflictError("That category already exists")
        record = {
            "id": str(uuid4()),
            "name": name,
            "kind": kind,
            "parent_id": _clean_text(parent_id, "Category parent"),
        }
        _validate_hierarchy_records(
            [*existing_categories, record],
            compatibility_field="kind",
            item_label="Category",
        )
        self._append("Categories", record)
        return record

    def edit_category(self, category_id: str, *, expected_category=None, **changes: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            return self._edit_category(category_id, expected_category=expected_category, **changes)

    def _edit_category(self, category_id: str, *, expected_category=None, **changes: Any) -> dict[str, str]:
        current = self._find_row("Categories", category_id)
        check_expected_snapshot(current.values, expected_category, fields=CATEGORY_FIELDS, label="category")
        updated = dict(current.values)
        normalized_category_id = _clean_text(
            updated.get("id"), "Category ID", required=True
        )
        existing_categories = self.list_categories()
        name = _clean_text(
            changes.get("name", updated["name"]), "Category name", required=True
        )
        kind = _clean_text(
            changes.get("kind", updated["kind"]), "Category kind", required=True
        ).title()
        if kind not in CATEGORY_KINDS:
            raise StorageValidationError("Category kind must be Income or Expense")

        def reject_mixed_use_kind_change() -> None:
            self._reject_asset_expense_category_change(normalized_category_id)
            self._reject_journal_category_reference(
                normalized_category_id,
                "Category kind cannot change while used by a journal entry",
            )
            sources, _ = self._raw_mixed_use_snapshot()
            if any(
                str(source.get("category_id") or "").strip() == normalized_category_id
                for source in sources.values()
            ):
                raise StorageConflictError(
                    "Category kind cannot change while used by a mixed-use expense"
                )
            recurring_schedules = self._rows("RecurringSchedules", force_refresh=True)
            if any(
                _clean_text(row.values.get("category_id"), "Category")
                == normalized_category_id
                for row in recurring_schedules
            ):
                raise StorageConflictError(
                    "Category kind cannot change while used by a recurring schedule"
                )

        if kind != updated["kind"]:
            reject_mixed_use_kind_change()
            current = self._find_row("Categories", normalized_category_id)
            check_expected_snapshot(current.values, expected_category, fields=CATEGORY_FIELDS, label="category")
            updated = dict(current.values)
            existing_categories = self.list_categories()
            name = _clean_text(
                changes.get("name", updated["name"]), "Category name", required=True
            )
            kind = _clean_text(
                changes.get("kind", updated["kind"]), "Category kind", required=True
            ).title()
        if any(
            category["id"] != normalized_category_id
            and category["name"].casefold() == name.casefold()
            and category["kind"] == kind
            for category in existing_categories
        ):
            raise StorageConflictError("That category already exists")
        updated.update(
            {
                "name": name,
                "kind": kind,
                "parent_id": _clean_text(
                    changes.get("parent_id", updated.get("parent_id", "")),
                    "Category parent",
                ),
            }
        )
        _validate_hierarchy_records(
            [
                updated if category["id"] == normalized_category_id else category
                for category in existing_categories
            ],
            compatibility_field="kind",
            item_label="Category",
        )
        if kind != current.values["kind"]:
            self._replace_rows(
                "Categories",
                [(current, updated)],
                before_retry=reject_mixed_use_kind_change,
            )
        else:
            self._replace_row("Categories", current, updated)
        return updated

    def _reject_asset_expense_category_change(self, category_id: str) -> None:
        category_id = _clean_text(category_id, "Category ID", required=True)
        if any(
                _clean_text(
                    row.values.get("depreciation_expense_account_id"), "Category ID"
                )
                == category_id
            for row in self._rows("Assets", force_refresh=True)
        ):
            raise StorageConflictError(
                "Category is used by an asset depreciation schedule"
            )

    def _reject_journal_category_reference(
        self, category_id: str, message: str
    ) -> None:
        category_id = _clean_text(category_id, "Category ID", required=True)
        if any(
            _clean_text(row.values.get("target_type"), "Journal target type")
            == "category"
            and _clean_text(row.values.get("target_id"), "Journal target")
            == category_id
            for row in self._rows("JournalPostings", force_refresh=True)
        ):
            raise StorageConflictError(message)

    def delete_category(self, category_id: str, *, expected_category=None) -> None:
        with self._workbook_locks.ledger:
            self._delete_category(category_id, expected_category=expected_category)

    def _delete_category(self, category_id: str, *, expected_category=None) -> None:
        self._reject_asset_expense_category_change(category_id)
        category_id = _clean_text(category_id, "ID", required=True)
        self._reject_journal_category_reference(
            category_id, "That category has journal entries and cannot be deleted"
        )
        current = self._find_row("Categories", category_id)
        check_expected_snapshot(current.values, expected_category, fields=CATEGORY_FIELDS, label="category")
        existing_categories = self.list_categories(_force_refresh=True)
        if any(
            str(category.get("parent_id") or "").strip() == category_id
            for category in existing_categories
        ):
            raise StorageConflictError(
                "That category has child categories and cannot be deleted"
            )
        transactions = self.list_transactions(_force_refresh=True)
        if any(
            str(transaction.get("category_id") or "").strip() == category_id
            for transaction in transactions
        ):
            raise StorageConflictError(
                "That category has transactions and cannot be deleted"
            )
        mixed_use_sources = self._rows("MixedUseExpenses", force_refresh=True)
        if any(
            _clean_text(row.values.get("category_id"), "Category") == category_id
            for row in mixed_use_sources
        ):
            raise StorageConflictError(
                "That category has mixed-use expenses and cannot be deleted"
            )
        recurring_schedules = self._rows("RecurringSchedules", force_refresh=True)
        if any(
            _clean_text(row.values.get("category_id"), "Category") == category_id
            for row in recurring_schedules
        ):
            raise StorageConflictError(
                "That category has recurring schedules and cannot be deleted"
            )
        original = dict(current.values)
        current_row = current
        worksheet = self._worksheet("Categories")

        def write() -> None:
            self._api(
                lambda: worksheet.delete_rows(current_row.row_number),
                retry_safe=False,
            )

        def state() -> str:
            try:
                latest = self._find_row("Categories", category_id)
            except StorageNotFoundError:
                return "applied"
            return "unchanged" if latest.values == original else "ambiguous"

        def refresh() -> None:
            nonlocal current_row
            self._reject_journal_category_reference(
                category_id, "That category has journal entries and cannot be deleted"
            )
            mixed_use_sources = self._rows("MixedUseExpenses", force_refresh=True)
            if any(
                _clean_text(row.values.get("category_id"), "Category") == category_id
                for row in mixed_use_sources
            ):
                raise StorageConflictError(
                    "That category has mixed-use expenses and cannot be deleted"
                )
            recurring_schedules = self._rows("RecurringSchedules", force_refresh=True)
            if any(
                _clean_text(row.values.get("category_id"), "Category") == category_id
                for row in recurring_schedules
            ):
                raise StorageConflictError(
                    "That category has recurring schedules and cannot be deleted"
                )
            current_row = self._find_row("Categories", category_id)
            if current_row.values != original:
                raise StorageConflictError(
                    "The category changed while deletion was being retried."
                )

        # Repeat the referential and row checks immediately before the write;
        # the first snapshot only discovers the candidate row.
        refresh()
        self._write_with_uncertain_readback(
            "category deletion",
            write,
            state,
            before_retry=refresh,
            invalidate=("Categories",),
        )


__all__ = ["AccountsMixin"]
