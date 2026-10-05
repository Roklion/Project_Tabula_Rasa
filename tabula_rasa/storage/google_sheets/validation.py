"""Pure validation and serialization helpers for Sheets storage."""

from __future__ import annotations

from tabula_rasa.mixed_use_records import mixed_use_ledger_description as mixed_use_ledger_description, validate_mixed_use_records

import csv
import hashlib
import io
import json
import zipfile
from tabula_rasa.ledger_validation import encode_tag_ids as _encode_tag_ids
from tabula_rasa.ledger_validation import positive_integer as _positive_integer
from tabula_rasa.ledger_validation import validate_recurring_provenance as _validate_recurring_provenance
from tabula_rasa.ledger_validation import validate_unique_recurring_occurrences as _validate_unique_recurring_occurrences
from collections.abc import Iterable
from collections.abc import Mapping
from datetime import date
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any
from tabula_rasa.ledger_validation import (
    iso_date as _iso_date, positive_amount as _positive_amount, decode_receipt_references,
)
from tabula_rasa.journal import JournalValidationError, normalize_journal_postings
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.mixed_use import MixedUseAllocationError
from tabula_rasa.mixed_use import validate_mixed_use_allocation
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.receipt_manifest import validate_receipt_manifest
from tabula_rasa.reference_data import (
    as_bool as _as_bool,
    balance_amount as _balance_amount,
    clean_text as _clean_text,
    normalize_payee_name,
    normalize_tag_ids as _normalize_tag_ids,
    normalize_tag_name,
    validate_account_classification as _validate_account_classification,
    validate_hierarchy_records as _validate_hierarchy_records,
)
from .schema import (
    BACKUP_FORMAT_VERSION,
    WORKSHEET_HEADERS,
    validate_worksheet_headers,
)
from .errors import (
    StorageValidationError,
)

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

def _encode_receipt_references(value: Any) -> str:
    references = decode_receipt_references(value)
    return json.dumps(references, separators=(",", ":"), ensure_ascii=False)

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






def _positive_miles(value: Any) -> str:
    try:
        miles = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Miles must be numeric") from None
    if not miles.is_finite() or miles <= 0:
        raise StorageValidationError("Miles must be greater than zero")
    return format(miles.quantize(Decimal("0.1")), "f")

