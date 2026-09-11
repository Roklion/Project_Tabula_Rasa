"""Pure validation and serialization helpers for Sheets storage."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import unicodedata
import zipfile
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from tabula_rasa.hierarchy import HierarchyValidationError
from tabula_rasa.hierarchy import validate_two_level_hierarchy
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.mixed_use import MixedUseAllocationError
from tabula_rasa.mixed_use import validate_mixed_use_allocation
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.receipt_manifest import decode_receipt_reference_list
from tabula_rasa.receipt_manifest import validate_receipt_manifest
from .schema import (
    ACCOUNT_CLASSIFICATIONS,
    BACKUP_FORMAT_VERSION,
    FIXED_TYPE_CLASSIFICATIONS,
    MIXED_USE_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageValidationError,
)

def _looks_like_historical_workbook(
    values: Mapping[str, list[list[Any]]],
) -> bool:
    """Return whether a workbook has a recognizable migration-only marker.

    The detailed historical layouts belong to ``scripts.migration_schemas``.
    Runtime needs only the small set of stable markers required to direct an
    older workbook to the explicit migration command.
    """
    present_titles = set(values)
    if "RecurringSchedules" not in present_titles and (
        "Transactions" in present_titles
        or any(
            str(value).strip()
            for row in values.get("MixedUseExpenses", [])
            for value in row
        )
    ):
        return True
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
        if title == "Transactions" and len(headers) == len(set(headers)):
            header_set = set(headers)
            if "payee" in header_set:
                return True
            if (
                "MixedUseExpenses" not in present_titles
                and header_set != set(WORKSHEET_HEADERS["Transactions"])
                and {"payee_id", "source_type", "source_id", "tag_ids"}
                <= header_set
            ):
                # The explicit migration updates Transactions before Mileage;
                # preserve the historical marker if startup observes that
                # supported intermediate layout after an interrupted run.
                return True
            if (
                "MixedUseExpenses" not in present_titles
                and "payee_id" in header_set
                and "source_type" not in header_set
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
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_occurrence_type",
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
    schedules = {record["id"]: record for record in tables["RecurringSchedules"][1]}
    for schedule in schedules.values():
        if schedule.get("kind") != "Expense":
            raise StorageValidationError("Recurring schedules must be Expense records")
        if schedule.get("expense_type", "ordinary") not in {"ordinary", "mixed_use"}:
            raise StorageValidationError("Recurring schedule expense type is invalid")
        if schedule.get("account_id") not in account_ids or schedule.get("category_id") not in category_ids:
            raise StorageValidationError("Recurring schedule references an unknown account or category")
        payee_id = schedule.get("payee_id", "")
        if payee_id and payee_id not in payee_ids:
            raise StorageValidationError("Recurring schedule references an unknown payee")
        if schedule.get("receipt_references", ""):
            raise StorageValidationError("Recurring schedules cannot contain receipts")
        _normalize_tag_ids(schedule.get("tag_ids", ""))
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
        recurring_id = transaction.get("recurring_schedule_id", "")
        if recurring_id:
            if recurring_id not in schedules:
                raise StorageValidationError("Transaction references an unknown recurring schedule")
            _iso_date(transaction.get("recurring_scheduled_date"))
            if transaction.get("recurring_occurrence_type") not in {"initial", "generated"}:
                raise StorageValidationError("Transaction recurring occurrence type is invalid")
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
    for source in tables["MixedUseExpenses"][1]:
        recurring_id = source.get("recurring_schedule_id", "")
        if recurring_id:
            if recurring_id not in schedules:
                raise StorageValidationError("Mixed-use source references an unknown recurring schedule")
            if source.get("recurring_occurrence_type") not in {"initial", "generated"}:
                raise StorageValidationError("Mixed-use recurring occurrence type is invalid")
            _iso_date(source.get("recurring_scheduled_date"))

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

__all__ = [
    "decode_receipt_references",
    "normalize_payee_name",
    "normalize_tag_name",
    "mixed_use_ledger_description",
    "_looks_like_historical_workbook",
    "_looks_like_partial_blank_workbook",
    "_utc_now",
    "_clean_text",
    "_validate_hierarchy_records",
    "_validate_payee_records",
    "_decimal_values_match",
    "_encode_receipt_references",
    "_normalize_tag_ids",
    "_raw_tag_ids_may_contain",
    "_managed_comparison_text",
    "_encode_tag_ids",
    "_validate_tag_records",
    "_positive_amount",
    "_positive_miles",
    "_balance_amount",
    "_validate_account_classification",
    "_iso_date",
    "_as_bool",
    "_validate_mixed_use_tables",
    "_parse_backup_zip",
]
