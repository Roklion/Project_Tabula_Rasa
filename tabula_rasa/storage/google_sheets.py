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
from functools import wraps
from typing import Any, Callable, TypeVar
from uuid import NAMESPACE_URL, uuid4, uuid5

import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials

from tabula_rasa.hierarchy import (
    HierarchyValidationError,
    validate_two_level_hierarchy,
)
from tabula_rasa.mixed_use import (
    MIXED_USE_SOURCE_TYPE,
    MixedUseAllocationError,
    validate_mixed_use_allocation,
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
VERSION_7_WORKSHEET_HEADERS = {
    **VERSION_6_WORKSHEET_HEADERS,
    "Payees": ("id", "name", "active", "created_at"),
    "Transactions": tuple(
        "payee_id" if header == "payee" else header
        for header in VERSION_6_WORKSHEET_HEADERS["Transactions"]
    ),
}
PRE_MIXED_USE_WORKSHEET_HEADERS = VERSION_7_WORKSHEET_HEADERS
MIXED_USE_WORKSHEET_HEADERS = (
    "id",
    "txn_date",
    "kind",
    "total_expense",
    "business_use_percentage",
    "allocated_amount",
    "account_id",
    "category_id",
    "payee_id",
    "description",
    "reference",
    "receipt_references",
    "allocation_rationale",
    "linked_transaction_id",
    "tag_ids",
    "created_at",
)
WORKSHEET_HEADERS = {
    **PRE_MIXED_USE_WORKSHEET_HEADERS,
    "Transactions": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "source_type",
        "source_id",
    ),
    "MixedUseExpenses": MIXED_USE_WORKSHEET_HEADERS,
}
_PAYEE_WRITE_LOCK = threading.RLock()
_MIXED_USE_CREATE_LOCK = threading.RLock()
WORKSHEET_HEADERS = {
    **WORKSHEET_HEADERS,
    "Tags": ("id", "name", "active", "created_at"),
    "Transactions": (
        *WORKSHEET_HEADERS["Transactions"],
        "tag_ids",
    ),
    "Mileage": (
        *WORKSHEET_HEADERS["Mileage"],
        "tag_ids",
    ),
}
_TAG_WRITE_LOCK = threading.RLock()
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
BACKUP_FORMAT_VERSION = 10
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

# Workbook migration recognizes the v8 tags layout independently from the
# backup-format constants. The backup-only TAGS_WORKSHEET_HEADERS definition
# can therefore be retired by the legacy-backup migration work.
LEGACY_TAGS_WORKBOOK_HEADERS = {
    **PRE_MIXED_USE_WORKSHEET_HEADERS,
    "Tags": WORKSHEET_HEADERS["Tags"],
    "Transactions": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "tag_ids",
    ),
    "Mileage": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Mileage"],
        "tag_ids",
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


def _looks_like_historical_workbook(
    values: Mapping[str, list[list[Any]]],
) -> bool:
    """Return whether headers match a supported pre-current workbook layout."""
    historical_headers = (
        VERSION_3_WORKSHEET_HEADERS,
        PRE_PAYEE_WORKSHEET_HEADERS,
        VERSION_6_WORKSHEET_HEADERS,
        VERSION_7_WORKSHEET_HEADERS,
        LEGACY_TAGS_WORKBOOK_HEADERS,
    )
    for title, rows in values.items():
        if not rows:
            continue
        headers = [str(value).strip() for value in rows[0]]
        if "tag_ids__migration_pending" in headers:
            return True
        if (
            title == "MixedUseExpenses"
            and set(headers)
            == set(MIXED_USE_WORKSHEET_HEADERS) - {"tag_ids"}
            and len(headers) == len(set(headers))
        ):
            # Version 9 mixed-use sources predate durable source tag IDs.
            return True
        if any(
            title in layout
            and set(headers) == set(layout[title])
            and set(headers) != set(WORKSHEET_HEADERS.get(title, ()))
            and len(headers) == len(set(headers))
            for layout in historical_headers
        ):
            return True
    # Legacy workbooks commonly omit one or more worksheets entirely. Their
    # remaining standard tabs still identify the layout reliably.
    present_titles = set(values)
    if "MixedUseExpenses" not in present_titles:
        transactions = values.get("Transactions", [])
        if transactions:
            transaction_headers = {str(value).strip() for value in transactions[0]}
            if transaction_headers in (
                set(VERSION_7_WORKSHEET_HEADERS["Transactions"]),
                set(LEGACY_TAGS_WORKBOOK_HEADERS["Transactions"]),
            ):
                return True
    return False


def _looks_like_partial_blank_workbook(
    values: Mapping[str, list[list[Any]]],
) -> bool:
    """Return whether only current headers exist in a partial new workbook."""
    found_header = False
    for title, rows in values.items():
        if not any(str(value).strip() for row in rows for value in row):
            continue
        if title not in WORKSHEET_HEADERS or not rows:
            return False
        headers = [str(value).strip() for value in rows[0]]
        while headers and not headers[-1]:
            headers.pop()
        if headers != list(WORKSHEET_HEADERS[title]):
            return False
        if any(str(value).strip() for row in rows[1:] for value in row):
            return False
        found_header = True
    return found_header


class StorageError(RuntimeError):
    """Base class for safe, user-displayable storage errors."""


class StorageUnavailableError(StorageError):
    """Raised when Google Sheets cannot complete an API operation."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _mutation_guidance(operation: str) -> str:
    """Return the common user-facing guidance for an unconfirmed write."""
    operation_key = operation.casefold()
    if "mixed-use" in operation_key or "mixeduse" in operation_key:
        inspection_area = "Mixed-use expenses and the Transactions ledger"
    elif "payee" in operation_key:
        inspection_area = (
            "Payee management and the Transactions and MixedUseExpenses tables"
        )
    elif "tag" in operation_key:
        inspection_area = (
            "Tag management and the Transactions, Mileage, and MixedUseExpenses tables"
        )
    elif any(keyword in operation_key for keyword in ("bulk", "transaction", "category")):
        inspection_area = "the Transactions ledger"
    elif "receipt" in operation_key:
        inspection_area = "the receipt records and linked ledger rows"
    else:
        inspection_area = "the affected records"
    return (
        f"Google Sheets could not confirm the {operation}. Refresh and inspect "
        f"{inspection_area} before trying again; no success was reported."
    )


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


def _active_ledger_mutation_lock(operation: Callable[..., T]) -> Callable[..., T]:
    """Serialize writes that can create or change Payee/Tag references."""

    @wraps(operation)
    def locked(*args: Any, **kwargs: Any) -> T:
        with _MIXED_USE_CREATE_LOCK:
            return operation(*args, **kwargs)

    return locked


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


def normalize_tag_name(value: Any) -> str:
    """Normalize tag names for profile-local deduplication."""
    return " ".join(
        unicodedata.normalize("NFKC", _clean_text(value, "Tag name")).split()
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


def _validate_payee_records(records: Iterable[Mapping[str, Any]]) -> None:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for record in records:
        payee_id = _clean_text(record.get("id"), "Payee ID", required=True)
        name = _clean_text(record.get("name"), "Payee name", required=True)
        _as_bool(record.get("active"), "Payee active")
        name_key = normalize_payee_name(name)
        if payee_id in seen_ids or name_key in seen_names:
            raise StorageValidationError("Payee IDs and names must be unique")
        seen_ids.add(payee_id)
        seen_names.add(name_key)


def _decimal_values_match(actual: Any, expected: str) -> bool:
    try:
        return Decimal(str(actual).strip()) == Decimal(expected)
    except (InvalidOperation, ValueError):
        return False


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


def _normalize_tag_ids(value: Any) -> list[str]:
    """Return sorted, unique tag IDs from a JSON cell or write payload."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StorageValidationError("Tag IDs are not valid JSON") from exc
    if not isinstance(value, (list, tuple, set)):
        raise StorageValidationError("Tag IDs must be a JSON array")
    normalized: list[str] = []
    for tag_id in value:
        if not isinstance(tag_id, str):
            raise StorageValidationError("Tag IDs must be strings")
        clean_id = tag_id.strip()
        if not clean_id:
            raise StorageValidationError("Tag IDs cannot be blank")
        if clean_id in normalized:
            raise StorageValidationError("Tag IDs must be unique")
        normalized.append(clean_id)
    return sorted(normalized)


def _raw_tag_ids_may_contain(value: Any, candidates: Iterable[str]) -> bool:
    """Use a cheap substring check before parsing a stored tag-ID JSON cell."""
    raw_value = "" if value is None else str(value)
    return any(candidate in raw_value for candidate in candidates)


