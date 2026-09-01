"""Google Sheets persistence for Project Tabula Rasa.

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
import unicodedata
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, TypeVar
from uuid import NAMESPACE_URL, uuid4, uuid5

import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials

from tabula_rasa.hierarchy import (
    HierarchyValidationError,
    validate_two_level_hierarchy,
)
from tabula_rasa.quickbooks_import import (
    fingerprint,
    missing_references,
    normalize_rows,
    suggested_account_classification,
    suggested_account_type,
)
from tabula_rasa.quickbooks_mileage_import import (
    mileage_fingerprint,
    missing_required_columns as missing_quickbooks_mileage_columns,
    normalize_rows as normalize_quickbooks_mileage_rows,
)
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    decode_receipt_reference_list,
    validate_receipt_manifest,
    validate_receipt_reference,
)


PRE_PAYEE_WORKSHEET_HEADERS = {
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
        "receipt_references",
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
VERSION_5_WORKSHEET_HEADERS = PRE_PAYEE_WORKSHEET_HEADERS
VERSION_6_WORKSHEET_HEADERS = {
    **PRE_PAYEE_WORKSHEET_HEADERS,
    "Accounts": (*PRE_PAYEE_WORKSHEET_HEADERS["Accounts"], "parent_id"),
    "Categories": (*PRE_PAYEE_WORKSHEET_HEADERS["Categories"], "parent_id"),
}
WORKSHEET_HEADERS = {
    **VERSION_6_WORKSHEET_HEADERS,
    "Payees": ("id", "name", "active", "created_at"),
    "Transactions": tuple(
        "payee_id" if header == "payee" else header
        for header in VERSION_6_WORKSHEET_HEADERS["Transactions"]
    ),
}
VERSION_3_WORKSHEET_HEADERS = {
    title: (
        tuple(header for header in headers if header != "receipt_references")
        if title == "Transactions"
        else headers
    )
    for title, headers in PRE_PAYEE_WORKSHEET_HEADERS.items()
}
LEGACY_BACKUP_HEADERS = {
    title: headers
    for title, headers in VERSION_3_WORKSHEET_HEADERS.items()
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
LEDGER_ONLY_BACKUP_FORMAT_VERSION = 4
RECEIPT_INVENTORY_BACKUP_FORMAT_VERSION = 5
BACKUP_FORMAT_VERSION = 7
BACKUP_HEADERS_BY_VERSION = {
    2: LEGACY_BACKUP_HEADERS,
    3: VERSION_3_WORKSHEET_HEADERS,
    6: VERSION_6_WORKSHEET_HEADERS,
    LEDGER_ONLY_BACKUP_FORMAT_VERSION: PRE_PAYEE_WORKSHEET_HEADERS,
    RECEIPT_INVENTORY_BACKUP_FORMAT_VERSION: PRE_PAYEE_WORKSHEET_HEADERS,
    BACKUP_FORMAT_VERSION: VERSION_6_WORKSHEET_HEADERS,
}
BACKUP_HEADERS_BY_VERSION[BACKUP_FORMAT_VERSION] = WORKSHEET_HEADERS
SUPPORTED_BACKUP_FORMAT_VERSIONS = set(BACKUP_HEADERS_BY_VERSION)
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
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


class StorageBulkMutationUncertainError(StorageUnavailableError):
    """Raised when a bulk write's postcondition is not safely complete."""

    def __init__(self, message: str, *, outcome: str, retryable: bool):
        super().__init__(message, retryable=retryable)
        self.outcome = outcome


class StorageAuthenticationError(StorageUnavailableError):
    """Raised when Google rejects a service-account credential."""


class StorageWorkbookAccessError(StorageUnavailableError):
    """Raised when the configured spreadsheet cannot be opened."""


class StorageInitializationError(StorageUnavailableError):
    """Raised when an accessible workbook cannot be initialized."""


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


def normalize_payee_name(value: Any) -> str:
    """Normalize payee names for deduplication and reference resolution."""
    return " ".join(
        unicodedata.normalize("NFKC", _clean_text(value, "Payee")).split()
    ).casefold()


def _legacy_payee_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"tabula-rasa:payee:{normalize_payee_name(name)}"))


def _validate_hierarchy_records(
    records: Iterable[Mapping[str, Any]],
    *,
    compatibility_field: str,
    item_label: str,
) -> None:
    try:
        validate_two_level_hierarchy(
            records,
            compatibility_field=compatibility_field,
            item_label=item_label,
        )
    except HierarchyValidationError as exc:
        raise StorageValidationError(str(exc)) from exc


def decode_receipt_references(value: Any) -> list[dict[str, Any]]:
    """Return validated Drive receipt references from one transaction cell."""
    try:
        return decode_receipt_reference_list(value)
    except ReceiptManifestError as exc:
        message = (
            "Transaction receipt references are unreadable"
            if "unreadable" in str(exc).casefold()
            else "Transaction receipt references are invalid"
        )
        raise StorageValidationError(message) from exc


