"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from uuid import uuid4
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.quickbooks_import import fingerprint
from tabula_rasa.quickbooks_import import missing_references
from tabula_rasa.quickbooks_import import normalize_rows
from tabula_rasa.quickbooks_import import suggested_account_classification
from tabula_rasa.quickbooks_import import suggested_account_type
from .schema import (
    CATEGORY_KINDS,
    TRANSACTION_KINDS,
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _clean_text,
    _decimal_values_match,
    _encode_receipt_references,
    _encode_tag_ids,
    _iso_date,
    _normalize_tag_ids,
    _positive_amount,
    _utc_now,
    _validate_hierarchy_records,
    decode_receipt_references,
    normalize_payee_name,
)
from .base import (
    _MIXED_USE_CREATE_LOCK,
    _StoredRow,
    _active_ledger_mutation_lock,
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

    def _fresh_bulk_transaction_snapshot(
        self,
        transaction_ids: Sequence[str],
        expected_transactions: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, _StoredRow], dict[str, dict[str, str]]]:
        normalized_ids = [
            _clean_text(transaction_id, "Transaction ID", required=True)
            for transaction_id in transaction_ids
        ]
        if not normalized_ids:
            raise StorageValidationError("No transactions selected")
        if len(normalized_ids) != len(set(normalized_ids)):
            raise StorageValidationError("Bulk transaction IDs must be unique")
        expected_by_id = {
            _clean_text(item.get("id"), "Transaction ID", required=True): dict(item)
            for item in expected_transactions
        }
        if set(expected_by_id) != set(normalized_ids) or len(expected_by_id) != len(
            expected_transactions
        ):
            raise StorageConflictError(
                "The visible transaction selection changed; select the rows again."
            )
        current_rows = self._rows("Transactions", force_refresh=True)
        current_by_id: dict[str, _StoredRow] = {}
        for row in current_rows:
            row_id = str(row.values.get("id", ""))
            if row_id in current_by_id:
                raise StorageValidationError("Duplicate ID detected in Transactions")
            current_by_id[row_id] = row
        selected_rows = {}
        current_by_id_values = {}
        for transaction_id in normalized_ids:
            row = current_by_id.get(transaction_id)
            if row is None:
                raise StorageConflictError(
                    "A selected transaction no longer exists; select the rows again."
                )
            expected = {}
            for key, value in expected_by_id[transaction_id].items():
                key = str(key)
                if key not in self._headers("Transactions"):
                    continue
                expected[key] = (
                    _encode_tag_ids(value)
                    if key == "tag_ids"
                    else (str(value) if value is not None else "")
                )
            current = self._normalized_transaction_values(row.values)
            if any(
                not self._transaction_value_matches(key, current.get(key), value)
                for key, value in expected.items()
            ):
                raise StorageConflictError(
                    "A selected transaction changed; review the current rows and try again."
                )
            selected_rows[transaction_id] = row
            current_by_id_values[transaction_id] = current
        return selected_rows, current_by_id_values

    @staticmethod
    def _transaction_value_matches(key: str, actual: Any, expected: Any) -> bool:
        if key == "amount":
            return _decimal_values_match(actual, str(expected))
        if key == "payee_id":
            return _clean_text(actual, "Payee") == _clean_text(expected, "Payee")
        if key == "tag_ids":
            return _normalize_tag_ids(actual) == _normalize_tag_ids(expected)
        return str(actual or "") == str(expected or "")

    @classmethod
    def _normalized_transaction_values(
        cls, values: Mapping[str, Any]
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for header in WORKSHEET_HEADERS["Transactions"]:
            value = values.get(header, "")
            if header == "amount":
                try:
                    normalized[header] = format(
                        Decimal(str(value).strip()).normalize(), "f"
                    )
                except (InvalidOperation, ValueError):
                    normalized[header] = str(value or "")
            elif header == "payee_id":
                normalized[header] = _clean_text(value, "Payee")
            elif header == "tag_ids":
                normalized[header] = _encode_tag_ids(value)
            else:
                normalized[header] = str(value or "")
        return normalized

    @classmethod
    def _transaction_rows_match(
        cls, actual: Mapping[str, Any], expected: Mapping[str, Any]
    ) -> bool:
        return all(
            cls._transaction_value_matches(
                header, actual.get(header), expected.get(header)
            )
            for header in WORKSHEET_HEADERS["Transactions"]
        )

    @staticmethod
    def _reject_mixed_use_projection(transaction: Mapping[str, Any]) -> None:
        source_type = _clean_text(
            transaction.get("source_type"), "Transaction source type"
        )
        source_id = _clean_text(transaction.get("source_id"), "Transaction source ID")
        if not source_type and not source_id:
            return
        if bool(source_type) != bool(source_id):
            raise StorageValidationError(
                "Transaction source type and source ID must be provided together"
            )
        if source_type != MIXED_USE_SOURCE_TYPE:
            raise StorageValidationError("Transaction source type is unsupported")
        raise StorageValidationError(
            "Mixed-use projections must be changed through mixed-use expense APIs"
        )

    def bulk_change_transaction_category(
        self,
        transaction_ids: Sequence[str],
        *,
        expected_transactions: Sequence[Mapping[str, Any]],
        category_id: str,
    ) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            return self._bulk_change_transaction_category(
                transaction_ids,
                expected_transactions=expected_transactions,
                category_id=category_id,
            )

    def _bulk_change_transaction_category(
        self,
        transaction_ids: Sequence[str],
        *,
        expected_transactions: Sequence[Mapping[str, Any]],
        category_id: str,
    ) -> dict[str, str]:
        """Revalidate and change categories with one atomic minimal-cell batch."""
        selected_rows, current_by_id = self._fresh_bulk_transaction_snapshot(
            transaction_ids, expected_transactions
        )
        for transaction in current_by_id.values():
            self._reject_mixed_use_projection(transaction)
        categories = self._category_lookup(force_refresh=True)
        category_id = _clean_text(category_id, "Category", required=True)
        target = categories.get(category_id)
        if target is None:
            raise StorageValidationError("Category does not exist")
        kinds = {transaction["kind"] for transaction in current_by_id.values()}
        if len(kinds) != 1 or kinds == {"Transfer"}:
            raise StorageValidationError(
                "Category changes require a homogeneous Income or Expense selection"
            )
        kind = next(iter(kinds))
        if kind not in {"Income", "Expense"} or target["kind"] != kind:
            raise StorageValidationError(
                "The selected category must match the transaction kind"
            )
        if all(transaction["category_id"] == category_id for transaction in current_by_id.values()):
            return {"status": "fully_applied", "count": "0"}
        pending_by_id = {
            transaction_id: transaction
            for transaction_id, transaction in current_by_id.items()
            if transaction["category_id"] != category_id
        }

        headers = self._headers("Transactions")
        category_column = self._sheet_column_index(headers, "category_id")
        sheet_id = self._transactions_sheet_id()
        def write() -> None:
            requests = [
                {
                    "updateCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": selected_rows[transaction_id].row_number - 1,
                            "endRowIndex": selected_rows[transaction_id].row_number,
                            "startColumnIndex": category_column,
                            "endColumnIndex": category_column + 1,
                        },
                        "rows": [
                            {"values": [{"userEnteredValue": {"stringValue": category_id}}]}
                        ],
                        "fields": "userEnteredValue",
                    }
                }
                for transaction_id in pending_by_id
            ]
            self._batch_update_spreadsheet(requests)

        def state() -> str:
            current = {
                str(row.values["id"]): self._normalized_transaction_values(row.values)
                for row in self._rows("Transactions", force_refresh=True)
            }
            if all(
                item in current and current[item].get("category_id") == category_id
                for item in pending_by_id
            ):
                return "applied"
            if all(
                item in current
                and self._transaction_rows_match(current[item], pending_by_id[item])
                for item in pending_by_id
            ):
                return "unchanged"
            return "ambiguous"

        def refresh() -> None:
            nonlocal selected_rows, current_by_id
            selected_rows, current_by_id = self._fresh_bulk_transaction_snapshot(
                transaction_ids, expected_transactions
            )
            for transaction in current_by_id.values():
                self._reject_mixed_use_projection(transaction)

        self._write_with_uncertain_readback(
            "category change", write, state, before_retry=refresh, invalidate=("Transactions",)
        )
        return {"status": "fully_applied", "count": str(len(pending_by_id))}

    def bulk_delete_transactions(
        self,
        transaction_ids: Sequence[str],
        *,
        expected_transactions: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        """Revalidate and delete transactions with one atomic row-index batch."""
        with _MIXED_USE_CREATE_LOCK:
            selected_rows, current_by_id = self._fresh_bulk_transaction_snapshot(
                transaction_ids, expected_transactions
            )
            for transaction in current_by_id.values():
                self._reject_mixed_use_projection(transaction)
            sheet_id = self._transactions_sheet_id()
            original_by_id = dict(current_by_id)

            def write() -> None:
                requests = [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": selected_rows[transaction_id].row_number - 1,
                                "endIndex": selected_rows[transaction_id].row_number,
                            }
                        }
                    }
                    for transaction_id in sorted(
                        selected_rows,
                        key=lambda item: selected_rows[item].row_number,
                        reverse=True,
                    )
                ]
                self._batch_update_spreadsheet(requests)

            def state() -> str:
                current = {
                    str(row.values["id"]): self._normalized_transaction_values(row.values)
                    for row in self._rows("Transactions", force_refresh=True)
                }
                if not any(item in current for item in original_by_id):
                    return "applied"
                if all(
                    item in current
                    and self._transaction_rows_match(current[item], value)
                    for item, value in original_by_id.items()
                ):
                    return "unchanged"
                return "ambiguous"

            def refresh() -> None:
                nonlocal selected_rows, current_by_id
                selected_rows, current_by_id = self._fresh_bulk_transaction_snapshot(
                    transaction_ids, expected_transactions
                )
                if current_by_id != original_by_id:
                    raise StorageConflictError(
                        "A selected transaction changed while deletion was being retried."
                    )
                for transaction in current_by_id.values():
                    self._reject_mixed_use_projection(transaction)

            self._write_with_uncertain_readback(
                "transaction deletion", write, state,
                before_retry=refresh, invalidate=("Transactions",),
            )
            return {"status": "fully_applied", "count": str(len(selected_rows))}

    def _account_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
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

    def _prepare_transaction(
        self,
        data: Mapping[str, Any],
        *,
        transaction_id: str | None = None,
        created_at: str | None = None,
        accounts: Mapping[str, Mapping[str, Any]] | None = None,
        categories: Mapping[str, Mapping[str, str]] | None = None,
        payees: Mapping[str, Mapping[str, str]] | None = None,
        tags: Mapping[str, Mapping[str, str]] | None = None,
        original_transaction: Mapping[str, Any] | None = None,
        preserve_existing_payee: bool = False,
    ) -> dict[str, str]:
        payees_force_refresh = True
        tags_force_refresh = True
        if accounts is None and categories is None:
            self._snapshot(
                ["Accounts", "Categories", "Payees", "Tags"],
                force_refresh=True,
            )
            accounts = self._account_lookup()
            categories = self._category_lookup()
            payees_force_refresh = False
            tags_force_refresh = False
        else:
            accounts = accounts or self._account_lookup(force_refresh=True)
            categories = categories or self._category_lookup(force_refresh=True)
        payees = (
            dict(payees)
            if payees is not None
            else self._payee_lookup(force_refresh=payees_force_refresh)
        )
        tags = (
            dict(tags)
            if tags is not None
            else self._tag_lookup(force_refresh=tags_force_refresh)
        )
        kind = _clean_text(data.get("kind"), "Transaction kind", required=True).title()
        if kind not in TRANSACTION_KINDS:
            raise StorageValidationError("Unknown transaction kind")
        account_id = _clean_text(data.get("account_id"), "Account", required=True)
        if account_id not in accounts:
            raise StorageValidationError("Source account does not exist")
        original_account_id = (
            _clean_text(original_transaction.get("account_id"), "Account")
            if original_transaction is not None
            else None
        )
        if not _as_bool(accounts[account_id]["active"]) and account_id != original_account_id:
            raise StorageValidationError("Source account is inactive")

        to_account_id = _clean_text(data.get("to_account_id"), "Destination account")
        category_id = _clean_text(data.get("category_id"), "Category")
        if kind == "Transfer":
            if to_account_id not in accounts:
                raise StorageValidationError("Destination account does not exist")
            original_to_account_id = (
                _clean_text(
                    original_transaction.get("to_account_id"),
                    "Destination account",
                )
                if original_transaction is not None
                else None
            )
            if not _as_bool(accounts[to_account_id]["active"]) and to_account_id != original_to_account_id:
                raise StorageValidationError("Destination account is inactive")
            if to_account_id == account_id:
                raise StorageValidationError("Transfer accounts must be different")
            category_id = ""
        else:
            if to_account_id:
                raise StorageValidationError(
                    "Only transfers can have a destination account"
                )
            if category_id not in categories:
                raise StorageValidationError("Category does not exist")
            if categories[category_id]["kind"] != kind:
                raise StorageValidationError("Category kind does not match transaction kind")

        txn_date = _iso_date(data.get("txn_date"))
        amount = _positive_amount(data.get("amount"))
        receipt_references = (
            _encode_receipt_references(data.get("receipt_references", []))
            if transaction_id is None
            or data.get("receipt_references", "") != ""
            else ""
        )
        payee_id = _clean_text(data.get("payee_id"), "Payee")
        new_payee_name = _clean_text(data.get("new_payee_name"), "New payee")
        legacy_payee = _clean_text(data.get("payee"), "Payee")
        if legacy_payee:
            raise StorageValidationError(
                "Transactions must reference a stored payee"
            )
        if payee_id and new_payee_name:
            raise StorageValidationError(
                "Choose an existing payee or add a new payee"
            )
        tag_ids = _normalize_tag_ids(data.get("tag_ids", ""))
        original_tag_ids = (
            _normalize_tag_ids(original_transaction.get("tag_ids", ""))
            if original_transaction is not None
            else []
        )
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
                raise StorageValidationError("Tag is inactive")
        original_payee_id = (
            _clean_text(original_transaction.get("payee_id"), "Payee")
            if original_transaction is not None
            else None
        )
        if (
            preserve_existing_payee
            and original_payee_id
            and not payee_id
            and new_payee_name
        ):
            if original_payee_id not in payees:
                raise StorageValidationError("Payee does not exist")
            payee_id = original_payee_id
            new_payee_name = ""
        if not payee_id and new_payee_name:
            new_payee = self.create_payee(new_payee_name)
            payee_id = new_payee["id"]
            payees[payee_id] = new_payee
        if payee_id and payee_id not in payees:
            raise StorageValidationError("Payee does not exist")
        if (
            payee_id
            and not _as_bool(payees[payee_id]["active"], "Payee active")
            and payee_id != original_payee_id
        ):
            raise StorageValidationError("Payee is inactive")
        new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
        if new_tag_name:
            new_tag = self.create_tag(new_tag_name)
            if new_tag["id"] not in tag_ids:
                tag_ids.append(new_tag["id"])
            tags[new_tag["id"]] = new_tag
            tag_ids = _normalize_tag_ids(tag_ids)
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
                raise StorageValidationError("Tag is inactive")
        record = {
            "id": transaction_id or str(uuid4()),
            "txn_date": txn_date,
            "kind": kind,
            "amount": amount,
            "account_id": account_id,
            "to_account_id": to_account_id,
            "category_id": category_id,
            "payee_id": payee_id,
            "payee": payees.get(payee_id, {}).get("name", ""),
            "description": _clean_text(data.get("description"), "Description"),
            "reference": _clean_text(data.get("reference"), "Reference"),
            "receipt_references": receipt_references,
            "tag_ids": _encode_tag_ids(tag_ids),
            "created_at": created_at or _utc_now(),
        }
        if original_transaction is not None:
            source_type = _clean_text(
                original_transaction.get("source_type"),
                "Transaction source type",
            )
            source_id = _clean_text(
                original_transaction.get("source_id"),
                "Transaction source ID",
            )
            if bool(source_type) != bool(source_id):
                raise StorageValidationError(
                    "Transaction source type and source ID must be provided together"
                )
            if source_type:
                if source_type != MIXED_USE_SOURCE_TYPE:
                    raise StorageValidationError("Transaction source type is unsupported")
                record["source_type"] = source_type
                record["source_id"] = source_id
        return record

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
        for row in self._rows("Transactions", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Transaction ID", required=True)
            item["txn_date"] = _iso_date(item.get("txn_date"))
            item["kind"] = _clean_text(
                item.get("kind"), "Transaction kind", required=True
            ).title()
            if item["kind"] not in TRANSACTION_KINDS:
                raise StorageValidationError("Unknown transaction kind")
            item["amount"] = _positive_amount(item.get("amount"))
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
            item["source_type"] = _clean_text(
                item.get("source_type"), "Transaction source type"
            )
            item["source_id"] = _clean_text(
                item.get("source_id"), "Transaction source ID"
            )
            if bool(item["source_type"]) != bool(item["source_id"]):
                raise StorageValidationError(
                    "Transaction source type and source ID must be provided together"
                )
            if item["source_type"] and item["source_type"] != MIXED_USE_SOURCE_TYPE:
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

    def create_transaction(self, **data: Any) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            # Generic transaction creation cannot manufacture a derived
            # projection. Mixed-use projections are created only as the paired
            # result of create_mixed_use_expense.
            if data.get("source_type") or data.get("source_id"):
                self._reject_mixed_use_projection(data)
            record = self._prepare_transaction(data)
            self._append("Transactions", record)
            return record

    def edit_transaction(self, transaction_id: str, **changes: Any) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            return self._edit_transaction(transaction_id, **changes)

    def _edit_transaction(self, transaction_id: str, **changes: Any) -> dict[str, str]:
        transaction_id = _clean_text(transaction_id, "Transaction ID", required=True)
        current = self._find_row("Transactions", transaction_id)
        self._reject_mixed_use_projection(current.values)
        merged = dict(current.values)
        merged.update(changes)
        updated = self._prepare_transaction(
            merged,
            transaction_id=transaction_id,
            created_at=current.values["created_at"],
            original_transaction=current.values,
        )
        self._replace_row("Transactions", current, updated)
        return updated

    def delete_transaction(self, transaction_id: str) -> None:
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Transactions", transaction_id)
            self._reject_mixed_use_projection(current.values)
            original = dict(current.values)
            current_row = current
            worksheet = self._worksheet("Transactions")

            def write() -> None:
                self._api(
                    lambda: worksheet.delete_rows(current_row.row_number),
                    retry_safe=False,
                )

            def state() -> str:
                try:
                    latest = self._find_row("Transactions", transaction_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh() -> None:
                nonlocal current_row
                current_row = self._find_row("Transactions", transaction_id)
                self._reject_mixed_use_projection(current_row.values)
                if current_row.values != original:
                    raise StorageConflictError(
                        "The transaction changed while deletion was being retried."
                    )

            self._write_with_uncertain_readback(
                "transaction deletion", write, state, before_retry=refresh,
                invalidate=("Transactions",),
            )

    @_active_ledger_mutation_lock
    def import_csv_transactions(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        """Validate all CSV-style rows, then append them in one API request."""
        self._snapshot(["Accounts", "Categories"], force_refresh=True)
        accounts = self._account_lookup()
        categories = self._category_lookup()
        accounts_by_name = {
            account["name"].casefold(): account for account in accounts.values()
        }
        categories_by_name = {
            (category["name"].casefold(), category["kind"]): category
            for category in categories.values()
        }
        payees = self._payee_lookup(force_refresh=True)
        tags = self._tag_lookup(force_refresh=True)
        prepared: list[dict[str, str]] = []
        payee_names: list[str] = []
        for index, row in enumerate(rows, start=2):
            kind = _clean_text(row.get("Type"), "Type", required=True).title()
            if kind not in CATEGORY_KINDS:
                raise StorageValidationError(
                    f"CSV row {index}: Type must be Income or Expense"
                )
            account_name = _clean_text(row.get("Account"), "Account", required=True)
            category_name = _clean_text(row.get("Category"), "Category", required=True)
            account = accounts_by_name.get(account_name.casefold())
            category = categories_by_name.get((category_name.casefold(), kind))
            if account is None or category is None:
                raise StorageValidationError(
                    f"CSV row {index}: unknown account or category"
                )
            prepared.append(
                self._prepare_transaction(
                    {
                        "txn_date": row.get("Date"),
                        "kind": kind,
                        "amount": row.get("Amount"),
                        "account_id": account["id"],
                        "category_id": category["id"],
                        "payee_id": "",
                        "new_payee_name": "",
                        "description": row.get("Description", ""),
                        "reference": row.get("Reference", ""),
                    },
                    accounts=accounts,
                    categories=categories,
                    payees=payees,
                    tags=tags,
                )
            )
            payee_names.append(_clean_text(row.get("Payee", ""), "New payee"))
        payees = self._ensure_payee_names(payee_names)
        payee_ids_by_name = {
            normalize_payee_name(item["name"]): item for item in payees.values()
        }
        for record, name in zip(prepared, payee_names):
            if name:
                payee = payee_ids_by_name[normalize_payee_name(name)]
                record["payee_id"] = payee["id"]
                record["payee"] = payee["name"]
        self._append_many("Transactions", prepared)
        return prepared

    def preview_quickbooks_transactions(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        auto_create: bool = False,
        _force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Validate and summarize a QuickBooks export without writing anything."""
        source_rows = list(rows)
        self._snapshot(
            ["Accounts", "Categories", "Transactions", "Payees", "Tags"],
            force_refresh=_force_refresh,
        )
        accounts = self._account_lookup()
        categories = self._category_lookup()
        new_accounts, new_categories = missing_references(
            source_rows, accounts.values(), categories.values()
        )
        if auto_create:
            for name in new_accounts:
                item = {"id": f"pending-account:{name.casefold()}", "name": name, "active": True}
                accounts[item["id"]] = item
            for name, kind in new_categories:
                item = {"id": f"pending-category:{kind}:{name.casefold()}", "name": name, "kind": kind}
                categories[item["id"]] = item
        normalized, errors = normalize_rows(
            source_rows, accounts.values(), categories.values()
        )
        payee_names = {
            normalize_payee_name(item["name"]): item["name"]
            for item in self.list_payees()
        }
        existing = {
            fingerprint(item)
            for item in self.list_transactions()
        }
        seen: set[str] = set()
        ready: list[dict[str, str]] = []
        duplicate_rows: list[int] = []
        for item in normalized:
            payee_key = normalize_payee_name(item.get("payee", ""))
            if payee_key:
                item["payee"] = payee_names.setdefault(
                    payee_key, item["payee"]
                )
            row_number = int(item.pop("_source_row"))
            identity = fingerprint(item)
            if identity in existing or identity in seen:
                duplicate_rows.append(row_number)
            else:
                seen.add(identity)
                ready.append(item)
        counts = {kind: sum(item["kind"] == kind for item in ready) for kind in TRANSACTION_KINDS}
        return {
            "rows": ready,
            "errors": errors,
            "duplicate_rows": duplicate_rows,
            "new_accounts": new_accounts,
            "new_account_types": {
                name: suggested_account_type(name) for name in new_accounts
            },
            "new_account_classifications": {
                name: suggested_account_classification(
                    name, suggested_account_type(name)
                )
                for name in new_accounts
            },
            "new_categories": new_categories,
            "summary": {"ready": len(ready), "duplicates": len(duplicate_rows), **counts},
        }

    @_active_ledger_mutation_lock
    def import_quickbooks_transactions(
        self, rows: Iterable[Mapping[str, Any]], *, auto_create: bool = False
    ) -> list[dict[str, str]]:
        """Revalidate a QuickBooks export, then atomically batch append unique rows."""
        source_rows = list(rows)
        preview = self.preview_quickbooks_transactions(
            source_rows,
            auto_create=auto_create,
            _force_refresh=True,
        )
        if preview["errors"]:
            raise StorageValidationError("\n".join(preview["errors"]))
        if auto_create:
            now = _utc_now()
            account_records = [
                {
                    "id": str(uuid4()),
                    "name": name,
                    "type": preview["new_account_types"][name],
                    "classification": preview[
                        "new_account_classifications"
                    ][name],
                    "opening_balance": "0.00",
                    "active": "TRUE",
                    "created_at": now,
                    "parent_id": "",
                }
                for name in preview["new_accounts"]
            ]
            category_records = [
                {
                    "id": str(uuid4()),
                    "name": name,
                    "kind": kind,
                    "parent_id": "",
                }
                for name, kind in preview["new_categories"]
            ]
            _validate_hierarchy_records(
                [*self.list_accounts(active_only=False), *account_records],
                compatibility_field="classification",
                item_label="Account",
            )
            _validate_hierarchy_records(
                [*self.list_categories(), *category_records],
                compatibility_field="kind",
                item_label="Category",
            )
            self._append_many("Accounts", account_records)
            self._append_many("Categories", category_records)
            preview = self.preview_quickbooks_transactions(
                source_rows,
                _force_refresh=True,
            )
            if preview["errors"]:
                raise StorageValidationError("\n".join(preview["errors"]))
        if not preview["rows"]:
            return []
        accounts = self._account_lookup()
        categories = self._category_lookup()
        payees = self._ensure_payee_names(
            item.get("payee", "") for item in preview["rows"]
        )
        payee_ids_by_name = {
            normalize_payee_name(item["name"]): item["id"]
            for item in payees.values()
        }
        tags = self._tag_lookup()
        prepared = [
            self._prepare_transaction(
                {
                    **item,
                    "payee_id": payee_ids_by_name.get(
                        normalize_payee_name(item.get("payee", "")), ""
                    ),
                    "new_payee_name": "",
                    "payee": "",
                },
                accounts=accounts,
                categories=categories,
                payees=payees,
                tags=tags,
            )
            for item in preview["rows"]
        ]
        self._append_many("Transactions", prepared)
        return prepared

__all__ = ["TransactionsMixin"]