def _validate_journal_tables(
    entries: Iterable[Mapping[str, Any]],
    postings: Iterable[Mapping[str, Any]],
    *,
    account_ids: Iterable[str],
    category_ids: Iterable[str],
    payee_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Validate journal structure and references, returning complete entries."""
    known_accounts = {str(value).strip() for value in account_ids}
    known_categories = {str(value).strip() for value in category_ids}
    known_payees = {str(value).strip() for value in payee_ids}
    entries_by_id: dict[str, dict[str, Any]] = {}
    for source in entries:
        entry = dict(source)
        entry_id = _clean_text(entry.get("id"), "Journal entry ID", required=True)
        if entry_id in entries_by_id:
            raise StorageValidationError("Journal entry IDs must be unique")
        entry["id"] = entry_id
        entry["txn_date"] = _iso_date(entry.get("txn_date"))
        entry["description"] = _clean_text(
            entry.get("description"), "Journal description"
        )
        entry["created_at"] = _clean_text(
            entry.get("created_at"), "Journal created time", required=True
        )
        entry["updated_at"] = _clean_text(
            entry.get("updated_at"), "Journal updated time", required=True
        )
        entries_by_id[entry_id] = entry

    posting_ids: set[str] = set()
    grouped: dict[str, list[dict[str, Any]]] = {
        entry_id: [] for entry_id in entries_by_id
    }
    for source in postings:
        posting = dict(source)
        posting_id = _clean_text(
            posting.get("id"), "Journal posting ID", required=True
        )
        if posting_id in posting_ids:
            raise StorageValidationError("Journal posting IDs must be unique")
        posting_ids.add(posting_id)
        parent_id = _clean_text(
            posting.get("parent_entry_id"),
            "Journal parent entry ID",
            required=True,
        )
        if parent_id not in entries_by_id:
            raise StorageValidationError(
                "Journal posting references an unknown parent entry"
            )
        posting["id"] = posting_id
        posting["parent_entry_id"] = parent_id
        posting["position"] = _positive_integer(
            posting.get("position"), "Journal posting position"
        )
        grouped[parent_id].append(posting)

    complete: list[dict[str, Any]] = []
    for entry_id, entry in entries_by_id.items():
        source_postings = sorted(
            grouped[entry_id], key=lambda posting: posting["position"]
        )
        positions = [posting["position"] for posting in source_postings]
        if positions != list(range(1, len(source_postings) + 1)):
            raise StorageValidationError(
                "Journal posting positions must be unique and contiguous from 1"
            )
        try:
            canonical_postings = normalize_journal_postings(source_postings)
        except JournalValidationError as exc:
            raise StorageValidationError(str(exc)) from exc
        for source_posting, posting in zip(source_postings, canonical_postings):
            posting["parent_entry_id"] = entry_id
            target_id = posting["target_id"]
            if posting["target_type"] == "account":
                if target_id not in known_accounts:
                    raise StorageValidationError(
                        "Journal posting references an unknown account"
                    )
            elif target_id not in known_categories:
                raise StorageValidationError(
                    "Journal posting references an unknown category"
                )
            payee_id = posting["payee_id"]
            if payee_id and payee_id not in known_payees:
                raise StorageValidationError(
                    "Journal posting references an unknown payee"
                )
            if any(
                str(source_posting.get(field, "") or "").strip()
                != str(posting.get(field, "") or "")
                for field in (
                    "id",
                    "target_type",
                    "target_id",
                    "side",
                    "amount",
                    "payee_id",
                    "description",
                )
            ):
                raise StorageValidationError(
                    "Journal posting values are not in canonical form"
                )
        debits = sum(
            Decimal(posting["amount"])
            for posting in canonical_postings
            if posting["side"] == "Debit"
        )
        credits = sum(
            Decimal(posting["amount"])
            for posting in canonical_postings
            if posting["side"] == "Credit"
        )
        complete.append(
            {
                **entry,
                "postings": canonical_postings,
                "total_debits": format(debits, "f"),
                "total_credits": format(credits, "f"),
            }
        )
    return complete


def _validate_mixed_use_tables(tables):
    return validate_mixed_use_records(tables.get("MixedUseExpenses", ((), []))[1], tables.get("Transactions", ((), []))[1])

def _parse_backup_zip(
    backup: bytes,
) -> tuple[
    dict[str, Any],
    dict[str, tuple[list[str], list[dict[str, str]]]],
    dict[str, Any],
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
            if type(format_version) is not int or format_version != BACKUP_FORMAT_VERSION:
                raise StorageValidationError(
                    "Only backup format 13 is supported. Historical archive conversion "
                    "is retired; preserve this file and select a format-13 backup."
                )
            try:
                backup_time = datetime.fromisoformat(manifest["backup_time"])
            except (KeyError, TypeError, ValueError) as exc:
                raise StorageValidationError("Backup time must be a UTC timestamp") from exc
            if backup_time.utcoffset() != timezone.utc.utcoffset(backup_time):
                raise StorageValidationError("Backup time must be a UTC timestamp")
            if not isinstance(manifest.get("workbook_title"), str) or not manifest["workbook_title"].strip():
                raise StorageValidationError("Backup workbook title is missing or invalid")
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
    if set(row_counts) != set(backup_headers) or set(worksheet_headers) != set(backup_headers):
        raise StorageValidationError("Backup manifest worksheet entries are invalid")
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
        validate_worksheet_headers(title, headers)
        if worksheet_headers.get(title) != headers:
            raise StorageValidationError(f"{title} backup headers are invalid")
        records: list[dict[str, str]] = []
        for raw_row in parsed_rows[1:]:
            if len(raw_row) > len(headers):
                raise StorageValidationError(f"{title} backup has an over-wide row")
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            if any(value.strip() for value in padded):
                records.append(dict(zip(headers, padded)))
        if type(row_counts.get(title)) is not int or row_counts[title] != len(records):
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
    category_records = {
        record["id"]: record for record in tables["Categories"][1]
    }
    category_ids = set(category_records)
    payee_ids = {record["id"] for record in tables["Payees"][1]}
    tag_ids = {record["id"] for record in tables["Tags"][1]}
    _validate_journal_tables(
        tables["JournalEntries"][1],
        tables["JournalPostings"][1],
        account_ids=account_ids,
        category_ids=category_ids,
        payee_ids=payee_ids,
    )
    schedule_records = tables["RecurringSchedules"][1]
    schedule_ids = [record.get("id", "") for record in schedule_records]
    if any(
        not schedule_id
        or str(schedule_id) != str(schedule_id).strip()
        for schedule_id in schedule_ids
    ) or len(schedule_ids) != len(set(schedule_ids)):
        raise StorageValidationError("Backup contains missing or duplicated recurring schedule IDs")
    schedules = {record["id"]: record for record in schedule_records}
    for schedule in schedules.values():
        _clean_text(schedule.get("name"), "Schedule name", required=True)
        if schedule.get("kind") != "Expense":
            raise StorageValidationError("Recurring schedules must be Expense records")
        if schedule.get("source_kind", "transaction") not in {"transaction", "mixed_use"}:
            raise StorageValidationError("Recurring schedule source kind is invalid")
        if schedule.get("recurrence_unit") not in {"day", "week", "month", "year"}:
            raise StorageValidationError("Recurring schedule unit is invalid")
        _positive_integer(
            schedule.get("recurrence_interval"),
            "Recurring schedule interval",
        )
        if schedule.get("status") not in {"active", "paused", "ended"}:
            raise StorageValidationError("Recurring schedule status is invalid")
        start_date = _iso_date(schedule.get("start_date"))
        anchor_date = _iso_date(schedule.get("anchor_date"))
        end_date = _clean_text(schedule.get("end_date"), "Schedule end date")
        if end_date:
            end_date = _iso_date(end_date)
        if anchor_date != start_date or (end_date and end_date < start_date and schedule.get("status") != "ended"):
            raise StorageValidationError("Recurring schedule dates are invalid")
        if (
            schedule.get("account_id") not in account_ids
            or schedule.get("category_id") not in category_ids
            or category_records[schedule["category_id"]].get("kind") != "Expense"
        ):
            raise StorageValidationError("Recurring schedule references an unknown account or category")
        payee_id = schedule.get("payee_id", "")
        if payee_id and payee_id not in payee_ids:
            raise StorageValidationError("Recurring schedule references an unknown payee")
        if schedule.get("receipt_references", ""):
            raise StorageValidationError("Recurring schedules cannot contain receipts")
        schedule_tags = _normalize_tag_ids(schedule.get("tag_ids", ""))
        if any(tag_id not in tag_ids for tag_id in schedule_tags):
            raise StorageValidationError("Recurring schedule references an unknown tag")
        if schedule.get("source_kind", "transaction") == "transaction":
            _positive_amount(schedule.get("amount"))
        else:
            try:
                allocation = validate_mixed_use_allocation(
                    schedule.get("total_expense"),
                    schedule.get("business_use_percentage"),
                )
            except MixedUseAllocationError as exc:
                raise StorageValidationError(str(exc)) from exc
            if not _decimal_values_match(schedule.get("amount"), allocation.allocated_amount):
                raise StorageValidationError("Recurring mixed-use allocation is invalid")
            _clean_text(schedule.get("allocation_rationale"), "Allocation rationale", required=True)
    for title in ("Transactions", "Mileage", "MixedUseExpenses", "Assets"):
        if title not in tables:
            continue
        for record in tables[title][1]:
            normalized_tag_ids = _normalize_tag_ids(record.get("tag_ids", ""))
            if any(tag_id not in tag_ids for tag_id in normalized_tag_ids):
                item_label = {
                    "Transactions": "transaction",
                    "Mileage": "mileage",
                    "MixedUseExpenses": "mixed-use source",
                    "Assets": "asset",
                }[title]
                raise StorageValidationError(
                    "Backup contains an unknown "
                    f"{item_label} tag"
                )
            record["tag_ids"] = _encode_tag_ids(normalized_tag_ids)
    from tabula_rasa.depreciation import DepreciationError, straight_line_schedule
    from .assets import ASSET_TYPES, AssetsMixin, _decode_overrides, _whole_quarters

    for asset in tables["Assets"][1]:
        _clean_text(asset.get("name"), "Asset name", required=True)
        _clean_text(asset.get("created_at"), "Asset created time", required=True)
        _clean_text(asset.get("updated_at"), "Asset updated time", required=True)
        if asset.get("asset_type") not in ASSET_TYPES:
            raise StorageValidationError("Backup contains an unknown asset type")
        acquisition_date = _iso_date(asset.get("acquisition_date"))
        start_date = _iso_date(asset.get("depreciation_start_date"))
        if start_date < acquisition_date:
            raise StorageValidationError("Backup contains invalid asset dates")
        if asset.get("depreciation_method") != "Straight-line":
            raise StorageValidationError("Backup contains an unsupported depreciation method")
        if asset.get("status") not in {"active", "retired"}:
            raise StorageValidationError("Backup contains an invalid asset status")
        retired_text = _clean_text(asset.get("retired_date"), "Retired date")
        retired = date.fromisoformat(_iso_date(retired_text)) if retired_text else None
        if (asset.get("status") == "retired") != bool(retired):
            raise StorageValidationError("Backup contains inconsistent asset retirement state")
        if retired is not None and retired < date.fromisoformat(acquisition_date):
            raise StorageValidationError("Backup contains invalid asset dates")
        payee_id = _clean_text(asset.get("payee_id"), "Payee")
        if payee_id and payee_id not in payee_ids:
            raise StorageValidationError("Backup contains an unknown asset payee")
        _clean_text(
            asset.get("source_transaction_id"), "Source transaction"
        )
        # Missing historical source transactions are allowed by the asset model.
        try:
            quarters = _whole_quarters(asset.get("useful_life_quarters"))
            straight_line_schedule(
                asset.get("cost_basis"),
                asset.get("salvage_value"),
                date.fromisoformat(start_date),
                quarters,
                retired_date=retired,
                overrides=_decode_overrides(asset.get("schedule_overrides", "")),
            )
        except (DepreciationError, StorageValidationError, ValueError) as exc:
            raise StorageValidationError(f"Backup contains an invalid asset: {exc}") from exc
        normalized_asset = AssetsMixin._prepare_asset(
            asset,
            asset_id=_clean_text(asset.get("id"), "Asset ID", required=True),
            created_at=_clean_text(
                asset.get("created_at"), "Asset created time", required=True
            ),
        )
        normalized_asset["updated_at"] = _clean_text(
            asset.get("updated_at"), "Asset updated time", required=True
        )
        asset.update(normalized_asset)
    from .depreciation_posting import validate_depreciation_accounts, validate_depreciation_history
    backup_accounts = {row["id"]: row for row in tables["Accounts"][1]}
    for asset in tables["Assets"][1]:
        validate_depreciation_accounts(asset, backup_accounts, category_records)
    validate_depreciation_history(tables["Assets"][1], tables["Transactions"][1],
                                  backup_accounts, category_records)
    for transaction in tables["Transactions"][1]:
        _validate_recurring_provenance(transaction, "Transaction")
        recurring_id = transaction.get("recurring_schedule_id", "")
        if recurring_id:
            if transaction.get("kind") != "Expense":
                raise StorageValidationError("Recurring transaction must be an Expense")
            if recurring_id not in schedules:
                raise StorageValidationError("Transaction references an unknown recurring schedule")
            _iso_date(transaction.get("recurring_scheduled_date"))
            expected_source_kind = (
                "mixed_use"
                if transaction.get("source_type") == MIXED_USE_SOURCE_TYPE
                and transaction.get("source_id")
                else "transaction"
            )
            if (
                transaction.get("recurring_source_kind") != expected_source_kind
                or schedules[recurring_id].get("source_kind") != expected_source_kind
            ):
                raise StorageValidationError("Transaction recurring source kind is invalid")
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
        decode_receipt_references(transaction.get("receipt_references", ""))
    _validate_unique_recurring_occurrences(tables["Transactions"][1], "Transactions")
    for source in tables["MixedUseExpenses"][1]:
        _validate_recurring_provenance(source, "Mixed-use source")
        recurring_id = source.get("recurring_schedule_id", "")
        if recurring_id:
            if recurring_id not in schedules:
                raise StorageValidationError("Mixed-use source references an unknown recurring schedule")
            if source.get("recurring_occurrence_type") not in {"initial", "generated"}:
                raise StorageValidationError("Mixed-use recurring occurrence type is invalid")
            if (
                source.get("recurring_source_kind") != "mixed_use"
                or schedules[recurring_id].get("source_kind") != "mixed_use"
            ):
                raise StorageValidationError("Mixed-use recurring source kind is invalid")
            _iso_date(source.get("recurring_scheduled_date"))
    _validate_unique_recurring_occurrences(
        tables["MixedUseExpenses"][1], "Mixed-use expenses"
    )

    for source in tables["MixedUseExpenses"][1]:
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
    "_looks_like_partial_blank_workbook",
    "_utc_now",
    "_clean_text",
    "_validate_hierarchy_records",
    "_validate_payee_records",
    "_validate_journal_tables",
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