def _managed_comparison_text(value: Any) -> str:
    """Preserve falsy expected values while normalizing comparison text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    text = str(value).strip()
    return text.upper() if text.upper() in {"TRUE", "FALSE"} else text


def _encode_tag_ids(value: Any) -> str:
    return json.dumps(
        _normalize_tag_ids(value), separators=(",", ":"), ensure_ascii=False
    )


def _validate_tag_records(records: Iterable[Mapping[str, Any]]) -> None:
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for record in records:
        tag_id = _clean_text(record.get("id"), "Tag ID", required=True)
        name = _clean_text(record.get("name"), "Tag name", required=True)
        _as_bool(record.get("active"), "Tag active")
        name_key = normalize_tag_name(name)
        if tag_id in seen_ids or name_key in seen_names:
            raise StorageValidationError("Tag IDs and names must be unique")
        seen_ids.add(tag_id)
        seen_names.add(name_key)


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


def mixed_use_ledger_description(description: Any, rationale: Any) -> str:
    """Build the deterministic description for a mixed-use projection."""
    original = _clean_text(description, "Description")
    explanation = _clean_text(rationale, "Allocation rationale", required=True)
    prefix = f"{original}\n" if original else ""
    return f"{prefix}Allocation rationale: {explanation}"


def _validate_mixed_use_tables(
    tables: Mapping[str, tuple[Sequence[str], list[dict[str, str]]]],
) -> None:
    """Validate source/projection relationships in a workbook or backup."""
    source_table = tables.get("MixedUseExpenses")
    if source_table is None:
        sources: list[dict[str, str]] = []
    else:
        sources = source_table[1]
    transactions = tables.get("Transactions", ((), []))[1]
    sources_by_id: dict[str, dict[str, str]] = {}
    linked_ids: set[str] = set()
    for source in sources:
        source_id = _clean_text(source.get("id"), "Mixed-use source ID", required=True)
        if source_id in sources_by_id:
            raise StorageValidationError("Mixed-use source IDs must be unique")
        sources_by_id[source_id] = source
        if _clean_text(source.get("kind"), "Mixed-use kind", required=True) != "Expense":
            raise StorageValidationError("Mixed-use sources must be Expense records")
        _iso_date(source.get("txn_date"))
        _clean_text(source.get("account_id"), "Account", required=True)
        _clean_text(source.get("category_id"), "Category", required=True)
        linked_id = _clean_text(
            source.get("linked_transaction_id"),
            "Linked transaction ID",
            required=True,
        )
        if linked_id in linked_ids:
            raise StorageValidationError(
                "Mixed-use linked transaction IDs must be unique"
            )
        linked_ids.add(linked_id)
        try:
            allocation = validate_mixed_use_allocation(
                source.get("total_expense"),
                source.get("business_use_percentage"),
            )
        except MixedUseAllocationError as exc:
            raise StorageValidationError(str(exc)) from exc
        if not _decimal_values_match(
            source.get("total_expense"), allocation.total_expense
        ):
            raise StorageValidationError(
                "Mixed-use total expense has a non-canonical value"
            )
        if not _decimal_values_match(
            source.get("business_use_percentage"), allocation.business_use_percentage
        ):
            raise StorageValidationError(
                "Mixed-use business-use percentage has a non-canonical value"
            )
        if not _decimal_values_match(
            source.get("allocated_amount"), allocation.allocated_amount
        ):
            raise StorageValidationError(
                "Mixed-use allocated amount does not match its allocation"
            )
        _clean_text(source.get("allocation_rationale"), "Allocation rationale", required=True)
        decode_receipt_references(source.get("receipt_references", ""))
        _normalize_tag_ids(source.get("tag_ids", ""))

    transactions_by_id = {
        _clean_text(transaction.get("id"), "Transaction ID", required=True): transaction
        for transaction in transactions
    }
    if len(transactions_by_id) != len(transactions):
        raise StorageValidationError("Transaction IDs must be unique")
    linked_source_ids: set[str] = set()
    for transaction in transactions:
        source_type = _clean_text(transaction.get("source_type"), "Transaction source type")
        source_id = _clean_text(transaction.get("source_id"), "Transaction source ID")
        if bool(source_type) != bool(source_id):
            raise StorageValidationError(
                "Transaction source type and source ID must be provided together"
            )
        if not source_type:
            continue
        if source_type != MIXED_USE_SOURCE_TYPE:
            raise StorageValidationError("Transaction source type is unsupported")
        source = sources_by_id.get(source_id)
        if source is None:
            raise StorageValidationError(
                "Mixed-use projection references an unknown source record"
            )
        transaction_id = _clean_text(transaction.get("id"), "Transaction ID", required=True)
        if source_id in linked_source_ids:
            raise StorageValidationError(
                "A mixed-use source has more than one projection transaction"
            )
        linked_source_ids.add(source_id)
        if source.get("linked_transaction_id") != transaction_id:
            raise StorageValidationError(
                "Mixed-use source and projection IDs do not match"
            )
        if transaction.get("kind") != "Expense":
            raise StorageValidationError("Mixed-use projections must be Expense records")
        if _clean_text(transaction.get("to_account_id"), "Destination account"):
            raise StorageValidationError(
                "Mixed-use projections cannot have a destination account"
            )
        for field in (
            "txn_date",
            "account_id",
            "category_id",
            "payee_id",
            "reference",
        ):
            if _clean_text(transaction.get(field), field) != _clean_text(
                source.get(field), field
            ):
                raise StorageValidationError(
                    f"Mixed-use source and projection {field} values do not match"
                )
        if _clean_text(transaction.get("description"), "Description") != mixed_use_ledger_description(
            source.get("description"), source.get("allocation_rationale")
        ):
            raise StorageValidationError(
                "Mixed-use projection description is out of sync"
            )
        if not _decimal_values_match(
            transaction.get("amount"), source.get("allocated_amount")
        ):
            raise StorageValidationError(
                "Mixed-use projection amount does not match its source"
            )
        if transaction.get("receipt_references", "") != source.get(
            "receipt_references", ""
        ):
            raise StorageValidationError(
                "Mixed-use source and projection receipt references do not match"
            )
        if (
            "tag_ids" in source
            and "tag_ids" in transaction
            and _normalize_tag_ids(source.get("tag_ids", ""))
            != _normalize_tag_ids(transaction.get("tag_ids", ""))
        ):
            raise StorageValidationError(
                "Mixed-use source and projection tags do not match"
            )
    for source in sources:
        linked_id = source.get("linked_transaction_id")
        if linked_id not in transactions_by_id or _clean_text(
            transactions_by_id[linked_id].get("source_id"), "Transaction source ID"
        ) != source.get("id"):
            raise StorageValidationError(
                "Mixed-use source references a missing projection transaction"
            )


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
            if format_version != BACKUP_FORMAT_VERSION:
                raise StorageValidationError(
                    "Backup format version is not supported by the application; "
                    "convert it with scripts/migrate_legacy_backup.py first."
                )
            backup_headers = WORKSHEET_HEADERS
            required_files = {
                f"{title}.csv" for title in backup_headers
            } | {"manifest.json"}
            required_files.add("receipts.json")
            if set(names) != required_files:
                raise StorageValidationError(
                    "Backup must contain exactly the expected ledger and manifest files"
                )
            csv_files = {
                title: archive.read(f"{title}.csv") for title in backup_headers
            }
            receipt_manifest_bytes = archive.read("receipts.json")
    except StorageValidationError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise StorageValidationError("Backup is not a readable ZIP archive") from exc

    row_counts = manifest.get("row_counts")
    file_hashes = manifest.get("sha256")
    worksheet_headers = manifest.get("worksheet_headers")
    if not all(isinstance(value, dict) for value in (row_counts, file_hashes, worksheet_headers)):
        raise StorageValidationError("Backup manifest is missing validation metadata")
    expected_hash_names = {
        f"{title}.csv" for title in backup_headers
    } | {"receipts.json"}
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
        if title == "Payees":
            for record in records:
                record["id"] = record["id"].strip()
        elif title == "Transactions":
            for record in records:
                record["payee_id"] = _clean_text(record.get("payee_id"), "Payee")
        tables[title] = (headers, records)

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
    _validate_payee_records(tables["Payees"][1])
    for tag in tables["Tags"][1]:
        tag["id"] = _clean_text(tag.get("id"), "Tag ID", required=True)
        tag["name"] = _clean_text(tag.get("name"), "Tag name", required=True)
        tag["active"] = (
            "TRUE" if _as_bool(tag.get("active"), "Tag active") else "FALSE"
        )
    _validate_tag_records(tables["Tags"][1])

    account_ids = {record["id"] for record in tables["Accounts"][1]}
    category_ids = {record["id"] for record in tables["Categories"][1]}
    payee_ids = {record["id"] for record in tables["Payees"][1]}
    tag_ids = {record["id"] for record in tables["Tags"][1]}
    for title in ("Transactions", "Mileage", "MixedUseExpenses"):
        if title not in tables:
            continue
        for record in tables[title][1]:
            normalized_tag_ids = _normalize_tag_ids(record.get("tag_ids", ""))
            if any(tag_id not in tag_ids for tag_id in normalized_tag_ids):
                item_label = {
                    "Transactions": "transaction",
                    "Mileage": "mileage",
                    "MixedUseExpenses": "mixed-use source",
                }[title]
                raise StorageValidationError(
                    "Backup contains an unknown "
                    f"{item_label} tag"
                )
            record["tag_ids"] = _encode_tag_ids(normalized_tag_ids)
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

    category_records = {
        record["id"]: record for record in tables["Categories"][1]
    }
    for source in tables.get("MixedUseExpenses", ((), []))[1]:
        _iso_date(source.get("txn_date"))
        account_id = _clean_text(source.get("account_id"), "Account", required=True)
        if account_id not in account_ids:
            raise StorageValidationError("Backup contains an unknown mixed-use account")
        category_id = _clean_text(source.get("category_id"), "Category", required=True)
        if category_id not in category_ids:
            raise StorageValidationError("Backup contains an unknown mixed-use category")
        if category_records[category_id].get("kind") != "Expense":
            raise StorageValidationError(
                "Mixed-use source category must be an Expense category"
            )
        payee_id = _clean_text(source.get("payee_id"), "Payee")
        if payee_id and payee_id not in payee_ids:
            raise StorageValidationError("Backup contains an unknown mixed-use payee")

    _validate_mixed_use_tables(tables)

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
        """Open a workbook, bootstrapping only a genuinely blank workbook.

        Populated workbooks are intentionally validation-only. Historical
        schema conversion is performed by ``scripts/migrate_workbook.py`` so
        an ordinary application startup cannot mutate ledger data.
        """
        workbook = cls._open_workbook_from_secrets(
            secrets,
            scopes=[SHEETS_SCOPE],
        )
        try:
            worksheets = {
                worksheet.title: worksheet for worksheet in workbook.worksheets()
            }
            values = {
                title: worksheet.get_all_values()
                for title, worksheet in worksheets.items()
            }
            is_blank = not any(
                str(value).strip()
                for rows in values.values()
                for row in rows
                for value in row
            )
            if is_blank or _looks_like_partial_blank_workbook(values):
                for title, headers in WORKSHEET_HEADERS.items():
                    worksheet = worksheets.get(title)
                    if worksheet is None:
                        worksheet = workbook.add_worksheet(
                            title=title,
                            rows=1000,
                            cols=len(headers),
                        )
                        worksheets[title] = worksheet
                    worksheet.update([list(headers)], range_name="A1", raw=True)
                return cls(
                    workbook,
                    _initial_worksheets=worksheets,
                    _initial_values={
                        title: [list(headers)]
                        for title, headers in WORKSHEET_HEADERS.items()
                    },
                )

            try:
                return cls(
                    workbook,
                    _initial_worksheets=worksheets,
                    _initial_values=values,
                )
            except StorageValidationError as exc:
                if _looks_like_historical_workbook(values):
                    raise StorageInitializationError(
                        "This workbook uses an older Tabula Rasa schema. "
                        "Run `python scripts/migrate_workbook.py --profile "
                        "PROFILE_KEY` for the selected workbook, replacing "
                        "PROFILE_KEY with its business-profile key, then "
                        "restart the application."
                    ) from exc
                raise
        except GoogleAuthError as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc
        except (PermissionError, gspread.GSpreadException, OSError) as exc:
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

    def _write_with_confirmation(
        self,
        operation: str,
        write: Callable[[], None],
        readback: Callable[[], str],
        *,
        before_retry: Callable[[], None] | None = None,
        invalidate: Iterable[str] = (),
    ) -> None:
        """Perform one mutation, confirming uncertain responses before retrying.

        ``readback`` returns ``"applied"`` when the requested postcondition is
        present, ``"unchanged"`` when the complete precondition is still
        present, and ``"ambiguous"`` for every partial or conflicting state.
        A write is never retried more than once and only an unchanged state is
        safe to retry.  Cache invalidation happens before every failure leaves
        this method so callers cannot continue using a stale snapshot.
        """
        retried = False
        while True:
            try:
                write()
            except StorageUnavailableError as error:
                if not error.retryable:
                    for title in invalidate:
                        self._invalidate(title)
                    if retried:
                        raise StorageUnavailableError(
                            _mutation_guidance(operation), retryable=False
                        ) from error
                    raise
                try:
                    state = readback()
                except (StorageError, OSError) as read_error:
                    for title in invalidate:
                        self._invalidate(title)
                    raise StorageUnavailableError(
                        _mutation_guidance(operation), retryable=False
                    ) from read_error
                if state == "applied":
                    for title in invalidate:
                        self._invalidate(title)
                    return
                if state == "unchanged" and not retried:
                    retried = True
                    if before_retry is not None:
                        try:
                            before_retry()
                        except (StorageError, OSError):
                            for title in invalidate:
                                self._invalidate(title)
                            raise
                    self._sleeper(self._retry_base_delay_seconds)
                    continue
                for title in invalidate:
                    self._invalidate(title)
                raise StorageUnavailableError(
                    _mutation_guidance(operation), retryable=False
                ) from error
            else:
                for title in invalidate:
                    self._invalidate(title)
                return

    def _append(self, title: str, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        record_id = _clean_text(record.get("id"), "ID")

        def state() -> str:
            rows = self._rows(title, force_refresh=True)
            matches = [
                row for row in rows
                if _clean_text(row.values.get("id"), "ID") == record_id
            ]
            if not matches:
                return "unchanged"
            if len(matches) != 1:
                return "ambiguous"
            expected = {header: str(record.get(header, "")) for header in headers}
            return "applied" if matches[0].values == expected else "ambiguous"

        self._write_with_confirmation(
            f"{title} append",
            lambda: self._api(
                lambda: worksheet.append_row(values, value_input_option="RAW"),
                retry_safe=False,
            ),
            state,
            invalidate=(title,),
        )

    def _append_many(self, title: str, records: Iterable[Mapping[str, Any]]) -> None:
        records = list(records)
        if not records:
            return
        headers = self._headers(title)
        values = [
            [str(record.get(header, "")) for header in headers] for record in records
        ]
        worksheet = self._worksheet(title)
        record_ids = {
            _clean_text(record.get("id"), "ID") for record in records
        }

        def state() -> str:
            rows = self._rows(title, force_refresh=True)
            by_id: dict[str, dict[str, str]] = {}
            for row in rows:
                record_id = _clean_text(row.values.get("id"), "ID")
                if record_id in by_id:
                    return "ambiguous"
                by_id[record_id] = row.values
            expected = {
                _clean_text(record.get("id"), "ID"): {
                    header: str(record.get(header, "")) for header in headers
                }
                for record in records
            }
            if all(by_id.get(record_id) == item for record_id, item in expected.items()):
                return "applied"
            if not any(record_id in by_id for record_id in record_ids):
                return "unchanged"
            return "ambiguous"

        self._write_with_confirmation(
            f"{title} batch append",
            lambda: self._api(
                lambda: worksheet.append_rows(values, value_input_option="RAW"),
                retry_safe=False,
            ),
            state,
            invalidate=(title,),
        )

    def _replace_row(self, title: str, row: _StoredRow, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        record_id = _clean_text(record.get("id"), "ID", required=True)
        original = dict(row.values)
        current_row = row

        def write() -> None:
            self._api(
                lambda: worksheet.update(
                    [values], range_name=f"A{current_row.row_number}", raw=True
                ),
                retry_safe=False,
            )

        def state() -> str:
            latest = self._find_row(title, record_id)
            if latest.values == {header: str(record.get(header, "")) for header in headers}:
                return "applied"
            return "unchanged" if latest.values == original else "ambiguous"

        def refresh() -> None:
            nonlocal current_row
            latest = self._find_row(title, record_id)
            if latest.values != original:
                raise StorageConflictError(
                    f"The {title} row changed while the write was being retried."
                )
            current_row = latest

        self._write_with_confirmation(
            f"{title} update", write, state, before_retry=refresh, invalidate=(title,)
        )

    def _replace_rows(
        self,
        title: str,
        updates: Sequence[tuple[_StoredRow, Mapping[str, Any]]],
        *,
        before_retry: Callable[[], None] | None = None,
    ) -> None:
        if not updates:
            return
        headers = self._headers(title)
        worksheet = self._worksheet(title)
        current_updates = list(updates)
        originals = {
            _clean_text(record.get("id"), "ID", required=True): dict(row.values)
            for row, record in updates
        }
        if len(originals) != len(updates):
            raise StorageValidationError(f"Duplicate ID detected in {title}")

        def write() -> None:
            batch = [
                {
                    "range": f"A{row.row_number}",
                    "values": [[str(record.get(header, "")) for header in headers]],
                }
                for row, record in current_updates
            ]
            self._api(
                lambda: worksheet.batch_update(batch, raw=True),
                retry_safe=False,
            )

        intended_by_id = {
            _clean_text(record.get("id"), "ID", required=True): {
                header: str(record.get(header, "")) for header in headers
            }
            for _, record in updates
        }
        if len(intended_by_id) != len(updates):
            raise StorageValidationError(f"Duplicate ID detected in {title}")

        def state() -> str:
            current_rows = self._rows(title, force_refresh=True)
            current_by_id = {
                _clean_text(item.values.get("id"), "ID", required=True): item
                for item in current_rows
            }
            if all(
                current_by_id.get(record_id, _StoredRow(0, {})).values == intended
                for record_id, intended in intended_by_id.items()
            ):
                return "applied"
            if all(
                current_by_id.get(record_id, _StoredRow(0, {})).values
                == originals[record_id]
                for record_id in originals
            ):
                return "unchanged"
            return "ambiguous"

        def refresh() -> None:
            nonlocal current_updates
            if before_retry is not None:
                before_retry()
            retry_rows = self._rows(title, force_refresh=True)
            retry_by_id = {
                _clean_text(item.values.get("id"), "ID", required=True): item
                for item in retry_rows
            }
            if any(
                retry_by_id.get(record_id, _StoredRow(0, {})).values
                != originals[record_id]
                for record_id in originals
            ):
                raise StorageConflictError(
                    f"A row in {title} changed unexpectedly during a write retry."
                )
            current_updates = [
                (retry_by_id[record_id], record)
                for record_id, (_, record) in zip(
                    originals, updates
                )
            ]

        self._write_with_confirmation(
            f"{title} batch update",
            write,
            state,
            before_retry=refresh,
            invalidate=(title,),
        )

    def _replace_rows_atomically(
        self,
        updates: Sequence[tuple[str, _StoredRow, Mapping[str, Any]]],
    ) -> None:
        """Replace rows across worksheets in one spreadsheet-level batch."""
        if not updates:
            return
        requests: list[dict[str, Any]] = []
        titles: set[str] = set()
        for title, row, record in updates:
            headers = self._headers(title)
            titles.add(title)
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": self._sheet_id(title),
                            "startRowIndex": row.row_number - 1,
                            "endRowIndex": row.row_number,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        },
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {
                                            "stringValue": str(record.get(header, ""))
                                        }
                                    }
                                    for header in headers
                                ]
                            }
                        ],
                        "fields": "userEnteredValue",
                    }
                }
            )
        self._batch_update_spreadsheet(requests)
        for title in titles:
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
            current = dict(row.values)
            if "payee_id" in current:
                current["payee_id"] = _clean_text(current.get("payee_id"), "Payee")
            if "tag_ids" in current:
                current["tag_ids"] = _encode_tag_ids(current.get("tag_ids", ""))
            if any(
                (
                    not _decimal_values_match(current.get(key), value)
                    if key == "amount"
                    else current.get(key, "") != value
                )
                for key, value in expected.items()
            ):
                raise StorageConflictError(
                    "A selected transaction changed; review the current rows and try again."
                )
            selected_rows[transaction_id] = row
            current_by_id_values[transaction_id] = current
        return selected_rows, current_by_id_values

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
                str(row.values["id"]): dict(row.values)
                for row in self._rows("Transactions", force_refresh=True)
            }
            if all(
                item in current and current[item].get("category_id") == category_id
                for item in pending_by_id
            ):
                return "applied"
            if all(
                item in current and current[item] == pending_by_id[item]
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

        self._write_with_confirmation(
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
                    str(row.values["id"]): dict(row.values)
                    for row in self._rows("Transactions", force_refresh=True)
                }
                if not any(item in current for item in original_by_id):
                    return "applied"
                if all(current.get(item) == value for item, value in original_by_id.items()):
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

            self._write_with_confirmation(
                "transaction deletion", write, state,
                before_retry=refresh, invalidate=("Transactions",),
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
        with _MIXED_USE_CREATE_LOCK:
            return self._edit_category(category_id, **changes)

    def _edit_category(self, category_id: str, **changes: Any) -> dict[str, str]:
        current = self._find_row("Categories", category_id)
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
            sources, _ = self._raw_mixed_use_snapshot()
            if any(
                str(source.get("category_id") or "").strip()
                == normalized_category_id
                for source in sources.values()
            ):
                raise StorageConflictError(
                    "Category kind cannot change while used by a mixed-use expense"
                )
        if kind != updated["kind"]:
            reject_mixed_use_kind_change()
            current = self._find_row("Categories", normalized_category_id)
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

    def delete_category(self, category_id: str) -> None:
        with _MIXED_USE_CREATE_LOCK:
            self._delete_category(category_id)

    def _delete_category(self, category_id: str) -> None:
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
        mixed_use_sources = self._rows("MixedUseExpenses", force_refresh=True)
        if any(
            _clean_text(row.values.get("category_id"), "Category") == category_id
            for row in mixed_use_sources
        ):
            raise StorageConflictError(
                "That category has mixed-use expenses and cannot be deleted"
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
            mixed_use_sources = self._rows("MixedUseExpenses", force_refresh=True)
            if any(
                _clean_text(row.values.get("category_id"), "Category") == category_id
                for row in mixed_use_sources
            ):
                raise StorageConflictError(
                    "That category has mixed-use expenses and cannot be deleted"
                )
            current_row = self._find_row("Categories", category_id)
            if current_row.values != original:
                raise StorageConflictError(
                    "The category changed while deletion was being retried."
                )

        # Repeat the referential and row checks immediately before the write;
        # the first snapshot only discovers the candidate row.
        refresh()
        self._write_with_confirmation(
            "category deletion", write, state, before_retry=refresh,
            invalidate=("Categories",),
        )

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
        with _PAYEE_WRITE_LOCK:
            existing = self.list_payees(_force_refresh=True)
            key = normalize_payee_name(name)
            match = next(
                (item for item in existing if normalize_payee_name(item["name"]) == key),
                None,
            )
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

    def _ensure_payee_names(
        self, names: Iterable[Any]
    ) -> dict[str, dict[str, str]]:
        with _PAYEE_WRITE_LOCK:
            payees = self.list_payees(_force_refresh=True)
            by_key = {normalize_payee_name(item["name"]): item for item in payees}
            rows_by_id = {
                _clean_text(row.values.get("id"), "Payee ID", required=True): row
                for row in self._rows("Payees")
            }
            additions: list[dict[str, str]] = []
            activations: list[dict[str, str]] = []
            for value in names:
                name = _clean_text(value, "New payee")
                if not name:
                    continue
                key = normalize_payee_name(name)
                match = by_key.get(key)
                if match is None:
                    match = {
                        "id": str(uuid4()),
                        "name": name,
                        "active": "TRUE",
                        "created_at": _utc_now(),
                    }
                    additions.append(match)
                    by_key[key] = match
                elif match["active"] != "TRUE":
                    match = dict(match)
                    match["active"] = "TRUE"
                    activations.append(match)
                    by_key[key] = match
            if activations:
                self._replace_rows(
                    "Payees",
                    [(rows_by_id[item["id"]], item) for item in activations],
                )
            if additions:
                self._append_many("Payees", additions)
            return {item["id"]: item for item in by_key.values()}

    def edit_payee(
        self,
        payee_id: str,
        *,
        expected_payee: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        with _PAYEE_WRITE_LOCK:
            current = self._find_row("Payees", payee_id)
            updated = dict(current.values)
            expected_record = expected_payee or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {str(updated["id"]): updated}, expected_record
                )
            name = _clean_text(
                changes.get("name", updated["name"]),
                "Payee name",
                required=True,
            )
            if "name" in changes and normalize_payee_name(name) != normalize_payee_name(updated["name"]):
                existing = self.list_payees(_force_refresh=True)
                if any(
                    item["id"] != payee_id
                    and normalize_payee_name(item["name"]) == normalize_payee_name(name)
                    for item in existing
                ):
                    raise StorageConflictError("That payee already exists")
            updated.update(
                {
                    "name": name,
                    "active": "TRUE"
                    if _as_bool(
                        changes.get("active", updated["active"]), "Payee active"
                    )
                    else "FALSE",
                }
            )
            self._replace_row("Payees", current, updated)
            return updated

    @staticmethod
    def _expected_managed_records(
        expected: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
    ) -> dict[str, Mapping[str, Any]]:
        """Normalize an optional caller snapshot used by management actions."""
        if expected is None:
            return {}
        if isinstance(expected, Mapping) and "id" in expected:
            values = [(expected.get("id"), expected)]
        elif isinstance(expected, Mapping):
            values = expected.items()
        else:
            values = ((None, item) for item in expected)
        result: dict[str, Mapping[str, Any]] = {}
        for mapping_id, item in values:
            record_id = _clean_text(
                item.get("id", mapping_id), "Managed record ID", required=True
            )
            result[record_id] = item
        return result

    @staticmethod
    def _assert_expected_managed_records(
        current: Mapping[str, Mapping[str, str]],
        expected: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
    ) -> None:
        for record_id, expected_record in GoogleSheetsStorage._expected_managed_records(
            expected
        ).items():
            actual = current.get(record_id)
            if actual is None or any(
                _managed_comparison_text(actual.get(key))
                != _managed_comparison_text(value)
                for key, value in expected_record.items()
                if key != "tags"
            ):
                raise StorageConflictError(
                    "A payee or tag changed; refresh the management list and try again."
                )

    @staticmethod
    def _managed_rows_by_id(
        rows: Iterable[_StoredRow], title: str
    ) -> dict[str, _StoredRow]:
        result: dict[str, _StoredRow] = {}
        for row in rows:
            record_id = _clean_text(row.values.get("id"), f"{title} ID", required=True)
            if record_id in result:
                raise StorageValidationError(f"Duplicate ID detected in {title}")
            result[record_id] = row
        return result

    def _managed_write(
        self,
        *,
        operation: str,
        requests: Sequence[Mapping[str, Any]],
        read_state: Callable[[], Any],
        applied: Callable[[Any], bool],
        unchanged: Callable[[Any], bool],
        before_retry: Callable[[], None] | None = None,
        invalidate: Iterable[str],
    ) -> None:
        """Write one managed batch with one fresh readback and safe retry."""

        def state() -> str:
            current = read_state()
            if applied(current):
                return "applied"
            if unchanged(current):
                return "unchanged"
            return "ambiguous"

        self._write_with_confirmation(
            operation,
            lambda: self._batch_update_spreadsheet(requests),
            state,
            before_retry=before_retry,
            invalidate=invalidate,
        )

    def _managed_update_request(
        self, title: str, row: _StoredRow, column: str, value: str
    ) -> dict[str, Any]:
        headers = self._headers(title)
        column_index = self._sheet_column_index(headers, column)
        return {
            "updateCells": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "startRowIndex": row.row_number - 1,
                    "endRowIndex": row.row_number,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "rows": [{"values": [{"userEnteredValue": {"stringValue": value}}]}],
                "fields": "userEnteredValue",
            }
        }

    def _managed_delete_request(self, title: str, row: _StoredRow) -> dict[str, Any]:
        return {
            "deleteDimension": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "dimension": "ROWS",
                    "startIndex": row.row_number - 1,
                    "endIndex": row.row_number,
                }
            }
        }

    def merge_payees(
        self,
        target_payee_id: str,
        source_payee_ids: Sequence[str],
        *,
        expected_payees: Iterable[Mapping[str, Any]]
        | Mapping[str, Mapping[str, Any]]
        | None = None,
    ) -> dict[str, str]:
        """Merge source payees into one target while preserving all references."""
        target_id = _clean_text(target_payee_id, "Target payee", required=True)
        source_ids = list(dict.fromkeys(
            _clean_text(item, "Source payee", required=True) for item in source_payee_ids
        ))
        if not source_ids:
            raise StorageValidationError("Select at least one source payee")
        if target_id in source_ids:
            raise StorageValidationError("The target payee cannot also be a source")
        with _MIXED_USE_CREATE_LOCK, _PAYEE_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
            )
            _validate_mixed_use_tables(
                {
                    "MixedUseExpenses": (
                        WORKSHEET_HEADERS["MixedUseExpenses"],
                        [dict(row.values) for row in snapshot["MixedUseExpenses"]],
                    ),
                    "Transactions": (
                        WORKSHEET_HEADERS["Transactions"],
                        [dict(row.values) for row in snapshot["Transactions"]],
                    ),
                }
            )
            payee_rows = self._managed_rows_by_id(snapshot["Payees"], "Payees")
            payees = {record_id: dict(row.values) for record_id, row in payee_rows.items()}
            if target_id not in payees:
                raise StorageNotFoundError("Payee no longer exists")
            missing = [item for item in source_ids if item not in payees]
            if missing and len(missing) == len(source_ids):
                # A retried merge may have already removed every source. Once
                # the target still exists and no reference survives, this is
                # a safe converged outcome. Do not hide an inconsistent
                # workbook behind a successful retry.
                expected_records = self._expected_managed_records(expected_payees)
                self._assert_expected_managed_records(
                    {target_id: payees[target_id]},
                    {target_id: expected_records[target_id]}
                    if target_id in expected_records
                    else None,
                )
                references = [
                    row
                    for row in (*snapshot["Transactions"], *snapshot["MixedUseExpenses"])
                    if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
                ]
                if not references:
                    return {"status": "fully_applied", "count": str(len(source_ids))}
                raise StorageConflictError(
                    "The selected source payee records are missing but their references remain."
                )
            if missing:
                raise StorageNotFoundError("A source payee no longer exists")
            self._assert_expected_managed_records(payees, expected_payees)

            transaction_rows = self._managed_rows_by_id(snapshot["Transactions"], "Transactions")
            mixed_rows = self._managed_rows_by_id(snapshot["MixedUseExpenses"], "MixedUseExpenses")
            transaction_updates = {
                record_id: row
                for record_id, row in transaction_rows.items()
                if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
            }
            mixed_updates = {
                record_id: row
                for record_id, row in mixed_rows.items()
                if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
            }
            requests: list[dict[str, Any]] = []
            for row in transaction_updates.values():
                requests.append(
                    self._managed_update_request(
                        "Transactions", row, "payee_id", target_id
                    )
                )
            for row in mixed_updates.values():
                requests.append(
                    self._managed_update_request(
                        "MixedUseExpenses", row, "payee_id", target_id
                    )
                )
            for source_id in sorted(source_ids, key=lambda item: payee_rows[item].row_number, reverse=True):
                requests.append(self._managed_delete_request("Payees", payee_rows[source_id]))
            if not requests:
                raise StorageValidationError("The selected payees have no mergeable changes")

            def fresh_state() -> tuple[dict[str, dict[str, str]], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
                )
                return (
                    {record_id: dict(row.values) for record_id, row in self._managed_rows_by_id(current["Payees"], "Payees").items()},
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                )

            def is_applied(state: Any) -> bool:
                current_payees, current_transactions, current_mixed = state
                return (
                    target_id in current_payees
                    and not any(item in current_payees for item in source_ids)
                    and all(
                        _clean_text(row.values.get("payee_id"), "Payee") != source_id
                        for source_id in source_ids
                        for row in (*current_transactions.values(), *current_mixed.values())
                    )
                    and all(
                        record_id in current_transactions
                        and _clean_text(current_transactions[record_id].values.get("payee_id"), "Payee") == target_id
                        for record_id in transaction_updates
                    )
                    and all(
                        record_id in current_mixed
                        and _clean_text(current_mixed[record_id].values.get("payee_id"), "Payee") == target_id
                        for record_id in mixed_updates
                    )
                )

            def is_unchanged(state: Any) -> bool:
                current_payees, current_transactions, current_mixed = state
                if any(
                    record_id not in current_payees
                    or current_payees[record_id] != row.values
                    for record_id, row in payee_rows.items()
                ):
                    return False
                return all(
                    record_id in current_transactions
                    and current_transactions[record_id].values == row.values
                    for record_id, row in transaction_updates.items()
                ) and all(
                    record_id in current_mixed and current_mixed[record_id].values == row.values
                    for record_id, row in mixed_updates.items()
                )

            def refresh_requests() -> None:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"],
                    force_refresh=True,
                )
                current_payees = self._managed_rows_by_id(current["Payees"], "Payees")
                current_transactions = self._managed_rows_by_id(
                    current["Transactions"], "Transactions"
                )
                current_mixed = self._managed_rows_by_id(
                    current["MixedUseExpenses"], "MixedUseExpenses"
                )
                refreshed = [
                    self._managed_update_request(
                        "Transactions", current_transactions[record_id], "payee_id", target_id
                    )
                    for record_id in transaction_updates
                ]
                refreshed.extend(
                    self._managed_update_request(
                        "MixedUseExpenses", current_mixed[record_id], "payee_id", target_id
                    )
                    for record_id in mixed_updates
                )
                refreshed.extend(
                    self._managed_delete_request("Payees", current_payees[source_id])
                    for source_id in sorted(
                        source_ids,
                        key=lambda item: current_payees[item].row_number,
                        reverse=True,
                    )
                )
                requests[:] = refreshed

            self._managed_write(
                operation="payee merge",
                requests=requests,
                read_state=fresh_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Payees", "Transactions", "MixedUseExpenses"),
            )
            return {"status": "fully_applied", "count": str(len(source_ids))}

    merge_payee = merge_payees

    def remove_payee(
        self,
        payee_id: str,
        *,
        expected_payee: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Permanently remove one unreferenced payee after a fresh check."""
        payee_id = _clean_text(payee_id, "Payee", required=True)
        with _MIXED_USE_CREATE_LOCK, _PAYEE_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
            )
            payee_rows = self._managed_rows_by_id(snapshot["Payees"], "Payees")
            if payee_id not in payee_rows:
                raise StorageNotFoundError("Payee no longer exists")
            expected_record = expected_payee or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {payee_id: dict(payee_rows[payee_id].values)}, expected_record
                )
            references = sum(
                _clean_text(row.values.get("payee_id"), "Payee") == payee_id
                for row in (*snapshot["Transactions"], *snapshot["MixedUseExpenses"])
            )
            if references:
                raise StorageConflictError(
                    f"This payee is referenced by {references} records. Merge it or unassign it first."
                )
            request = self._managed_delete_request("Payees", payee_rows[payee_id])

            def read_state() -> tuple[dict[str, _StoredRow], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Payees"], "Payees"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                )

            def references_present(state: Any) -> bool:
                _, current_transactions, current_mixed = state
                return any(
                    _clean_text(row.values.get("payee_id"), "Payee") == payee_id
                    for row in (*current_transactions.values(), *current_mixed.values())
                )

            def is_applied(state: Any) -> bool:
                current_payees, _, _ = state
                return payee_id not in current_payees and not references_present(state)

            def is_unchanged(state: Any) -> bool:
                current_payees, _, _ = state
                return (
                    payee_id in current_payees
                    and current_payees[payee_id].values == payee_rows[payee_id].values
                    and not references_present(state)
                )

            def refresh_request() -> None:
                current_payees, _, _ = read_state()
                refreshed = self._managed_delete_request(
                    "Payees", current_payees[payee_id]
                )
                requests[:] = [refreshed]

            requests = [request]
            self._managed_write(
                operation="payee removal",
                requests=requests,
                read_state=read_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_request,
                invalidate=("Payees", "Transactions", "MixedUseExpenses"),
            )
            return {"status": "fully_applied"}

    delete_payee = remove_payee

    def list_tags(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        tags: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Tags", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Tag ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Tag name", required=True)
            item["active"] = (
                "TRUE" if _as_bool(item.get("active"), "Tag active") else "FALSE"
            )
            item["created_at"] = _clean_text(item.get("created_at"), "Tag created at")
            name_key = normalize_tag_name(item["name"])
            if item["id"] in seen_ids or name_key in seen_names:
                raise StorageValidationError("Tag IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(name_key)
            if not active_only or item["active"] == "TRUE":
                tags.append(item)
        return sorted(tags, key=lambda item: item["name"].casefold())

    def create_tag(self, name: str, *, active: bool = True) -> dict[str, str]:
        """Create or reactivate a profile-local tag by normalized name."""
        name = _clean_text(name, "Tag name", required=True)
        with _TAG_WRITE_LOCK:
            existing = self.list_tags(_force_refresh=True)
            key = normalize_tag_name(name)
            match = next(
                (item for item in existing if normalize_tag_name(item["name"]) == key),
                None,
            )
            if match is not None:
                if active and match["active"] != "TRUE":
                    current = self._find_row("Tags", match["id"])
                    updated = dict(current.values)
                    updated["active"] = "TRUE"
                    self._replace_row("Tags", current, updated)
                    match = {**match, "active": "TRUE"}
                return match
            record = {
                "id": str(uuid4()),
                "name": name,
                "active": "TRUE" if active else "FALSE",
                "created_at": _utc_now(),
            }
            self._append("Tags", record)
            return record

    def edit_tag(
        self,
        tag_id: str,
        *,
        expected_tag: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        """Rename or activate/deactivate a tag while retaining its stable ID."""
        tag_id = _clean_text(tag_id, "Tag", required=True)
        with _TAG_WRITE_LOCK:
            current = self._find_row("Tags", tag_id)
            updated = dict(current.values)
            expected_record = expected_tag or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {str(updated["id"]): updated}, expected_record
                )
            name = _clean_text(changes.get("name", updated.get("name")), "Tag name", required=True)
            if normalize_tag_name(name) != normalize_tag_name(updated.get("name", "")):
                existing = self.list_tags(_force_refresh=True)
                if any(
                    item["id"] != tag_id
                    and normalize_tag_name(item["name"]) == normalize_tag_name(name)
                    for item in existing
                ):
                    raise StorageConflictError("That tag already exists")
            updated.update({
                "name": name,
                "active": "TRUE"
                if _as_bool(changes.get("active", updated.get("active")), "Tag active")
                else "FALSE",
            })
            self._replace_row("Tags", current, updated)
            return updated

    def merge_tags(
        self,
        target_tag_id: str,
        source_tag_ids: Sequence[str],
        *,
        expected_tags: Iterable[Mapping[str, Any]]
        | Mapping[str, Mapping[str, Any]]
        | None = None,
    ) -> dict[str, str]:
        """Merge source tags into a target across tagged worksheet rows."""
        target_id = _clean_text(target_tag_id, "Target tag", required=True)
        source_ids = list(dict.fromkeys(
            _clean_text(item, "Source tag", required=True) for item in source_tag_ids
        ))
        if not source_ids:
            raise StorageValidationError("Select at least one source tag")
        if target_id in source_ids:
            raise StorageValidationError("The target tag cannot also be a source")
        with _MIXED_USE_CREATE_LOCK, _TAG_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                force_refresh=True,
            )
            tag_rows = self._managed_rows_by_id(snapshot["Tags"], "Tags")
            tags = {record_id: dict(row.values) for record_id, row in tag_rows.items()}
            if target_id not in tags:
                raise StorageNotFoundError("Tag no longer exists")
            missing = [item for item in source_ids if item not in tags]
            if missing and len(missing) == len(source_ids):
                expected_records = self._expected_managed_records(expected_tags)
                self._assert_expected_managed_records(
                    {target_id: tags[target_id]},
                    {target_id: expected_records[target_id]}
                    if target_id in expected_records
                    else None,
                )
                references = []
                for row in (
                    *snapshot["Transactions"],
                    *snapshot["Mileage"],
                    *snapshot["MixedUseExpenses"],
                ):
                    raw_tags = row.values.get("tag_ids", "")
                    if _raw_tag_ids_may_contain(raw_tags, source_ids) and any(
                        item in source_ids for item in _normalize_tag_ids(raw_tags)
                    ):
                        references.append(row)
                if not references:
                    return {"status": "fully_applied", "count": str(len(source_ids))}
                raise StorageConflictError(
                    "The selected source tag records are missing but their references remain."
                )
            if missing:
                raise StorageNotFoundError("A source tag no longer exists")
            self._assert_expected_managed_records(tags, expected_tags)
            update_rows: dict[str, tuple[str, _StoredRow, str]] = {}
            for title in ("Transactions", "Mileage", "MixedUseExpenses"):
                for record_id, row in self._managed_rows_by_id(snapshot[title], title).items():
                    raw_tags = row.values.get("tag_ids", "")
                    if not _raw_tag_ids_may_contain(raw_tags, source_ids):
                        continue
                    tag_ids = _normalize_tag_ids(raw_tags)
                    if not any(item in source_ids for item in tag_ids):
                        continue
                    merged_ids = [target_id if item in source_ids else item for item in tag_ids]
                    merged_ids = list(dict.fromkeys(merged_ids))
                    update_rows[f"{title}:{record_id}"] = (
                        title, row, _encode_tag_ids(merged_ids)
                    )
            requests = [
                self._managed_update_request(title, row, "tag_ids", value)
                for title, row, value in update_rows.values()
            ]
            for source_id in sorted(source_ids, key=lambda item: tag_rows[item].row_number, reverse=True):
                requests.append(self._managed_delete_request("Tags", tag_rows[source_id]))

            def fresh_state() -> tuple[
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                )

            def is_applied(state: Any) -> bool:
                (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                ) = state
                if target_id not in current_tags or any(item in current_tags for item in source_ids):
                    return False
                if any(
                    item in _normalize_tag_ids(row.values.get("tag_ids", ""))
                    for item in source_ids
                    for row in (
                        *current_transactions.values(),
                        *current_mileage.values(),
                        *current_sources.values(),
                    )
                ):
                    return False
                for title, row, expected_value in update_rows.values():
                    current_rows = {
                        "Transactions": current_transactions,
                        "Mileage": current_mileage,
                        "MixedUseExpenses": current_sources,
                    }[title]
                    record_id = _clean_text(row.values.get("id"), "ID", required=True)
                    if record_id not in current_rows:
                        return False
                    if str(current_rows[record_id].values.get("tag_ids", "")) != expected_value:
                        return False
                return True

            def is_unchanged(state: Any) -> bool:
                (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                ) = state
                if any(
                    record_id not in current_tags
                    or current_tags[record_id].values != row.values
                    for record_id, row in tag_rows.items()
                ):
                    return False
                for title, row, _ in update_rows.values():
                    current_rows = {
                        "Transactions": current_transactions,
                        "Mileage": current_mileage,
                        "MixedUseExpenses": current_sources,
                    }[title]
                    current = current_rows.get(
                        _clean_text(row.values.get("id"), "ID", required=True)
                    )
                    if current is None or current.values != row.values:
                        return False
                return True

            def refresh_requests() -> None:
                current_tags, current_transactions, current_mileage, current_sources = (
                    fresh_state()
                )
                current_rows_by_title = {
                    "Transactions": current_transactions,
                    "Mileage": current_mileage,
                    "MixedUseExpenses": current_sources,
                }
                refreshed = [
                    self._managed_update_request(
                        title,
                        current_rows_by_title[title][
                            _clean_text(row.values.get("id"), "ID", required=True)
                        ],
                        "tag_ids",
                        expected_value,
                    )
                    for title, row, expected_value in update_rows.values()
                ]
                refreshed.extend(
                    self._managed_delete_request("Tags", current_tags[source_id])
                    for source_id in sorted(
                        source_ids,
                        key=lambda item: current_tags[item].row_number,
                        reverse=True,
                    )
                )
                requests[:] = refreshed

            self._managed_write(
                operation="tag merge",
                requests=requests,
                read_state=fresh_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses"),
            )
            return {"status": "fully_applied", "count": str(len(source_ids))}

    merge_tag = merge_tags

    def remove_tag(
        self,
        tag_id: str,
        *,
        expected_tag: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Permanently remove one tag only when no tagged row uses it."""
        tag_id = _clean_text(tag_id, "Tag", required=True)
        with _MIXED_USE_CREATE_LOCK, _TAG_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                force_refresh=True,
            )
            tag_rows = self._managed_rows_by_id(snapshot["Tags"], "Tags")
            if tag_id not in tag_rows:
                raise StorageNotFoundError("Tag no longer exists")
            expected_record = expected_tag or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {tag_id: dict(tag_rows[tag_id].values)}, expected_record
                )
            references = 0
            for row in (
                *snapshot["Transactions"],
                *snapshot["Mileage"],
                *snapshot["MixedUseExpenses"],
            ):
                raw_tags = row.values.get("tag_ids", "")
                if _raw_tag_ids_may_contain(
                    raw_tags, (tag_id,)
                ) and tag_id in _normalize_tag_ids(raw_tags):
                    references += 1
            if references:
                raise StorageConflictError(
                    f"This tag is referenced by {references} records. Merge it or unassign it first."
                )
            request = self._managed_delete_request("Tags", tag_rows[tag_id])
            def read_state() -> tuple[
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                )
            def references_present(state: Any) -> bool:
                _, current_transactions, current_mileage, current_sources = state
                return any(
                    tag_id in _normalize_tag_ids(row.values.get("tag_ids", ""))
                    for row in (
                        *current_transactions.values(),
                        *current_mileage.values(),
                        *current_sources.values(),
                    )
                )
            def is_gone(state: Any) -> bool:
                return tag_id not in state[0] and not references_present(state)
            def is_unchanged(state: Any) -> bool:
                return (
                    tag_id in state[0]
                    and state[0][tag_id].values == tag_rows[tag_id].values
                    and not references_present(state)
                )

            def refresh_request() -> None:
                nonlocal tag_rows, request
                tag_rows = read_state()[0]
                request = self._managed_delete_request("Tags", tag_rows[tag_id])

            requests = [request]
            def refresh_requests() -> None:
                refresh_request()
                requests[:] = [request]

            self._managed_write(
                operation="tag removal",
                requests=requests,
                read_state=read_state,
                applied=is_gone,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses"),
            )
            return {"status": "fully_applied"}

    delete_tag = remove_tag

    def _payee_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_payees(_force_refresh=force_refresh)}

    def _tag_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_tags(_force_refresh=force_refresh)}

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
    ) -> None:
        receipt_ids = {
            item["id"] for item in decode_receipt_references(references)
        }
        if not receipt_ids:
            return
        for transaction in self.list_transactions(_force_refresh=True):
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
        if not GoogleSheetsStorage._mixed_use_record_matches(
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

    def get_mixed_use_expense(self, source_id: str) -> dict[str, str]:
        source_id = _clean_text(source_id, "Mixed-use source ID", required=True)
        for source in self.list_mixed_use_expenses():
            if source["id"] == source_id:
                return source
        raise StorageNotFoundError("Mixed-use expense no longer exists")

    def resolve_mixed_use_expense(self, source_id: str) -> dict[str, str]:
        """Resolve one source record through its durable projection link."""
        return self.get_mixed_use_expense(source_id)

    def create_mixed_use_expense(self, **data: Any) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
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
            persisted_source = self._find_row("MixedUseExpenses", source_id)
            if not self._mixed_use_record_matches(
                "MixedUseExpenses", persisted_source.values, source
            ):
                raise StorageConflictError(
                    "The mixed-use source ID is already in use with different data"
                )
            self._append("Transactions", projection)
        except StorageConflictError:
            raise
        except (StorageError, OSError) as error:
            if isinstance(error, StorageUnavailableError):
                if not error.retryable:
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
                raise StorageUnavailableError(
                    _mutation_guidance("mixed-use create"), retryable=False
                ) from error
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
        with _MIXED_USE_CREATE_LOCK:
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

        self._write_with_confirmation(
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
        with _MIXED_USE_CREATE_LOCK:
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
            requests = [
                self._managed_delete_request("Transactions", fresh_transaction),
                self._managed_delete_request("MixedUseExpenses", fresh_source),
            ]

        self._write_with_confirmation(
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

        self._write_with_confirmation(
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
    ) -> dict[str, str]:
        """Replace the Drive receipt references attached to one transaction."""
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Transactions", transaction_id)
            self._reject_mixed_use_projection(current.values)
            encoded_references = _encode_receipt_references(references)
            self._reject_receipt_ownership_conflict(
                encoded_references, transaction_id=transaction_id
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

    def initialize_legacy_transaction_receipts(
        self,
        transaction_id: str,
        *,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            return self._initialize_legacy_transaction_receipts(
                transaction_id, references=references
            )

    def _initialize_legacy_transaction_receipts(
        self,
        transaction_id: str,
        *,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        """Populate one still-blank legacy receipt cell with rich references."""
        current = self._find_row("Transactions", transaction_id)
        self._reject_mixed_use_projection(current.values)
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
        if str(current.values.get("receipt_references", "")) != "":
            raise StorageConflictError(
                "The transaction receipt references are already initialized"
            )
        return self._replace_receipt_references(
            current, _encode_receipt_references(normalized)
        )

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

            self._write_with_confirmation(
                "transaction deletion", write, state, before_retry=refresh,
                invalidate=("Transactions",),
            )

    def _prepare_mileage_trip(
        self,
        data: Mapping[str, Any],
        *,
        trip_id: str | None = None,
        created_at: str | None = None,
        original_tag_ids: Any = "",
        tags: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict[str, str]:
        trip_date = _iso_date(data.get("trip_date"))
        miles = _positive_miles(data.get("miles"))
        vehicle = _clean_text(data.get("vehicle"), "Vehicle")
        start_location = _clean_text(
            data.get("start_location"), "Starting location", required=True
        )
        destination = _clean_text(
            data.get("destination"), "Destination", required=True
        )
        business_purpose = _clean_text(
            data.get("business_purpose"), "Business purpose", required=True
        )
        notes = _clean_text(data.get("notes"), "Notes")
        tags = dict(tags) if tags is not None else self._tag_lookup(force_refresh=True)
        tag_ids = _normalize_tag_ids(data.get("tag_ids", ""))
        original_tag_ids = _normalize_tag_ids(original_tag_ids)
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
                raise StorageValidationError("Tag is inactive")
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
        return {
            "id": trip_id or str(uuid4()),
            "trip_date": trip_date,
            "miles": miles,
            "vehicle": vehicle,
            "start_location": start_location,
            "destination": destination,
            "business_purpose": business_purpose,
            "notes": notes,
            "tag_ids": _encode_tag_ids(tag_ids),
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
        trip_ids: set[str] = set()
        tags = self._tag_lookup(force_refresh=_force_refresh)
        for row in self._rows("Mileage", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Mileage ID", required=True)
            if item["id"] in trip_ids:
                raise StorageValidationError("Mileage IDs must be unique")
            trip_ids.add(item["id"])
            item["trip_date"] = _iso_date(item.get("trip_date"))
            item["miles"] = _positive_miles(item.get("miles"))
            item["vehicle"] = _clean_text(item.get("vehicle"), "Vehicle")
            item["start_location"] = _clean_text(
                item.get("start_location"), "Starting location", required=True
            )
            item["destination"] = _clean_text(
                item.get("destination"), "Destination", required=True
            )
            item["business_purpose"] = _clean_text(
                item.get("business_purpose"), "Business purpose", required=True
            )
            item["notes"] = _clean_text(item.get("notes"), "Notes")
            if start_text and item["trip_date"] < start_text:
                continue
            if end_text and item["trip_date"] > end_text:
                continue
            normalized_tag_ids = _normalize_tag_ids(item.get("tag_ids", ""))
            if any(tag_id not in tags for tag_id in normalized_tag_ids):
                raise StorageValidationError("Tag does not exist")
            item["tag_ids"] = normalized_tag_ids
            item["tags"] = [tags[tag_id]["name"] for tag_id in normalized_tag_ids]
            trips.append(item)
        return sorted(
            trips,
            # Python's sort is stable, so same-timestamp rows retain the
            # worksheet insertion order. New round-trip writes intentionally
            # put the reversed return leg before outbound.
            key=lambda item: (item["trip_date"], item["created_at"]),
            reverse=True,
        )

    def create_mileage_trip(self, **data: Any) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
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
        with _MIXED_USE_CREATE_LOCK:
            created_at = _utc_now()
            new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
            prepared_data = dict(data)
            prepared_data["new_tag_name"] = ""
            outbound = self._prepare_mileage_trip(
                prepared_data,
                created_at=created_at,
            )
            return_data = dict(prepared_data)
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
            if new_tag_name:
                new_tag = self.create_tag(new_tag_name)
                for trip in (outbound, return_trip):
                    tag_ids = _normalize_tag_ids(trip["tag_ids"])
                    if new_tag["id"] not in tag_ids:
                        tag_ids.append(new_tag["id"])
                    trip["tag_ids"] = _encode_tag_ids(tag_ids)
            # Keep the public return value in semantic outbound/return order, but
            # write the rows in the order the log should display for a new pair.
            # Existing rows are not rewritten or migrated.
            records = [outbound, return_trip]
            self._append_many("Mileage", [return_trip, outbound])
            return records

    def edit_mileage_trip(self, trip_id: str, **changes: Any) -> dict[str, str]:
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Mileage", trip_id)
            merged = dict(current.values)
            merged.update(changes)
            updated = self._prepare_mileage_trip(
                merged,
                trip_id=trip_id,
                created_at=current.values["created_at"],
                original_tag_ids=current.values.get("tag_ids", ""),
            )
            self._replace_row("Mileage", current, updated)
            return updated

    def delete_mileage_trip(self, trip_id: str) -> None:
        with _MIXED_USE_CREATE_LOCK:
            current = self._find_row("Mileage", trip_id)
            original = dict(current.values)
            current_row = current
            worksheet = self._worksheet("Mileage")

            def write() -> None:
                self._api(
                    lambda: worksheet.delete_rows(current_row.row_number),
                    retry_safe=False,
                )

            def state() -> str:
                try:
                    latest = self._find_row("Mileage", trip_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh() -> None:
                nonlocal current_row
                current_row = self._find_row("Mileage", trip_id)
                if current_row.values != original:
                    raise StorageConflictError(
                        "The mileage trip changed while deletion was being retried."
                    )

            self._write_with_confirmation(
                "mileage deletion", write, state, before_retry=refresh,
                invalidate=("Mileage",),
            )

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

    @_active_ledger_mutation_lock
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
        tags = self._tag_lookup()
        prepared = [
            self._prepare_mileage_trip(item, tags=tags) for item in preview["rows"]
        ]
        self._append_many("Mileage", prepared)
        return prepared

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

    def export_backup_zip(self, receipt_manifest: Mapping[str, Any]) -> bytes:
        """Return a fresh, checksummed backup of every ledger worksheet."""
        generated_at = _utc_now()
        row_counts: dict[str, int] = {}
        worksheet_headers: dict[str, list[str]] = {}
        csv_files: dict[str, bytes] = {}
        archive_buffer = io.BytesIO()
        snapshot = self._snapshot(WORKSHEET_HEADERS, force_refresh=True)
        _validate_mixed_use_tables(
            {
                title: (WORKSHEET_HEADERS[title], [dict(row.values) for row in rows])
                for title, rows in snapshot.items()
            }
        )
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
        payees = self._payee_lookup(force_refresh=True)
        for row in snapshot["MixedUseExpenses"]:
            self._validate_mixed_use_references(
                row.values,
                accounts=accounts,
                categories=categories,
                payees=payees,
            )
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
        tag_records = [dict(row.values) for row in snapshot["Tags"]]
        for tag in tag_records:
            tag["id"] = _clean_text(tag.get("id"), "Tag ID", required=True)
            tag["name"] = _clean_text(tag.get("name"), "Tag name", required=True)
            tag["active"] = (
                "TRUE" if _as_bool(tag.get("active"), "Tag active") else "FALSE"
            )
        _validate_tag_records(tag_records)
        known_tag_ids = {tag["id"] for tag in tag_records}
        for title in WORKSHEET_HEADERS:
            headers = self._headers(title)
            rows = snapshot[title]
            row_counts[title] = len(rows)
            worksheet_headers[title] = headers
            csv_buffer = io.StringIO(newline="")
            writer = csv.writer(csv_buffer, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                values = dict(row.values)
                if title in {"Transactions", "Mileage", "MixedUseExpenses"}:
                    normalized_tag_ids = _normalize_tag_ids(values.get("tag_ids", ""))
                    if any(tag_id not in known_tag_ids for tag_id in normalized_tag_ids):
                        item_label = {
                            "Transactions": "transaction",
                            "Mileage": "mileage",
                            "MixedUseExpenses": "mixed-use source",
                        }[title]
                        raise StorageValidationError(
                            "Backup contains an unknown "
                            f"{item_label} tag"
                        )
                    values["tag_ids"] = _encode_tag_ids(normalized_tag_ids)
                elif title == "Tags":
                    record_id = _clean_text(values.get("id"), "Tag ID", required=True)
                    tag = next(item for item in tag_records if item["id"] == record_id)
                    values = tag
                writer.writerow([values.get(header, "") for header in headers])
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
        manifest, tables, _ = _parse_backup_zip(backup)
        for title in WORKSHEET_HEADERS:
            target_headers = self._headers(title)
            if set(target_headers) != set(tables[title][0]):
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
            if title == "MixedUseExpenses" and not records:
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
