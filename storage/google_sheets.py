"""Google Sheets persistence for Plain Ledger.

The UI interacts with this module through dictionaries containing domain fields;
Google worksheet objects, row numbers, and API exceptions stay inside this layer.
"""

from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, TypeVar
from uuid import uuid4

import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials


WORKSHEET_HEADERS = {
    "Accounts": ("id", "name", "type", "opening_balance", "active", "created_at"),
    "Categories": ("id", "name", "kind"),
    "Transactions": (
        "id",
        "txn_date",
        "kind",
        "amount",
        "account_id",
        "to_account_id",
        "category_id",
        "payee",
        "description",
        "reference",
        "created_at",
    ),
}
ACCOUNT_TYPES = {"Bank", "Cash", "Credit card", "Loan", "Other"}
CATEGORY_KINDS = {"Income", "Expense"}
TRANSACTION_KINDS = {"Income", "Expense", "Transfer"}
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_ACCOUNTS = (("Checking", "Bank"), ("Cash", "Cash"))
DEFAULT_CATEGORIES = {
    "Income": ("Sales", "Services", "Interest", "Other income"),
    "Expense": (
        "Advertising",
        "Bank fees",
        "Insurance",
        "Meals",
        "Office",
        "Professional fees",
        "Rent",
        "Software",
        "Supplies",
        "Travel",
        "Utilities",
        "Other expense",
    ),
}


class StorageError(RuntimeError):
    """Base class for safe, user-displayable storage errors."""


class StorageUnavailableError(StorageError):
    """Raised when Google Sheets cannot complete an API operation."""


class StorageValidationError(StorageError):
    """Raised when domain data is invalid."""


class StorageConflictError(StorageError):
    """Raised when a uniqueness constraint would be violated."""


class StorageNotFoundError(StorageError):
    """Raised when an ID no longer exists."""


@dataclass(frozen=True)
class _StoredRow:
    row_number: int
    values: dict[str, str]


