"""Google Sheets persistence for Tabula Rosa.

The UI interacts with this module through dictionaries containing domain fields;
Google worksheet objects, row numbers, and API exceptions stay inside this layer.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import threading
import time
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

from quickbooks_import import (
    fingerprint,
    missing_references,
    normalize_rows,
    suggested_account_classification,
    suggested_account_type,
)


WORKSHEET_HEADERS = {
    "Accounts": (
        "id",
        "name",
        "type",
        "classification",
        "opening_balance",
        "active",
        "created_at",
    ),
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
    "Mileage": (
        "id",
        "trip_date",
        "miles",
        "vehicle",
        "start_location",
        "destination",
        "business_purpose",
        "notes",
        "created_at",
    ),
}
LEGACY_BACKUP_HEADERS = {
    title: headers
    for title, headers in WORKSHEET_HEADERS.items()
    if title != "Mileage"
}
ACCOUNT_TYPES = {
    "Bank",
    "Cash",
    "Credit card",
    "Short-term debt",
    "Equity",
    "Other",
}
ACCOUNT_CLASSIFICATIONS = {"Asset", "Liability", "Equity"}
FIXED_TYPE_CLASSIFICATIONS = {
    "Bank": "Asset",
    "Cash": "Asset",
    "Credit card": "Liability",
    "Short-term debt": "Liability",
    "Equity": "Equity",
}
CATEGORY_KINDS = {"Income", "Expense"}
TRANSACTION_KINDS = {"Income", "Expense", "Transfer"}
BACKUP_FORMAT_VERSION = 3
SUPPORTED_BACKUP_FORMAT_VERSIONS = {2, BACKUP_FORMAT_VERSION}
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

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


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


def _positive_miles(value: Any) -> str:
    try:
        miles = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Miles must be numeric") from None
    if not miles.is_finite() or miles <= 0:
        raise StorageValidationError("Miles must be greater than zero")
    return format(miles.quantize(Decimal("0.1")), "f")


def _balance_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Opening balance must be numeric") from None
    if not amount.is_finite():
        raise StorageValidationError("Opening balance must be finite")
    return format(amount.quantize(Decimal("0.01")), "f")


def _validate_account_classification(
    account_type: str, classification: str
) -> None:
    if classification not in ACCOUNT_CLASSIFICATIONS:
        raise StorageValidationError("Unknown account classification")
    expected = FIXED_TYPE_CLASSIFICATIONS.get(account_type)
    if expected is not None and classification != expected:
        raise StorageValidationError(
            f"{account_type} accounts must be classified as {expected}"
        )


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
    text = str(value).strip().casefold()
    if text == "true":
        return True
    if text == "false":
        return False
    raise StorageValidationError(f"{field} must be true or false")


def _parse_backup_zip(
    backup: bytes,
) -> tuple[dict[str, Any], dict[str, tuple[list[str], list[dict[str, str]]]]]:
    """Validate a ledger backup without extracting files to disk."""
    try:
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise StorageValidationError("Backup files are missing or duplicated")
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise StorageValidationError("Backup is too large to restore safely")
            manifest_bytes = archive.read("manifest.json")
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise StorageValidationError(
                    "Backup manifest is not valid UTF-8 JSON"
                ) from exc
            format_version = manifest.get("format_version")
            if format_version not in SUPPORTED_BACKUP_FORMAT_VERSIONS:
                raise StorageValidationError("Backup format version is unsupported")
            backup_headers = (
                WORKSHEET_HEADERS
                if format_version == BACKUP_FORMAT_VERSION
                else LEGACY_BACKUP_HEADERS
            )
            required_files = {
                f"{title}.csv" for title in backup_headers
            } | {"manifest.json"}
            if set(names) != required_files:
                raise StorageValidationError(
                    "Backup must contain exactly the expected CSV files and manifest.json"
                )
            csv_files = {
                title: archive.read(f"{title}.csv") for title in backup_headers
            }
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise StorageValidationError("Backup is not a readable ZIP archive") from exc

    row_counts = manifest.get("row_counts")
    file_hashes = manifest.get("sha256")
    worksheet_headers = manifest.get("worksheet_headers")
    if not all(isinstance(value, dict) for value in (row_counts, file_hashes, worksheet_headers)):
        raise StorageValidationError("Backup manifest is missing validation metadata")

    tables: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for title, content in csv_files.items():
        if hashlib.sha256(content).hexdigest() != file_hashes.get(f"{title}.csv"):
            raise StorageValidationError(f"{title} backup checksum does not match")
        try:
            parsed_rows = list(csv.reader(io.StringIO(content.decode("utf-8"), newline="")))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise StorageValidationError(f"{title} backup CSV is invalid") from exc
        if not parsed_rows:
            raise StorageValidationError(f"{title} backup has no header row")
        headers = [value.strip() for value in parsed_rows[0]]
        required_headers = set(backup_headers[title])
        if (
            any(not value for value in headers)
            or len(headers) != len(set(headers))
            or not required_headers.issubset(headers)
            or worksheet_headers.get(title) != headers
        ):
            raise StorageValidationError(f"{title} backup headers are invalid")
        records: list[dict[str, str]] = []
        for raw_row in parsed_rows[1:]:
            if len(raw_row) > len(headers):
                raise StorageValidationError(f"{title} backup has an over-wide row")
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            if any(value.strip() for value in padded):
                records.append(dict(zip(headers, padded)))
        if row_counts.get(title) != len(records):
            raise StorageValidationError(f"{title} backup row count does not match")
        record_ids = [record.get("id", "").strip() for record in records]
        if any(not record_id for record_id in record_ids) or len(record_ids) != len(
            set(record_ids)
        ):
            raise StorageValidationError(f"{title} backup IDs are missing or duplicated")
        tables[title] = (headers, records)

    account_ids = {record["id"] for record in tables["Accounts"][1]}
    category_ids = {record["id"] for record in tables["Categories"][1]}
    for transaction in tables["Transactions"][1]:
        if transaction.get("account_id") not in account_ids:
            raise StorageValidationError("Backup contains an unknown transaction account")
        to_account_id = transaction.get("to_account_id", "")
        if to_account_id and to_account_id not in account_ids:
            raise StorageValidationError("Backup contains an unknown transfer account")
        category_id = transaction.get("category_id", "")
        if category_id and category_id not in category_ids:
            raise StorageValidationError("Backup contains an unknown transaction category")
    return manifest, tables


class GoogleSheetsStorage:
    """Validated CRUD and export operations for the ledger workbook."""

    def __init__(
        self,
        workbook: Any,
        *,
        cache_ttl_seconds: float = 10.0,
        retry_attempts: int = 4,
        retry_base_delay_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._workbook = workbook
        self._cache_ttl_seconds = cache_ttl_seconds
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleeper = sleeper
        self._row_cache: dict[str, tuple[float, list[_StoredRow]]] = {}
        self._cache_lock = threading.RLock()
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
            actual_titles = {worksheet.title for worksheet in workbook.worksheets()}
            if "Mileage" not in actual_titles:
                headers = WORKSHEET_HEADERS["Mileage"]
                worksheet = workbook.add_worksheet(
                    title="Mileage", rows=1000, cols=len(headers)
                )
                worksheet.update([list(headers)], range_name="A1", raw=True)
        except (
            KeyError,
            TypeError,
            ValueError,
            GoogleAuthError,
            gspread.GSpreadException,
            OSError,
        ) as exc:
            raise StorageUnavailableError(
                "Google Sheets authentication or workbook access failed"
            ) from exc
        return cls(workbook)

    @property
    def workbook_title(self) -> str:
        return str(self._workbook.title)

    def _api(self, operation: Callable[[], T], *, retry_safe: bool = True) -> T:
        attempts = self._retry_attempts if retry_safe else 1
        for attempt in range(attempts):
            try:
                return operation()
            except (GoogleAuthError, gspread.GSpreadException, OSError) as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                temporary = isinstance(exc, OSError) or status_code in {
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not temporary or attempt + 1 >= attempts:
                    raise StorageUnavailableError(
                        "Google Sheets is temporarily unavailable; no success was reported",
                        retryable=temporary,
                    ) from exc
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))
        raise AssertionError("Retry loop exited unexpectedly")

    def _worksheet(self, title: str) -> Any:
        return self._api(lambda: self._workbook.worksheet(title))

    def _headers(self, title: str) -> list[str]:
        headers = [
            str(value).strip()
            for value in self._api(lambda: self._worksheet(title).row_values(1))
        ]
        self._validate_header_values(title, headers)
        return headers

    def _validate_header_values(self, title: str, headers: list[str]) -> None:
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
        existing_accounts = self.list_accounts(
            active_only=False, _force_refresh=True
        )
        account_names = {account["name"].casefold() for account in existing_accounts}
        timestamp = _utc_now()
        new_accounts = [
            {
                "id": str(uuid4()),
                "name": name,
                "type": account_type,
                "classification": suggested_account_classification(
                    name, account_type
                ),
                "opening_balance": "0.00",
                "active": "TRUE",
                "created_at": timestamp,
            }
            for name, account_type in DEFAULT_ACCOUNTS
            if name.casefold() not in account_names
        ]

        existing_categories = self.list_categories(_force_refresh=True)
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

    def _rows(self, title: str, *, force_refresh: bool = False) -> list[_StoredRow]:
        now = time.monotonic()
        if not force_refresh and self._cache_ttl_seconds > 0:
            with self._cache_lock:
                cached = self._row_cache.get(title)
                if cached and now - cached[0] < self._cache_ttl_seconds:
                    return list(cached[1])

        worksheet = self._worksheet(title)
        values = self._api(worksheet.get_all_values)
        if not values:
            raise StorageValidationError(f"{title} header row is empty")
        headers = [str(value).strip() for value in values[0]]
        self._validate_header_values(title, headers)
        rows: list[_StoredRow] = []
        for row_number, raw_row in enumerate(values[1:], start=2):
            padded = [str(value) for value in raw_row] + [""] * (
                len(headers) - len(raw_row)
            )
            record = dict(zip(headers, padded[: len(headers)]))
            if any(value.strip() for value in record.values()):
                rows.append(_StoredRow(row_number, record))
        with self._cache_lock:
            self._row_cache[title] = (time.monotonic(), rows)
        return list(rows)

    def _invalidate(self, title: str) -> None:
        with self._cache_lock:
            self._row_cache.pop(title, None)

    def _find_row(self, title: str, record_id: str) -> _StoredRow:
        record_id = _clean_text(record_id, "ID", required=True)
        matches = [
            row
            for row in self._rows(title, force_refresh=True)
            if row.values.get("id") == record_id
        ]
        if not matches:
            raise StorageNotFoundError(f"{title[:-1]} no longer exists")
        if len(matches) > 1:
            raise StorageValidationError(f"Duplicate ID detected in {title}")
        return matches[0]

    def _append(self, title: str, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        record_id = str(record.get("id", ""))
        for attempt in range(self._retry_attempts):
            try:
                self._api(
                    lambda: worksheet.append_row(values, value_input_option="RAW"),
                    retry_safe=False,
                )
                self._invalidate(title)
                return
            except StorageUnavailableError as error:
                self._invalidate(title)
                if not error.retryable:
                    raise
                try:
                    if record_id and any(
                        row.values.get("id") == record_id
                        for row in self._rows(title, force_refresh=True)
                    ):
                        return
                except StorageError:
                    pass
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))

    def _append_many(self, title: str, records: Iterable[Mapping[str, Any]]) -> None:
        records = list(records)
        if not records:
            return
        headers = self._headers(title)
        values = [
            [str(record.get(header, "")) for header in headers] for record in records
        ]
        worksheet = self._worksheet(title)
        record_ids = {str(record.get("id", "")) for record in records}
        for attempt in range(self._retry_attempts):
            try:
                self._api(
                    lambda: worksheet.append_rows(values, value_input_option="RAW"),
                    retry_safe=False,
                )
                self._invalidate(title)
                return
            except StorageUnavailableError as error:
                self._invalidate(title)
                if not error.retryable:
                    raise
                try:
                    existing_ids = {
                        row.values.get("id", "")
                        for row in self._rows(title, force_refresh=True)
                    }
                    present = record_ids & existing_ids
                    if present == record_ids:
                        return
                    if present:
                        raise StorageConflictError(
                            "Batch write completion could not be confirmed safely"
                        )
                except StorageUnavailableError:
                    pass
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))

    def _replace_row(self, title: str, row: _StoredRow, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        self._api(
            lambda: worksheet.update(
                [values], range_name=f"A{row.row_number}", raw=True
            )
        )
        self._invalidate(title)

    def list_accounts(
        self, *, active_only: bool = True, _force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        accounts = []
        for row in self._rows("Accounts", force_refresh=_force_refresh):
            record: dict[str, Any] = dict(row.values)
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
        if any(
            account["name"].casefold() == name.casefold()
            for account in self.list_accounts(
                active_only=False, _force_refresh=True
            )
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
        classification = _clean_text(
            changes.get("classification", updated["classification"]),
            "Account classification",
            required=True,
        ).title()
        _validate_account_classification(account_type, classification)
        if any(
            account["id"] != account_id
            and account["name"].casefold() == name.casefold()
            for account in self.list_accounts(
                active_only=False, _force_refresh=True
            )
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
            }
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
            for category in self.list_categories(_force_refresh=True)
        ):
            raise StorageConflictError("That category already exists")
        record = {"id": str(uuid4()), "name": name, "kind": kind}
        self._append("Categories", record)
        return record

    def edit_category(self, category_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Categories", category_id)
        updated = dict(current.values)
        name = _clean_text(
            changes.get("name", updated["name"]), "Category name", required=True
        )
        kind = _clean_text(
            changes.get("kind", updated["kind"]), "Category kind", required=True
        ).title()
        if kind not in CATEGORY_KINDS:
            raise StorageValidationError("Category kind must be Income or Expense")
        if any(
            category["id"] != category_id
            and category["name"].casefold() == name.casefold()
            and category["kind"] == kind
            for category in self.list_categories(_force_refresh=True)
        ):
            raise StorageConflictError("That category already exists")
        updated.update({"name": name, "kind": kind})
        self._replace_row("Categories", current, updated)
        return updated

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
    ) -> dict[str, str]:
        accounts = accounts or self._account_lookup(force_refresh=True)
        categories = categories or self._category_lookup(force_refresh=True)
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
        account_ids: Iterable[str] | None = None,
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
        for row in self._rows("Transactions"):
            item = dict(row.values)
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
        for attempt in range(self._retry_attempts):
            current = self._find_row("Transactions", transaction_id)
            worksheet = self._worksheet("Transactions")
            try:
                self._api(
                    lambda: worksheet.delete_rows(current.row_number),
                    retry_safe=False,
                )
                self._invalidate("Transactions")
                return
            except StorageUnavailableError as error:
                self._invalidate("Transactions")
                if not error.retryable:
                    raise
                try:
                    self._find_row("Transactions", transaction_id)
                except StorageNotFoundError:
                    return
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))

    def _prepare_mileage_trip(
        self,
        data: Mapping[str, Any],
        *,
        trip_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, str]:
        return {
            "id": trip_id or str(uuid4()),
            "trip_date": _iso_date(data.get("trip_date")),
            "miles": _positive_miles(data.get("miles")),
            "vehicle": _clean_text(data.get("vehicle"), "Vehicle"),
            "start_location": _clean_text(
                data.get("start_location"), "Starting location", required=True
            ),
            "destination": _clean_text(
                data.get("destination"), "Destination", required=True
            ),
            "business_purpose": _clean_text(
                data.get("business_purpose"), "Business purpose", required=True
            ),
            "notes": _clean_text(data.get("notes"), "Notes"),
            "created_at": created_at or _utc_now(),
        }

    def list_mileage_trips(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
    ) -> list[dict[str, str]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        trips = []
        for row in self._rows("Mileage"):
            item = dict(row.values)
            if start_text and item["trip_date"] < start_text:
                continue
            if end_text and item["trip_date"] > end_text:
                continue
            trips.append(item)
        return sorted(
            trips,
            key=lambda item: (item["trip_date"], item["created_at"], item["id"]),
            reverse=True,
        )

    def create_mileage_trip(self, **data: Any) -> dict[str, str]:
        record = self._prepare_mileage_trip(data)
        self._append("Mileage", record)
        return record

    def edit_mileage_trip(self, trip_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Mileage", trip_id)
        merged = dict(current.values)
        merged.update(changes)
        updated = self._prepare_mileage_trip(
            merged,
            trip_id=trip_id,
            created_at=current.values["created_at"],
        )
        self._replace_row("Mileage", current, updated)
        return updated

    def delete_mileage_trip(self, trip_id: str) -> None:
        for attempt in range(self._retry_attempts):
            current = self._find_row("Mileage", trip_id)
            worksheet = self._worksheet("Mileage")
            try:
                self._api(
                    lambda: worksheet.delete_rows(current.row_number),
                    retry_safe=False,
                )
                self._invalidate("Mileage")
                return
            except StorageUnavailableError as error:
                self._invalidate("Mileage")
                if not error.retryable:
                    raise
                try:
                    self._find_row("Mileage", trip_id)
                except StorageNotFoundError:
                    return
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))

    def import_csv_transactions(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        """Validate all CSV-style rows, then append them in one API request."""
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
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

    def preview_quickbooks_transactions(
        self, rows: Iterable[Mapping[str, Any]], *, auto_create: bool = False
    ) -> dict[str, Any]:
        """Validate and summarize a QuickBooks export without writing anything."""
        source_rows = list(rows)
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
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
        existing = {fingerprint(item) for item in self.list_transactions()}
        seen: set[str] = set()
        ready: list[dict[str, str]] = []
        duplicate_rows: list[int] = []
        for item in normalized:
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

    def import_quickbooks_transactions(
        self, rows: Iterable[Mapping[str, Any]], *, auto_create: bool = False
    ) -> list[dict[str, str]]:
        """Revalidate a QuickBooks export, then atomically batch append unique rows."""
        source_rows = list(rows)
        preview = self.preview_quickbooks_transactions(source_rows, auto_create=auto_create)
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
                }
                for name in preview["new_accounts"]
            ]
            category_records = [
                {"id": str(uuid4()), "name": name, "kind": kind}
                for name, kind in preview["new_categories"]
            ]
            self._append_many("Accounts", account_records)
            self._append_many("Categories", category_records)
            preview = self.preview_quickbooks_transactions(source_rows)
            if preview["errors"]:
                raise StorageValidationError("\n".join(preview["errors"]))
        accounts = self._account_lookup()
        categories = self._category_lookup()
        prepared = [
            self._prepare_transaction(
                item,
                accounts=accounts,
                categories=categories,
            )
            for item in preview["rows"]
        ]
        self._append_many("Transactions", prepared)
        return prepared

    def export_backup_zip(self) -> bytes:
        """Return a fresh, checksummed backup of every ledger worksheet."""
        generated_at = _utc_now()
        row_counts: dict[str, int] = {}
        worksheet_headers: dict[str, list[str]] = {}
        csv_files: dict[str, bytes] = {}
        archive_buffer = io.BytesIO()
        for title in WORKSHEET_HEADERS:
            headers = self._headers(title)
            rows = self._rows(title, force_refresh=True)
            row_counts[title] = len(rows)
            worksheet_headers[title] = headers
            csv_buffer = io.StringIO(newline="")
            writer = csv.writer(csv_buffer, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                writer.writerow([row.values.get(header, "") for header in headers])
            csv_files[f"{title}.csv"] = csv_buffer.getvalue().encode("utf-8")

        manifest = {
            "backup_time": generated_at,
            "format_version": BACKUP_FORMAT_VERSION,
            "row_counts": row_counts,
            "sha256": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in csv_files.items()
            },
            "workbook_title": self.workbook_title,
            "worksheet_headers": worksheet_headers,
        }
        with zipfile.ZipFile(
            archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, content in csv_files.items():
                archive.writestr(name, content)
            archive.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
            )
        return archive_buffer.getvalue()

    @staticmethod
    def validate_backup_zip(backup: bytes) -> dict[str, Any]:
        """Return a validated manifest or raise a safe validation error."""
        manifest, _ = _parse_backup_zip(backup)
        return manifest

    def restore_backup_zip(self, backup: bytes) -> dict[str, int]:
        """Restore a validated backup into a blank initialized workbook."""
        _, tables = _parse_backup_zip(backup)
        for title in WORKSHEET_HEADERS:
            target_headers = self._headers(title)
            if title in tables and set(target_headers) != set(tables[title][0]):
                raise StorageValidationError(
                    f"{title} target headers do not match the backup"
                )
            if self._rows(title, force_refresh=True):
                raise StorageConflictError(
                    "Restore target must have empty ledger worksheets"
                )

        counts: dict[str, int] = {}
        for title in WORKSHEET_HEADERS:
            if title not in tables:
                continue
            _, records = tables[title]
            self._append_many(title, records)
            restored = self._rows(title, force_refresh=True)
            expected_by_id = {record["id"]: record for record in records}
            actual_by_id = {row.values.get("id", ""): row.values for row in restored}
            headers = tables[title][0]
            if len(restored) != len(records) or any(
                [actual_by_id.get(record_id, {}).get(header, "") for header in headers]
                != [record.get(header, "") for header in headers]
                for record_id, record in expected_by_id.items()
            ):
                raise StorageUnavailableError(
                    "Restore verification failed; the target may contain partial data"
                )
            counts[title] = len(records)
        return counts