def _encode_receipt_references(value: Any) -> str:
    references = decode_receipt_references(value)
    return json.dumps(references, separators=(",", ":"), ensure_ascii=False)


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
) -> tuple[
    dict[str, Any],
    dict[str, tuple[list[str], list[dict[str, str]]]],
    dict[str, Any] | None,
]:
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
            if not isinstance(manifest, dict):
                raise StorageValidationError("Backup manifest fields are invalid")
            format_version = manifest.get("format_version")
            if format_version not in SUPPORTED_BACKUP_FORMAT_VERSIONS:
                raise StorageValidationError("Backup format version is unsupported")
            backup_headers = BACKUP_HEADERS_BY_VERSION[format_version]
            required_files = {
                f"{title}.csv" for title in backup_headers
            } | {"manifest.json"}
            if format_version >= RECEIPT_INVENTORY_BACKUP_FORMAT_VERSION:
                required_files.add("receipts.json")
            optional_legacy_payees = format_version < BACKUP_FORMAT_VERSION and "Payees.csv" in names
            if set(names) not in (required_files, required_files | {"Payees.csv"}) or (
                optional_legacy_payees and "Payees.csv" not in names
            ):
                raise StorageValidationError(
                    "Backup must contain exactly the expected ledger and manifest files"
                )
            csv_files = {
                title: archive.read(f"{title}.csv") for title in backup_headers
            }
            if optional_legacy_payees:
                csv_files["Payees"] = archive.read("Payees.csv")
            receipt_manifest_bytes = (
                archive.read("receipts.json")
                if format_version >= RECEIPT_INVENTORY_BACKUP_FORMAT_VERSION
                else None
            )
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise StorageValidationError("Backup is not a readable ZIP archive") from exc

    row_counts = manifest.get("row_counts")
    file_hashes = manifest.get("sha256")
    worksheet_headers = manifest.get("worksheet_headers")
    if not all(isinstance(value, dict) for value in (row_counts, file_hashes, worksheet_headers)):
        raise StorageValidationError("Backup manifest is missing validation metadata")
    expected_hash_names = {f"{title}.csv" for title in backup_headers}
    if "Payees" in csv_files and "Payees.csv" not in expected_hash_names:
        expected_hash_names.add("Payees.csv")
    if format_version >= RECEIPT_INVENTORY_BACKUP_FORMAT_VERSION:
        expected_hash_names.add("receipts.json")
    if set(file_hashes) != expected_hash_names:
        raise StorageValidationError("Backup manifest checksum entries are invalid")

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
        required_headers = set(
            backup_headers.get(title, WORKSHEET_HEADERS[title])
        )
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

    if "Payees" not in tables:
        tables["Payees"] = (list(WORKSHEET_HEADERS["Payees"]), [])

    if format_version < LEDGER_ONLY_BACKUP_FORMAT_VERSION:
        transaction_headers, transactions = tables["Transactions"]
        if "receipt_references" not in transaction_headers:
            migrated_headers = [
                *transaction_headers,
                "receipt_references",
            ]
            migrated_transactions = [
                {**transaction, "receipt_references": ""}
                for transaction in transactions
            ]
            tables["Transactions"] = (
                migrated_headers,
                migrated_transactions,
            )

    if format_version < BACKUP_FORMAT_VERSION:
        for title in ("Accounts", "Categories"):
            legacy_headers, legacy_records = tables[title]
            if "parent_id" not in legacy_headers:
                legacy_headers = [*legacy_headers, "parent_id"]
                legacy_records = [
                    {**record, "parent_id": ""} for record in legacy_records
                ]
            tables[title] = (legacy_headers, legacy_records)

        # Formats through version 6 stored arbitrary payee text on each
        # transaction. Resolve that legacy text once while loading the backup;
        # unmatched text is intentionally discarded.
        for transaction in tables["Transactions"][1]:
            legacy_name = _clean_text(transaction.get("payee"), "Payee")
            transaction["legacy_payee"] = legacy_name
            transaction["payee_id"] = ""
            transaction.pop("payee", None)
        tables["Transactions"] = (
            list(WORKSHEET_HEADERS["Transactions"]),
            tables["Transactions"][1],
        )
        tables["Payees"] = (
            list(WORKSHEET_HEADERS["Payees"]),
            [],
        )

    _validate_hierarchy_records(
        tables["Accounts"][1],
        compatibility_field="classification",
        item_label="Account",
    )
    _validate_hierarchy_records(
        tables["Categories"][1],
        compatibility_field="kind",
        item_label="Category",
    )

    account_ids = {record["id"] for record in tables["Accounts"][1]}
    category_ids = {record["id"] for record in tables["Categories"][1]}
    payee_ids = {record["id"] for record in tables["Payees"][1]}
    for transaction in tables["Transactions"][1]:
        if transaction.get("account_id") not in account_ids:
            raise StorageValidationError("Backup contains an unknown transaction account")
        to_account_id = transaction.get("to_account_id", "")
        if to_account_id and to_account_id not in account_ids:
            raise StorageValidationError("Backup contains an unknown transfer account")
        category_id = transaction.get("category_id", "")
        if category_id and category_id not in category_ids:
            raise StorageValidationError("Backup contains an unknown transaction category")
        payee_id = transaction.get("payee_id", "")
        if payee_id and payee_id not in payee_ids:
            raise StorageValidationError("Backup contains an unknown transaction payee")
        decode_receipt_references(
            transaction.get("receipt_references", "")
        )

    receipt_manifest: dict[str, Any] | None = None
    if receipt_manifest_bytes is not None:
        if (
            hashlib.sha256(receipt_manifest_bytes).hexdigest()
            != file_hashes.get("receipts.json")
        ):
            raise StorageValidationError("Receipt manifest checksum does not match")
        try:
            raw_receipt_manifest = json.loads(receipt_manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StorageValidationError(
                "Receipt manifest is not valid UTF-8 JSON"
            ) from exc
        try:
            receipt_manifest = validate_receipt_manifest(
                raw_receipt_manifest,
                transaction_ids={
                    transaction["id"] for transaction in tables["Transactions"][1]
                },
            )
        except ReceiptManifestError as exc:
            raise StorageValidationError(str(exc)) from exc
        referenced_entries = {
            (str(entry["transaction_id"]), str(entry["old_drive_file_id"])): entry
            for entry in receipt_manifest["receipts"]
            if entry["reference_state"] == "referenced"
        }
        expected_references: set[tuple[str, str]] = set()
        for transaction in tables["Transactions"][1]:
            for reference in decode_receipt_references(
                transaction.get("receipt_references", "")
            ):
                if "receipt_id" not in reference:
                    raise StorageValidationError(
                        "Receipt references need integrity metadata before backup"
                    )
                key = (transaction["id"], str(reference["id"]))
                entry = referenced_entries.get(key)
                if entry is None or any(
                    (
                        reference[reference_field]
                        != entry[entry_field]
                    )
                    for reference_field, entry_field in (
                        ("name", "stored_filename"),
                        ("receipt_id", "receipt_id"),
                        ("original_filename", "original_filename"),
                        ("mime_type", "mime_type"),
                        ("byte_size", "byte_size"),
                        ("sha256", "sha256"),
                    )
                ):
                    raise StorageValidationError(
                        "Receipt manifest does not match transaction references"
                    )
                expected_references.add(key)
        if expected_references != set(referenced_entries):
            raise StorageValidationError(
                "Receipt manifest has an invalid transaction association"
            )
    return manifest, tables, receipt_manifest


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
        _allow_legacy_hierarchy_headers: bool = False,
        _initial_worksheets: Mapping[str, Any] | None = None,
        _initial_values: Mapping[str, list[list[Any]]] | None = None,
    ):
        self._workbook = workbook
        self._cache_ttl_seconds = cache_ttl_seconds
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleeper = sleeper
        self._allow_legacy_hierarchy_headers = (
            _allow_legacy_hierarchy_headers
        )
        self._worksheet_cache = dict(_initial_worksheets or {})
        self._header_cache: dict[str, list[str]] = {}
        self._row_cache: dict[str, tuple[float, list[_StoredRow]]] = {}
        self._cache_lock = threading.RLock()
        if _initial_values is None:
            self.validate_headers()
        else:
            missing = sorted(set(WORKSHEET_HEADERS) - set(_initial_values))
            if missing:
                raise StorageValidationError(
                    "Workbook is missing worksheets: " + ", ".join(missing)
                )
            for title in WORKSHEET_HEADERS:
                self._cache_values(title, _initial_values[title])

    @staticmethod
    def _open_workbook_from_secrets(
        secrets: Mapping[str, Any],
        *,
        scopes: Sequence[str],
    ) -> Any:
        """Open a configured workbook without changing its contents."""
        try:
            credential_info = dict(secrets["gcp_service_account"])
            spreadsheet_id = str(secrets["spreadsheet_id"]).strip()
            if not spreadsheet_id:
                raise ValueError("spreadsheet_id is empty")
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageAuthenticationError(
                "Profile Google settings are incomplete or malformed"
            ) from exc

        try:
            credentials = Credentials.from_service_account_info(
                credential_info, scopes=list(scopes)
            )
            client = gspread.authorize(credentials)
        except (
            TypeError,
            ValueError,
            GoogleAuthError,
            gspread.GSpreadException,
            OSError,
        ) as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc

        try:
            workbook = client.open_by_key(spreadsheet_id)
        except GoogleAuthError as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc
        except (
            gspread.SpreadsheetNotFound,
            PermissionError,
        ) as exc:
            raise StorageWorkbookAccessError(
                "The spreadsheet could not be opened with this service account"
            ) from exc
        except (gspread.GSpreadException, OSError) as exc:
            raise StorageWorkbookAccessError(
                "Google Sheets could not open the configured spreadsheet"
            ) from exc

        return workbook

    @classmethod
    def from_secrets_read_only(
        cls,
        secrets: Mapping[str, Any],
    ) -> "GoogleSheetsStorage":
        """Create storage using only read access to the configured workbook."""
        workbook = cls._open_workbook_from_secrets(
            secrets,
            scopes=[SHEETS_READONLY_SCOPE],
        )
        try:
            return cls(workbook)
        except StorageValidationError:
            raise
        except StorageUnavailableError as exc:
            raise StorageInitializationError(
                "The workbook opened, but worksheet validation could not finish"
            ) from exc

    @classmethod
    def from_secrets(cls, secrets: Mapping[str, Any]) -> "GoogleSheetsStorage":
        """Create and initialize storage from Streamlit-compatible secrets."""
        workbook = cls._open_workbook_from_secrets(
            secrets,
            scopes=[SHEETS_SCOPE],
        )

        try:
            actual_worksheets = {
                worksheet.title: worksheet for worksheet in workbook.worksheets()
            }
            initial_values: dict[str, list[list[Any]]] = {}
            for title, headers in WORKSHEET_HEADERS.items():
                worksheet = actual_worksheets.get(title)
                if worksheet is None:
                    worksheet = workbook.add_worksheet(
                        title=title, rows=1000, cols=len(headers)
                    )
                    worksheet.update(
                        [list(headers)], range_name="A1", raw=True
                    )
                    actual_worksheets[title] = worksheet
                    values: list[list[Any]] = [list(headers)]
                else:
                    values = worksheet.get_all_values()
                if title in {"Accounts", "Categories"} and values:
                    existing_headers = [
                        str(value).strip() for value in values[0]
                    ]
                    legacy_headers = set(
                        VERSION_5_WORKSHEET_HEADERS[title]
                    )
                    if (
                        "parent_id" not in existing_headers
                        and legacy_headers.issubset(existing_headers)
                        and len(existing_headers) == len(set(existing_headers))
                    ):
                        worksheet.add_cols(1)
                        migrated_headers = [*existing_headers, "parent_id"]
                        worksheet.update(
                            [migrated_headers],
                            range_name="A1",
                            raw=True,
                        )
                        values[0] = migrated_headers
                if title == "Transactions" and values:
                    existing_headers = [
                        str(value).strip() for value in values[0]
                    ]
                    transaction_headers_without_receipts = set(
                        WORKSHEET_HEADERS["Transactions"]
                    ) - {"receipt_references"}
                    if (
                        "receipt_references" not in existing_headers
                        and transaction_headers_without_receipts.issubset(
                            existing_headers
                        )
                        and len(existing_headers)
                        == len(set(existing_headers))
                    ):
                        worksheet.add_cols(1)
                        migrated_headers = [
                            *existing_headers,
                            "receipt_references",
                        ]
                        worksheet.update(
                            [migrated_headers],
                            range_name="A1",
                            raw=True,
                        )
                        values[0] = migrated_headers
                if not any(str(value).strip() for row in values for value in row):
                    worksheet.update(
                        [list(headers)], range_name="A1", raw=True
                    )
                    values = [list(headers)]
                initial_values[title] = values
        except (
            GoogleAuthError,
        ) as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc
        except (
            PermissionError,
            gspread.GSpreadException,
            OSError,
        ) as exc:
            raise StorageInitializationError(
                "The workbook opened, but worksheet initialization failed"
            ) from exc
        try:
            return cls(
                workbook,
                _initial_worksheets=actual_worksheets,
                _initial_values=initial_values,
            )
        except StorageValidationError:
            raise
        except StorageUnavailableError as exc:
            raise StorageInitializationError(
                "The workbook opened, but worksheet validation could not finish"
            ) from exc

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
        with self._cache_lock:
            worksheet = self._worksheet_cache.get(title)
        if worksheet is not None:
            return worksheet
        worksheet = self._api(lambda: self._workbook.worksheet(title))
        with self._cache_lock:
            self._worksheet_cache[title] = worksheet
        return worksheet

    def _headers(self, title: str) -> list[str]:
        with self._cache_lock:
            cached = self._header_cache.get(title)
        if cached is not None:
            return list(cached)
        headers = [
            str(value).strip()
            for value in self._api(lambda: self._worksheet(title).row_values(1))
        ]
        self._validate_header_values(title, headers)
        with self._cache_lock:
            self._header_cache[title] = headers
        return list(headers)

    def _validate_header_values(self, title: str, headers: list[str]) -> None:
        required = set(WORKSHEET_HEADERS[title])
        if (
            self._allow_legacy_hierarchy_headers
            and title in {"Accounts", "Categories"}
        ):
            required.discard("parent_id")
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
            worksheets = {
                worksheet.title: worksheet
                for worksheet in self._api(self._workbook.worksheets)
            }
        except AttributeError as exc:
            raise StorageValidationError("Invalid workbook object") from exc
        missing = sorted(set(WORKSHEET_HEADERS) - set(worksheets))
        if missing:
            raise StorageValidationError(
                "Workbook is missing worksheets: " + ", ".join(missing)
            )
        with self._cache_lock:
            self._worksheet_cache.update(worksheets)
        for title in WORKSHEET_HEADERS:
            self._headers(title)

    def ensure_defaults(self) -> dict[str, int]:
        """Seed default accounts/categories once for a blank workbook."""
        self._snapshot(["Accounts", "Categories"], force_refresh=True)
        existing_accounts = self.list_accounts(active_only=False)
        existing_categories = self.list_categories()
        if existing_accounts or existing_categories:
            _validate_hierarchy_records(
                existing_accounts,
                compatibility_field="classification",
                item_label="Account",
            )
            _validate_hierarchy_records(
                existing_categories,
                compatibility_field="kind",
                item_label="Category",
            )
            return {"accounts": 0, "categories": 0}

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
                "parent_id": "",
            }
            for name, account_type in DEFAULT_ACCOUNTS
            if name.casefold() not in account_names
        ]

        category_keys = {
            (category["name"].casefold(), category["kind"])
            for category in existing_categories
        }
        new_categories = [
            {"id": str(uuid4()), "name": name, "kind": kind, "parent_id": ""}
            for kind, names in DEFAULT_CATEGORIES.items()
            for name in names
            if (name.casefold(), kind) not in category_keys
        ]

        _validate_hierarchy_records(
            [*existing_accounts, *new_accounts],
            compatibility_field="classification",
            item_label="Account",
        )
        _validate_hierarchy_records(
            [*existing_categories, *new_categories],
            compatibility_field="kind",
            item_label="Category",
        )
        self._append_many("Accounts", new_accounts)
        self._append_many("Categories", new_categories)
        return {"accounts": len(new_accounts), "categories": len(new_categories)}

    def _cache_values(
        self,
        title: str,
        values: list[list[Any]],
    ) -> list[_StoredRow]:
        """Validate one worksheet response and populate its local caches."""
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
            self._header_cache[title] = headers
            self._row_cache[title] = (time.monotonic(), rows)
        return list(rows)

    def _refresh_rows(self, titles: list[str]) -> None:
        """Refresh multiple worksheets with one values batch request when available."""
        if not titles:
            return
        batch_get = getattr(self._workbook, "values_batch_get", None)
        if callable(batch_get) and len(titles) > 1:
            ranges = ["'{}'".format(title.replace("'", "''")) for title in titles]
            response = self._api(lambda: batch_get(ranges))
            value_ranges = response.get("valueRanges", [])
            if not isinstance(value_ranges, list) or len(value_ranges) != len(titles):
                raise StorageValidationError(
                    "Google Sheets returned an incomplete workbook snapshot"
                )
            for title, value_range in zip(titles, value_ranges):
                if not isinstance(value_range, Mapping):
                    raise StorageValidationError(
                        "Google Sheets returned an unreadable workbook snapshot"
                    )
                values = value_range.get("values", [])
                if not isinstance(values, list):
                    raise StorageValidationError(
                        "Google Sheets returned an unreadable worksheet"
                    )
                self._cache_values(title, values)
            return
        for title in titles:
            worksheet = self._worksheet(title)
            values = self._api(worksheet.get_all_values)
            self._cache_values(title, values)

    def _snapshot(
        self,
        titles: Iterable[str],
        *,
        force_refresh: bool = False,
    ) -> dict[str, list[_StoredRow]]:
        """Return a consistent cached or freshly batched worksheet snapshot."""
        requested = list(dict.fromkeys(titles))
        now = time.monotonic()
        refresh: list[str] = []
        with self._cache_lock:
            for title in requested:
                cached = self._row_cache.get(title)
                if (
                    force_refresh
                    or self._cache_ttl_seconds <= 0
                    or cached is None
                    or now - cached[0] >= self._cache_ttl_seconds
                ):
                    refresh.append(title)
        if refresh:
            self._refresh_rows(refresh)
        snapshot: dict[str, list[_StoredRow]] = {}
        with self._cache_lock:
            for title in requested:
                cached = self._row_cache.get(title)
                if cached is None:
                    raise StorageValidationError(
                        f"{title} could not be loaded from Google Sheets"
                    )
                snapshot[title] = list(cached[1])
        return snapshot

    def _rows(self, title: str, *, force_refresh: bool = False) -> list[_StoredRow]:
        return self._snapshot([title], force_refresh=force_refresh)[title]

    def prefetch_worksheets(
        self,
        *titles: str,
        force_refresh: bool = False,
    ) -> None:
        """Warm several worksheet caches through one multi-range values request."""
        unknown = sorted(set(titles) - set(WORKSHEET_HEADERS))
        if unknown:
            raise StorageValidationError(
                "Unknown worksheets requested: " + ", ".join(unknown)
            )
        self._snapshot(titles, force_refresh=force_refresh)

    def _invalidate(self, title: str) -> None:
        with self._cache_lock:
            self._row_cache.pop(title, None)

    def _find_row(self, title: str, record_id: str) -> _StoredRow:
        record_id = _clean_text(record_id, "ID", required=True)
        matches = [
            row
            for row in self._rows(title, force_refresh=True)
            if _clean_text(row.values.get("id"), "ID") == record_id
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
                if not error.retryable:
                    raise
                try:
                    if record_id and any(
                        _clean_text(row.values.get("id"), "ID") == record_id
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

    @staticmethod
    def _sheet_column_index(headers: Sequence[str], column: str) -> int:
        try:
            return list(headers).index(column)
        except ValueError as exc:
            raise StorageValidationError(
                f"Transactions is missing the {column} header"
            ) from exc

    def _transactions_sheet_id(self) -> int:
        sheet_id = getattr(self._worksheet("Transactions"), "id", None)
        if sheet_id is None:
            raise StorageValidationError("Transactions worksheet has no stable sheet ID")
        try:
            return int(sheet_id)
        except (TypeError, ValueError) as exc:
            raise StorageValidationError(
                f"Transactions worksheet has an invalid sheet ID: {sheet_id}"
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
            expected = {
                str(key): (str(value) if value is not None else "")
                for key, value in expected_by_id[transaction_id].items()
                if str(key) in self._headers("Transactions")
            }
            current = dict(row.values)
            if {key: current.get(key, "") for key in expected} != expected:
                raise StorageConflictError(
                    "A selected transaction changed; review the current rows and try again."
                )
            selected_rows[transaction_id] = row
            current_by_id_values[transaction_id] = current
        return selected_rows, current_by_id_values

    def _bulk_postcondition_error(
        self,
        *,
        operation: str,
        error: StorageUnavailableError,
        expected_by_id: Mapping[str, Mapping[str, str]],
        postcondition: Callable[[Mapping[str, Mapping[str, str]]], bool],
        fully_applied: Callable[[Mapping[str, Mapping[str, str]]], bool],
    ) -> dict[str, str] | None:
        if not error.retryable:
            raise StorageBulkMutationUncertainError(
                f"The {operation} batch was rejected. Do not retry until the underlying "
                "error is corrected.",
                outcome="not_applied",
                retryable=False,
            ) from error
        try:
            current_rows = self._rows("Transactions", force_refresh=True)
        except StorageUnavailableError as read_error:
            self._invalidate("Transactions")
            raise StorageBulkMutationUncertainError(
                f"The {operation} batch completed but its postcondition could not be "
                "read. Review the selected rows before retrying.",
                outcome="mixed_ambiguous",
                retryable=False,
            ) from read_error
        current_by_id = {
            str(row.values["id"]): dict(row.values) for row in current_rows
        }
        if fully_applied(current_by_id):
            self._invalidate("Transactions")
            return {"status": "fully_applied", "count": str(len(expected_by_id))}
        if postcondition(current_by_id):
            raise StorageBulkMutationUncertainError(
                f"The {operation} batch was not applied. Review the current ledger before retrying.",
                outcome="not_applied",
                retryable=True,
            ) from error
        raise StorageBulkMutationUncertainError(
            f"The {operation} batch outcome is ambiguous. Do not retry until the selected rows are reviewed.",
            outcome="mixed_ambiguous",
            retryable=False,
        ) from error

    def _verify_bulk_success(
        self,
        *,
        operation: str,
        postcondition: Callable[[Mapping[str, Mapping[str, str]]], bool],
    ) -> None:
        try:
            current_rows = self._rows("Transactions", force_refresh=True)
        except StorageUnavailableError as read_error:
            self._invalidate("Transactions")
            raise StorageBulkMutationUncertainError(
                f"The {operation} batch completed but its postcondition could not be "
                "read. Review the selected rows before retrying.",
                outcome="mixed_ambiguous",
                retryable=False,
            ) from read_error
        current_by_id = {
            str(row.values["id"]): dict(row.values) for row in current_rows
        }
        if postcondition(current_by_id):
            return
        raise StorageBulkMutationUncertainError(
            f"The {operation} batch completed but its postcondition is ambiguous. "
            "Review the selected rows before retrying.",
            outcome="mixed_ambiguous",
            retryable=False,
        )

    def _batch_update_spreadsheet(self, requests: Sequence[Mapping[str, Any]]) -> None:
        if not requests:
            return
        self._api(
            lambda: self._workbook.batch_update({"requests": list(requests)}),
            retry_safe=False,
        )

    def bulk_change_transaction_category(
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
        try:
            self._batch_update_spreadsheet(requests)
        except StorageUnavailableError as error:
            outcome = self._bulk_postcondition_error(
                operation="category change",
                error=error,
                expected_by_id=pending_by_id,
                postcondition=lambda current: all(
                    item in current and current[item] == pending_by_id[item]
                    for item in pending_by_id
                ),
                fully_applied=lambda current: all(
                    item in current
                    and current[item].get("category_id") == category_id
                    for item in pending_by_id
                ),
            )
            if outcome is not None:
                return outcome
            raise AssertionError("Bulk category postcondition did not classify")
        self._verify_bulk_success(
            operation="category change",
            postcondition=lambda current: all(
                item in current
                and current[item].get("category_id") == category_id
                for item in pending_by_id
            ),
        )
        return {"status": "fully_applied", "count": str(len(pending_by_id))}

    def bulk_delete_transactions(
        self,
        transaction_ids: Sequence[str],
        *,
        expected_transactions: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        """Revalidate and delete transactions with one atomic row-index batch."""
        selected_rows, current_by_id = self._fresh_bulk_transaction_snapshot(
            transaction_ids, expected_transactions
        )
        sheet_id = self._transactions_sheet_id()
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
        try:
            self._batch_update_spreadsheet(requests)
        except StorageUnavailableError as error:
            outcome = self._bulk_postcondition_error(
                operation="transaction deletion",
                error=error,
                expected_by_id=current_by_id,
                postcondition=lambda current: all(
                    item in current and current[item] == current_by_id[item]
                    for item in current_by_id
                ),
                fully_applied=lambda current: not any(
                    item in current for item in current_by_id
                ),
            )
            if outcome is not None:
                return outcome
            raise AssertionError("Bulk deletion postcondition did not classify")
        self._verify_bulk_success(
            operation="transaction deletion",
            postcondition=lambda current: not any(
                item in current for item in current_by_id
            ),
        )
        return {"status": "fully_applied", "count": str(len(selected_rows))}

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
            record["parent_id"] = _clean_text(
                record.get("parent_id"), "Account parent"
            )
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
        existing_accounts = self.list_accounts(
            active_only=False, _force_refresh=True
        )
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

    def edit_account(self, account_id: str, **changes: Any) -> dict[str, Any]:
        current = self._find_row("Accounts", account_id)
        updated = dict(current.values)
        existing_accounts = self.list_accounts(active_only=False)
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
            category["id"] = _clean_text(
                category.get("id"), "ID", required=True
            )
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
                raise StorageValidationError(
                    "Category kind must be Income or Expense"
                )
            category["kind"] = category_kind
        if kind is not None:
            categories = [item for item in categories if item["kind"] == kind]
        return sorted(categories, key=lambda item: (item["kind"], item["name"].casefold()))

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
            category["name"].casefold() == name.casefold()
            and category["kind"] == kind
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

    def edit_category(self, category_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Categories", category_id)
        updated = dict(current.values)
        existing_categories = self.list_categories()
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
                updated if category["id"] == category_id else category
                for category in existing_categories
            ],
            compatibility_field="kind",
            item_label="Category",
        )
        self._replace_row("Categories", current, updated)
        return updated

    def delete_category(self, category_id: str) -> None:
        category_id = _clean_text(category_id, "ID", required=True)
        current = self._find_row("Categories", category_id)
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
        for attempt in range(self._retry_attempts):
            current = self._find_row("Categories", category_id)
            worksheet = self._worksheet("Categories")
            try:
                self._api(
                    lambda: worksheet.delete_rows(current.row_number),
                    retry_safe=False,
                )
                self._invalidate("Categories")
                return
            except StorageUnavailableError as error:
                self._invalidate("Categories")
                if not error.retryable:
                    raise
                try:
                    self._find_row("Categories", category_id)
                except StorageNotFoundError:
                    return
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))

    def list_payees(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        payees: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Payees", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Payee ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Payee name", required=True)
            item["active"] = "TRUE" if _as_bool(item.get("active"), "Payee active") else "FALSE"
            item["created_at"] = _clean_text(item.get("created_at"), "Payee created at")
            key = normalize_payee_name(item["name"])
            if item["id"] in seen_ids or key in seen_names:
                raise StorageValidationError("Payee IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(key)
            if not active_only or item["active"] == "TRUE":
                payees.append(item)
        return sorted(payees, key=lambda item: item["name"].casefold())

    def create_payee(self, name: str, *, active: bool = True) -> dict[str, str]:
        name = _clean_text(name, "Payee name", required=True)
        existing = self.list_payees(_force_refresh=True)
        key = normalize_payee_name(name)
        match = next((item for item in existing if normalize_payee_name(item["name"]) == key), None)
        if match is not None:
            if active and match["active"] != "TRUE":
                return self.edit_payee(match["id"], active=True)
            return match
        record = {
            "id": str(uuid4()),
            "name": name,
            "active": "TRUE" if active else "FALSE",
            "created_at": _utc_now(),
        }
        self._append("Payees", record)
        return record

    def edit_payee(self, payee_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Payees", payee_id)
        updated = dict(current.values)
        name = _clean_text(changes.get("name", updated["name"]), "Payee name", required=True)
        existing = self.list_payees(_force_refresh=True)
        if any(item["id"] != payee_id and normalize_payee_name(item["name"]) == normalize_payee_name(name) for item in existing):
            raise StorageConflictError("That payee already exists")
        updated.update({"name": name, "active": "TRUE" if _as_bool(changes.get("active", updated["active"]), "Payee active") else "FALSE"})
        self._replace_row("Payees", current, updated)
        return updated

    def _payee_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_payees(_force_refresh=force_refresh)}

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
        if accounts is None and categories is None:
            self._snapshot(["Accounts", "Categories", "Payees"], force_refresh=True)
            accounts = self._account_lookup()
            categories = self._category_lookup()
            payees = self._payee_lookup()
        else:
            accounts = accounts or self._account_lookup(force_refresh=True)
            categories = categories or self._category_lookup(force_refresh=True)
            payees = self._payee_lookup(force_refresh=True)
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
        if not payee_id and new_payee_name:
            payee_id = self.create_payee(new_payee_name)["id"]
            payees = self._payee_lookup(force_refresh=True)
        if payee_id and payee_id not in payees:
            raise StorageValidationError("Payee does not exist")
        if payee_id and not _as_bool(payees[payee_id]["active"], "Payee active"):
            raise StorageValidationError("Payee is inactive")
        return {
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
            "created_at": created_at or _utc_now(),
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
        payees = self._payee_lookup(force_refresh=_force_refresh)
        for row in self._rows("Transactions", force_refresh=_force_refresh):
            item = dict(row.values)
            item["txn_date"] = _iso_date(item.get("txn_date"))
            item["account_id"] = _clean_text(
                item.get("account_id"), "Account", required=True
            )
            item["to_account_id"] = _clean_text(
                item.get("to_account_id"), "Destination account"
            )
            item["category_id"] = _clean_text(item.get("category_id"), "Category")
            item["payee_id"] = _clean_text(item.get("payee_id"), "Payee")
            item["payee"] = payees.get(item["payee_id"], {}).get("name", "")
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

    def set_transaction_receipt_references(
        self,
        transaction_id: str,
        references: Any,
    ) -> dict[str, str]:
        """Replace the Drive receipt references attached to one transaction."""
        current = self._find_row("Transactions", transaction_id)
        updated = dict(current.values)
        updated["receipt_references"] = _encode_receipt_references(
            references
        )
        self._replace_row("Transactions", current, updated)
        return updated

    def initialize_legacy_transaction_receipts(
        self,
        transaction_id: str,
        *,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        """Populate one still-blank legacy receipt cell with rich references."""
        try:
            normalized = [
                validate_receipt_reference(reference, allow_legacy=False)
                for reference in references
            ]
        except ReceiptManifestError as exc:
            raise StorageValidationError(str(exc)) from exc
        if not normalized:
            raise StorageValidationError(
                "Legacy receipt initialization requires at least one receipt"
            )
        file_ids = [str(reference["id"]) for reference in normalized]
        if len(file_ids) != len(set(file_ids)):
            raise StorageValidationError("Receipt references are duplicated")
        transactions = self.list_transactions(_force_refresh=True)
        for transaction in transactions:
            if transaction["id"] == transaction_id:
                continue
            linked_ids = {
                str(item["id"])
                for item in decode_receipt_references(
                    transaction.get("receipt_references", "")
                )
            }
            if linked_ids.intersection(file_ids):
                raise StorageConflictError(
                    "That receipt is already linked to another transaction"
                )
        current = self._find_row("Transactions", transaction_id)
        if str(current.values.get("receipt_references", "")) != "":
            raise StorageConflictError(
                "The transaction receipt references are already initialized"
            )
        updated = dict(current.values)
        updated["receipt_references"] = _encode_receipt_references(normalized)
        self._replace_row("Transactions", current, updated)
        return updated

    def link_transaction_receipt(
        self,
        transaction_id: str,
        *,
        file_id: str = "",
        name: str = "",
        reference: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Attach or refresh one Drive file reference on a transaction."""
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
        current = self._find_row("Transactions", transaction_id)
        references = decode_receipt_references(
            current.values.get("receipt_references", "")
        )
        references = [
            item
            for item in references
            if item["id"] != normalized_reference["id"]
        ]
        references.append(normalized_reference)
        updated = dict(current.values)
        updated["receipt_references"] = _encode_receipt_references(
            references
        )
        self._replace_row("Transactions", current, updated)
        return updated

    def remap_transaction_receipt(
        self,
        transaction_id: str,
        *,
        old_file_id: str,
        reference: Mapping[str, Any],
    ) -> dict[str, str]:
        """Replace one recovered old Drive ID with a verified new reference."""
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
        current = self._find_row("Transactions", transaction_id)
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
        updated = dict(current.values)
        updated["receipt_references"] = _encode_receipt_references(retained)
        self._replace_row("Transactions", current, updated)
        return updated

    def apply_receipt_recovery_plan(
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
        if expected_receipts != current_receipts:
            return False, current_transactions

        rows_by_id = {
            str(row.values["id"]): row for row in current_rows
        }
        unknown = sorted(set(updates) - set(rows_by_id))
        if unknown:
            raise StorageNotFoundError(
                "A transaction disappeared during receipt recovery."
            )
        if not updates:
            return True, current_transactions

        headers = self._headers("Transactions")
        reference_column = headers.index("receipt_references") + 1
        column_name = ""
        while reference_column:
            reference_column, remainder = divmod(reference_column - 1, 26)
            column_name = chr(65 + remainder) + column_name
        intended_values = {
            str(transaction_id): _encode_receipt_references(references)
            for transaction_id, references in updates.items()
        }
        batch = [
            {
                "range": f"{column_name}{rows_by_id[transaction_id].row_number}",
                "values": [[value]],
            }
            for transaction_id, value in intended_values.items()
        ]
        worksheet = self._worksheet("Transactions")
        try:
            self._api(
                lambda: worksheet.batch_update(batch, raw=True),
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
            ):
                return True, confirmed_transactions
            if error.retryable:
                return False, confirmed_transactions
            raise
        self._invalidate("Transactions")
        return True, current_transactions

    def unlink_transaction_receipt(
        self,
        transaction_id: str,
        *,
        file_id: str,
    ) -> dict[str, str]:
        """Remove one Drive reference without modifying the Drive file."""
        current = self._find_row("Transactions", transaction_id)
        references = decode_receipt_references(
            current.values.get("receipt_references", "")
        )
        retained = [
            item for item in references if item["id"] != str(file_id)
        ]
        if retained == references:
            return dict(current.values)
        updated = dict(current.values)
        updated["receipt_references"] = _encode_receipt_references(retained)
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
        _force_refresh: bool = False,
    ) -> list[dict[str, str]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        trips = []
        for row in self._rows("Mileage", force_refresh=_force_refresh):
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

    def create_mileage_round_trip(
        self,
        *,
        return_miles: Any | None = None,
        **data: Any,
    ) -> list[dict[str, str]]:
        """Create outbound and reversed return entries in one batch write.

        ``return_miles`` is optional for compatibility with callers that use
        one distance for both legs.  When supplied, it is validated and used
        only for the reversed return entry.
        """
        created_at = _utc_now()
        outbound = self._prepare_mileage_trip(data, created_at=created_at)
        return_data = dict(data)
        return_data.update(
            {
                "start_location": data.get("destination"),
                "destination": data.get("start_location"),
            }
        )
        if return_miles is not None:
            return_data["miles"] = return_miles
        return_trip = self._prepare_mileage_trip(
            return_data,
            created_at=created_at,
        )
        records = [outbound, return_trip]
        self._append_many("Mileage", records)
        return records

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

    def preview_quickbooks_mileage(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        _force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Validate a QuickBooks Download Trips export without writing it."""
        source_rows = list(rows)
        source_columns = {
            str(column)
            for row in source_rows
            for column in row
        }
        missing = missing_quickbooks_mileage_columns(source_columns)
        if missing:
            normalized = {
                "rows": [],
                "errors": [
                    "QuickBooks mileage export is missing columns: "
                    + ", ".join(missing)
                ],
                "personal_rows": [],
                "unreviewed_rows": [],
            }
        else:
            normalized = normalize_quickbooks_mileage_rows(source_rows)

        existing = {
            mileage_fingerprint(item)
            for item in self.list_mileage_trips(_force_refresh=_force_refresh)
        }
        seen: set[str] = set()
        ready: list[dict[str, str]] = []
        duplicate_rows: list[int] = []
        for source_item in normalized["rows"]:
            item = dict(source_item)
            row_number = int(item.pop("_source_row"))
            identity = mileage_fingerprint(item)
            if identity in existing or identity in seen:
                duplicate_rows.append(row_number)
            else:
                seen.add(identity)
                ready.append(item)
        return {
            "rows": ready,
            "errors": normalized["errors"],
            "duplicate_rows": duplicate_rows,
            "personal_rows": normalized["personal_rows"],
            "unreviewed_rows": normalized["unreviewed_rows"],
            "summary": {
                "ready": len(ready),
                "duplicates": len(duplicate_rows),
                "personal_skipped": len(normalized["personal_rows"]),
                "unreviewed_skipped": len(normalized["unreviewed_rows"]),
            },
        }

    def import_quickbooks_mileage(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        """Revalidate and batch append unique business mileage trips."""
        preview = self.preview_quickbooks_mileage(
            list(rows),
            _force_refresh=True,
        )
        if preview["errors"]:
            raise StorageValidationError("\n".join(preview["errors"]))
        prepared = [
            self._prepare_mileage_trip(item) for item in preview["rows"]
        ]
        self._append_many("Mileage", prepared)
        return prepared

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
                        "new_payee_name": row.get("Payee", ""),
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
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        auto_create: bool = False,
        _force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Validate and summarize a QuickBooks export without writing anything."""
        source_rows = list(rows)
        self._snapshot(
            ["Accounts", "Categories", "Transactions", "Payees"],
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
        existing = {
            fingerprint(item)
            for item in self.list_transactions()
        }
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
        accounts = self._account_lookup()
        categories = self._category_lookup()
        prepared = [
            self._prepare_transaction(
                {
                    **item,
                    "new_payee_name": item.get("payee", ""),
                    "payee": "",
                },
                accounts=accounts,
                categories=categories,
            )
            for item in preview["rows"]
        ]
        self._append_many("Transactions", prepared)
        return prepared

    def export_backup_zip(self, receipt_manifest: Mapping[str, Any]) -> bytes:
        """Return a fresh, checksummed backup of every ledger worksheet."""
        generated_at = _utc_now()
        row_counts: dict[str, int] = {}
        worksheet_headers: dict[str, list[str]] = {}
        csv_files: dict[str, bytes] = {}
        archive_buffer = io.BytesIO()
        snapshot = self._snapshot(WORKSHEET_HEADERS, force_refresh=True)
        _validate_hierarchy_records(
            [row.values for row in snapshot["Accounts"]],
            compatibility_field="classification",
            item_label="Account",
        )
        _validate_hierarchy_records(
            [row.values for row in snapshot["Categories"]],
            compatibility_field="kind",
            item_label="Category",
        )
        for title in WORKSHEET_HEADERS:
            headers = self._headers(title)
            rows = snapshot[title]
            row_counts[title] = len(rows)
            worksheet_headers[title] = headers
            csv_buffer = io.StringIO(newline="")
            writer = csv.writer(csv_buffer, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                writer.writerow([row.values.get(header, "") for header in headers])
            csv_files[f"{title}.csv"] = csv_buffer.getvalue().encode("utf-8")

        try:
            validated_receipts = validate_receipt_manifest(
                receipt_manifest,
                transaction_ids={
                    row.values["id"] for row in snapshot["Transactions"]
                },
            )
        except ReceiptManifestError as exc:
            raise StorageValidationError(str(exc)) from exc
        receipts_bytes = (
            json.dumps(validated_receipts, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        manifest = {
            "backup_time": generated_at,
            "format_version": BACKUP_FORMAT_VERSION,
            "row_counts": row_counts,
            "sha256": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in {
                    **csv_files,
                    "receipts.json": receipts_bytes,
                }.items()
            },
            "workbook_title": self.workbook_title,
            "worksheet_headers": worksheet_headers,
        }
        with zipfile.ZipFile(
            archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, content in csv_files.items():
                archive.writestr(name, content)
            archive.writestr("receipts.json", receipts_bytes)
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
        manifest, _, receipt_manifest = _parse_backup_zip(backup)
        result = dict(manifest)
        result["receipt_inventory"] = receipt_manifest is not None
        if receipt_manifest is not None:
            result["receipt_count"] = len(receipt_manifest["receipts"])
            result["business_profile_key"] = receipt_manifest[
                "business_profile_key"
            ]
        return result

    @staticmethod
    def receipt_manifest_from_backup(backup: bytes) -> dict[str, Any] | None:
        """Return a validated receipt inventory, or None for ledger-only backups."""
        _, _, receipt_manifest = _parse_backup_zip(backup)
        return receipt_manifest

    def restore_backup_zip(self, backup: bytes) -> dict[str, int]:
        """Restore a validated backup into a blank initialized workbook."""
        _, tables, _ = _parse_backup_zip(backup)
        legacy_payees = "legacy_payee" in tables["Transactions"][1][0] if tables["Transactions"][1] else False
        existing_payees = self.list_payees(_force_refresh=True)
        payees_by_key = {
            normalize_payee_name(item["name"]): item["id"] for item in existing_payees
        }
        if legacy_payees:
            for transaction in tables["Transactions"][1]:
                transaction["payee_id"] = payees_by_key.get(
                    normalize_payee_name(transaction.pop("legacy_payee", "")), ""
                )
        for title in WORKSHEET_HEADERS:
            target_headers = self._headers(title)
            if title in tables and set(target_headers) != set(tables[title][0]):
                raise StorageValidationError(
                    f"{title} target headers do not match the backup"
                )
            if self._rows(title, force_refresh=True) and not (
                title == "Payees" and legacy_payees
            ):
                raise StorageConflictError(
                    "Restore target must have empty ledger worksheets"
                )

        counts: dict[str, int] = {}
        for title in WORKSHEET_HEADERS:
            if title not in tables:
                continue
            _, records = tables[title]
            if not records and title == "Payees" and legacy_payees:
                continue
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