T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(value: Any, field: str, *, required: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        text = ""
    else:
        text = str(value).strip()
    if required and not text:
        raise StorageValidationError(f"{field} is required")
    return text


def _positive_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Amount must be numeric") from None
    if not amount.is_finite() or amount <= 0:
        raise StorageValidationError("Amount must be greater than zero")
    return format(amount.quantize(Decimal("0.01")), "f")


def _balance_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Opening balance must be numeric") from None
    if not amount.is_finite():
        raise StorageValidationError("Opening balance must be finite")
    return format(amount.quantize(Decimal("0.01")), "f")


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = _clean_text(value, "Date", required=True)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise StorageValidationError("Date must use YYYY-MM-DD format") from None


def _as_bool(value: Any, field: str = "active") -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise StorageValidationError(f"{field} must be true or false")


class GoogleSheetsStorage:
    """Validated CRUD and export operations for the ledger workbook."""

    def __init__(self, workbook: Any):
        self._workbook = workbook
        self.validate_headers()

    @classmethod
    def from_secrets(cls, secrets: Mapping[str, Any]) -> "GoogleSheetsStorage":
        """Create a storage client from Streamlit-compatible secrets."""
        try:
            credential_info = dict(secrets["gcp_service_account"])
            spreadsheet_id = str(secrets["spreadsheet_id"])
            credentials = Credentials.from_service_account_info(
                credential_info, scopes=[SHEETS_SCOPE]
            )
            workbook = gspread.authorize(credentials).open_by_key(spreadsheet_id)
        except (KeyError, TypeError, ValueError, GoogleAuthError, gspread.GSpreadException) as exc:
            raise StorageUnavailableError(
                "Google Sheets authentication or workbook access failed"
            ) from exc
        return cls(workbook)

    @property
    def workbook_title(self) -> str:
        return str(self._workbook.title)

    def _api(self, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except (GoogleAuthError, gspread.GSpreadException, OSError) as exc:
            raise StorageUnavailableError(
                "Google Sheets is temporarily unavailable; no success was reported"
            ) from exc

    def _worksheet(self, title: str) -> Any:
        return self._api(lambda: self._workbook.worksheet(title))

    def _headers(self, title: str) -> list[str]:
        headers = [str(value).strip() for value in self._api(
            lambda: self._worksheet(title).row_values(1)
        )]
        required = set(WORKSHEET_HEADERS[title])
        if not headers:
            raise StorageValidationError(f"{title} header row is empty")
        if any(not header for header in headers):
            raise StorageValidationError(f"{title} has a blank header")
        if len(headers) != len(set(headers)):
            raise StorageValidationError(f"{title} has duplicate headers")
        missing = sorted(required - set(headers))
        if missing:
            raise StorageValidationError(
                f"{title} is missing headers: {', '.join(missing)}"
            )
        return headers

    def validate_headers(self) -> None:
        """Validate required worksheets and headers without relying on positions."""
        try:
            actual_titles = {
                worksheet.title for worksheet in self._api(self._workbook.worksheets)
            }
        except AttributeError as exc:
            raise StorageValidationError("Invalid workbook object") from exc
        missing = sorted(set(WORKSHEET_HEADERS) - actual_titles)
        if missing:
            raise StorageValidationError(
                "Workbook is missing worksheets: " + ", ".join(missing)
            )
        for title in WORKSHEET_HEADERS:
            self._headers(title)

    def ensure_defaults(self) -> dict[str, int]:
        """Seed only missing default accounts/categories using batch writes."""
        existing_accounts = self.list_accounts(active_only=False)
        account_names = {account["name"].casefold() for account in existing_accounts}
        timestamp = _utc_now()
        new_accounts = [
            {
                "id": str(uuid4()),
                "name": name,
                "type": account_type,
                "opening_balance": "0.00",
                "active": "TRUE",
                "created_at": timestamp,
            }
            for name, account_type in DEFAULT_ACCOUNTS
            if name.casefold() not in account_names
        ]

        existing_categories = self.list_categories()
        category_keys = {
            (category["name"].casefold(), category["kind"])
            for category in existing_categories
        }
        new_categories = [
            {"id": str(uuid4()), "name": name, "kind": kind}
            for kind, names in DEFAULT_CATEGORIES.items()
            for name in names
            if (name.casefold(), kind) not in category_keys
        ]

        self._append_many("Accounts", new_accounts)
        self._append_many("Categories", new_categories)
        return {"accounts": len(new_accounts), "categories": len(new_categories)}

    def _rows(self, title: str) -> list[_StoredRow]:
        worksheet = self._worksheet(title)
        values = self._api(worksheet.get_all_values)
        if not values:
            raise StorageValidationError(f"{title} header row is empty")
        headers = [str(value).strip() for value in values[0]]
        self._headers(title)
        rows: list[_StoredRow] = []
        for row_number, raw_row in enumerate(values[1:], start=2):
            padded = [str(value) for value in raw_row] + [""] * (
                len(headers) - len(raw_row)
            )
            record = dict(zip(headers, padded[: len(headers)]))
            if any(value.strip() for value in record.values()):
                rows.append(_StoredRow(row_number, record))
        return rows

    def _find_row(self, title: str, record_id: str) -> _StoredRow:
        record_id = _clean_text(record_id, "ID", required=True)
        matches = [row for row in self._rows(title) if row.values.get("id") == record_id]
        if not matches:
            raise StorageNotFoundError(f"{title[:-1]} no longer exists")
        if len(matches) > 1:
            raise StorageValidationError(f"Duplicate ID detected in {title}")
        return matches[0]

    def _append(self, title: str, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        self._api(lambda: worksheet.append_row(values, value_input_option="RAW"))

    def _append_many(self, title: str, records: Iterable[Mapping[str, Any]]) -> None:
        records = list(records)
        if not records:
            return
        headers = self._headers(title)
        values = [
            [str(record.get(header, "")) for header in headers] for record in records
        ]
        worksheet = self._worksheet(title)
        self._api(lambda: worksheet.append_rows(values, value_input_option="RAW"))

    def _replace_row(self, title: str, row: _StoredRow, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        self._api(
            lambda: worksheet.update(
                [values], range_name=f"A{row.row_number}", raw=True
            )
        )

    def list_accounts(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        accounts = []
        for row in self._rows("Accounts"):
            record: dict[str, Any] = dict(row.values)
            record["active"] = _as_bool(record.get("active", ""))
            record["opening_balance"] = float(
                _balance_amount(record.get("opening_balance", ""))
            )
            if not active_only or record["active"]:
                accounts.append(record)
        return sorted(accounts, key=lambda item: item["name"].casefold())

    def create_account(
        self, name: str, account_type: str, opening_balance: Any = 0
    ) -> dict[str, Any]:
        name = _clean_text(name, "Account name", required=True)
        account_type = _clean_text(account_type, "Account type", required=True)
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError("Unknown account type")
        if any(
            account["name"].casefold() == name.casefold()
            for account in self.list_accounts(active_only=False)
        ):
            raise StorageConflictError("Account names must be unique")
        record = {
            "id": str(uuid4()),
            "name": name,
            "type": account_type,
            "opening_balance": _balance_amount(opening_balance),
            "active": "TRUE",
            "created_at": _utc_now(),
        }
        self._append("Accounts", record)
        return dict(record)

    def edit_account(self, account_id: str, **changes: Any) -> dict[str, Any]:
        current = self._find_row("Accounts", account_id)
        updated = dict(current.values)
        name = _clean_text(changes.get("name", updated["name"]), "Account name", required=True)
        account_type = _clean_text(
            changes.get("type", updated["type"]), "Account type", required=True
        )
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError("Unknown account type")
        if any(
            account["id"] != account_id
            and account["name"].casefold() == name.casefold()
            for account in self.list_accounts(active_only=False)
        ):
            raise StorageConflictError("Account names must be unique")
        updated.update(
            {
                "name": name,
                "type": account_type,
                "opening_balance": _balance_amount(
                    changes.get("opening_balance", updated["opening_balance"])
                ),
                "active": "TRUE"
                if _as_bool(changes.get("active", updated["active"]))
                else "FALSE",
            }
        )
        self._replace_row("Accounts", current, updated)
        return updated

    def deactivate_account(self, account_id: str) -> dict[str, Any]:
        return self.edit_account(account_id, active=False)

    def list_categories(self, kind: str | None = None) -> list[dict[str, str]]:
        if kind is not None and kind not in CATEGORY_KINDS:
            raise StorageValidationError("Unknown category kind")
        categories = [dict(row.values) for row in self._rows("Categories")]
        if kind is not None:
            categories = [item for item in categories if item["kind"] == kind]
        return sorted(categories, key=lambda item: (item["kind"], item["name"].casefold()))

    def create_category(self, name: str, kind: str) -> dict[str, str]:
        name = _clean_text(name, "Category name", required=True)
        kind = _clean_text(kind, "Category kind", required=True).title()
        if kind not in CATEGORY_KINDS:
            raise StorageValidationError("Category kind must be Income or Expense")
        if any(
            category["name"].casefold() == name.casefold()
            and category["kind"] == kind
            for category in self.list_categories()
        ):
            raise StorageConflictError("That category already exists")
        record = {"id": str(uuid4()), "name": name, "kind": kind}
        self._append("Categories", record)
        return record

    def _account_lookup(self) -> dict[str, dict[str, Any]]:
        return {
            account["id"]: account for account in self.list_accounts(active_only=False)
        }

    def _category_lookup(self) -> dict[str, dict[str, str]]:
        return {category["id"]: category for category in self.list_categories()}

    def _prepare_transaction(
        self,
        data: Mapping[str, Any],
        *,
        transaction_id: str | None = None,
        created_at: str | None = None,
        accounts: Mapping[str, Mapping[str, Any]] | None = None,
        categories: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict[str, str]:
        accounts = accounts or self._account_lookup()
        categories = categories or self._category_lookup()
        kind = _clean_text(data.get("kind"), "Transaction kind", required=True).title()
        if kind not in TRANSACTION_KINDS:
            raise StorageValidationError("Unknown transaction kind")
        account_id = _clean_text(data.get("account_id"), "Account", required=True)
        if account_id not in accounts:
            raise StorageValidationError("Source account does not exist")
        if not _as_bool(accounts[account_id]["active"]):
            raise StorageValidationError("Source account is inactive")

        to_account_id = _clean_text(data.get("to_account_id"), "Destination account")
        category_id = _clean_text(data.get("category_id"), "Category")
        if kind == "Transfer":
            if to_account_id not in accounts:
                raise StorageValidationError("Destination account does not exist")
            if not _as_bool(accounts[to_account_id]["active"]):
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

        return {
            "id": transaction_id or str(uuid4()),
            "txn_date": _iso_date(data.get("txn_date")),
            "kind": kind,
            "amount": _positive_amount(data.get("amount")),
            "account_id": account_id,
            "to_account_id": to_account_id,
            "category_id": category_id,
            "payee": _clean_text(data.get("payee"), "Payee"),
            "description": _clean_text(data.get("description"), "Description"),
            "reference": _clean_text(data.get("reference"), "Reference"),
            "created_at": created_at or _utc_now(),
        }

    def list_transactions(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, str]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        if kind is not None:
            kind = kind.title()
            if kind not in TRANSACTION_KINDS:
                raise StorageValidationError("Unknown transaction kind")
        transactions = []
        for row in self._rows("Transactions"):
            item = dict(row.values)
            if start_text and item["txn_date"] < start_text:
                continue
            if end_text and item["txn_date"] > end_text:
                continue
            if kind and item["kind"] != kind:
                continue
            transactions.append(item)
        return sorted(
            transactions,
            key=lambda item: (item["txn_date"], item["created_at"], item["id"]),
            reverse=True,
        )

    def create_transaction(self, **data: Any) -> dict[str, str]:
        record = self._prepare_transaction(data)
        self._append("Transactions", record)
        return record

    def edit_transaction(self, transaction_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Transactions", transaction_id)
        merged = dict(current.values)
        merged.update(changes)
        updated = self._prepare_transaction(
            merged,
            transaction_id=transaction_id,
            created_at=current.values["created_at"],
        )
        self._replace_row("Transactions", current, updated)
        return updated

    def delete_transaction(self, transaction_id: str) -> None:
        current = self._find_row("Transactions", transaction_id)
        worksheet = self._worksheet("Transactions")
        self._api(lambda: worksheet.delete_rows(current.row_number))

    def import_csv_transactions(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        """Validate all CSV-style rows, then append them in one API request."""
        accounts = self._account_lookup()
        categories = self._category_lookup()
        accounts_by_name = {
            account["name"].casefold(): account for account in accounts.values()
        }
        categories_by_name = {
            (category["name"].casefold(), category["kind"]): category
            for category in categories.values()
        }
        prepared = []
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
                        "payee": row.get("Payee", ""),
                        "description": row.get("Description", ""),
                        "reference": row.get("Reference", ""),
                    },
                    accounts=accounts,
                    categories=categories,
                )
            )
        self._append_many("Transactions", prepared)
        return prepared

    def export_backup_zip(self) -> bytes:
        """Return all ledger worksheets plus a timestamped row-count manifest."""
        generated_at = _utc_now()
        row_counts: dict[str, int] = {}
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(
            archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for title in WORKSHEET_HEADERS:
                headers = self._headers(title)
                rows = self._rows(title)
                row_counts[title] = len(rows)
                csv_buffer = io.StringIO(newline="")
                writer = csv.writer(csv_buffer, lineterminator="\n")
                writer.writerow(headers)
                for row in rows:
                    writer.writerow([row.values.get(header, "") for header in headers])
                archive.writestr(f"{title}.csv", csv_buffer.getvalue())
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {"backup_time": generated_at, "row_counts": row_counts},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        return archive_buffer.getvalue()
