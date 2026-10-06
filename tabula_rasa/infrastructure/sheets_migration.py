"""Read-only live format-13 extraction and independent domain preflight."""

from datetime import datetime, timezone
from decimal import Decimal
import json

from tabula_rasa.errors import StorageValidationError
from tabula_rasa.ledger_validation import iso_date, decode_receipt_references
from tabula_rasa.reference_data import (
    ACCOUNT_TYPES, as_bool, balance_amount, clean_text, normalize_payee_name,
    normalize_tag_name, validate_account_classification,
)
from tabula_rasa.storage.google_sheets.schema import (
    WORKSHEET_HEADERS, validate_workbook_headers,
)
from tabula_rasa.storage.google_sheets.validation import (
    _positive_miles, validate_source_tables,
)
from tabula_rasa.transaction import prepare_transaction
from tabula_rasa.recurring import schedule_template
from tabula_rasa.recurrence import occurrence_id

from tabula_rasa.migration.model import Binding, MigrationError, Snapshot


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StorageValidationError("A timestamp must have a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _raise_safe(message):
    # Do not retain a domain/provider error that might contain private values.
    try:
        raise MigrationError(message) from None
    except MigrationError as error:
        error.__context__ = None
        raise


def _no_inline(_):
    raise StorageValidationError("Migration cannot create inline references.")


def _normalize_record(title, row, lookups):
    for field in ("created_at", "updated_at", "attention_at"):
        if field in row and row[field]:
            row[field] = timestamp(row[field])
        elif field in row and field != "attention_at":
            raise StorageValidationError("Required timestamp is absent.")
    if title in {"Accounts", "Categories", "Payees", "Tags", "Assets", "RecurringSchedules"}:
        row["name"] = clean_text(row["name"], "Name", required=True)
    if title in {"Accounts", "Payees", "Tags"}:
        row["active"] = "TRUE" if as_bool(row["active"]) else "FALSE"
    if title == "Accounts":
        if row["type"] not in ACCOUNT_TYPES:
            raise StorageValidationError("Invalid account type.")
        validate_account_classification(row["type"], row["classification"])
        row["opening_balance"] = balance_amount(row["opening_balance"])
    elif title == "Categories" and row["kind"] not in {"Income", "Expense"}:
        raise StorageValidationError("Invalid category kind.")
    elif title == "Transactions":
        source = row["source_type"]
        if bool(source) != bool(row["source_id"]) or source not in {"", "mixed_use_expense", "depreciation"}:
            raise StorageValidationError("Invalid source ownership.")
        if row["kind"] == "Transfer" and row["category_id"]:
            raise StorageValidationError("Transfer category would be discarded.")
        original = dict(row)
        if source == "depreciation":
            original.update(source_type="", source_id="")
        prepared = prepare_transaction(
            row, transaction_id=row["id"], created_at=row["created_at"],
            accounts=lookups["Accounts"], categories=lookups["Categories"],
            payees=lookups["Payees"], tags=lookups["Tags"],
            create_payee=_no_inline, create_tag=_no_inline,
            original_transaction=original, allow_zero_amount=source == "depreciation",
        )
        row["amount"] = prepared["amount"]
        row["txn_date"] = prepared["txn_date"]
    elif title == "Mileage":
        row["trip_date"] = iso_date(row["trip_date"])
        row["miles"] = _positive_miles(row["miles"])
    elif title == "RecurringSchedules":
        if row["source_kind"] == "transaction" and (row["total_expense"] or row["business_use_percentage"] or row["allocation_rationale"]):
            raise StorageValidationError("Ordinary schedule contains mixed-use fields.")
        row.update(schedule_template(row, schedule_id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"],
                                     account_lookup=lookups["Accounts"], category_lookup=lookups["Categories"],
                                     payee_lookup=lookups["Payees"], tag_lookup=lookups["Tags"]))


def snapshot_from_values(binding: Binding, values, *, extracted_at=None):
    """Validate raw live worksheet values without source or target mutation.

    Header sets identify the live workbook version. Archives are not inputs.
    Source editing/jobs must be paused by the operator while extracting.
    """
    headers = {}
    for title in WORKSHEET_HEADERS:
        raw = values.get(title, [])
        headers[title] = [str(value).strip() for value in raw[0]] if raw else []
    try:
        validate_workbook_headers(headers)
    except StorageValidationError:
        _raise_safe("Unsupported workbook schema: only frozen format 13 is supported; preserve the source.")
    tables = {}
    positions = {}
    for title, fields in headers.items():
        records = []
        positions[title] = []
        seen = set()
        for position, raw in enumerate(values[title][1:], 2):
            if not any(str(value).strip() for value in raw):
                continue
            if len(raw) > len(fields):
                raise MigrationError(f"{title} row {position}: data extends beyond the source headers.")
            if any(not isinstance(value, str) for value in raw):
                raise MigrationError(f"{title} row {position}: extraction requires text cells.")
            row = dict(zip(fields, [*raw, *[""] * (len(fields) - len(raw))]))
            identity = row["id"]
            if not identity or identity != identity.strip() or identity in seen:
                raise MigrationError(f"{title} row {position}: missing, padded or duplicate identity.")
            seen.add(identity)
            records.append(row)
            positions[title].append(position)
        tables[title] = (fields, records)
    lookups = {title: {row["id"]: row for row in tables[title][1]} for title in WORKSHEET_HEADERS}
    for title, (_, rows) in tables.items():
        keys = set()
        for position, row in zip(positions[title], rows):
            try:
                _normalize_record(title, row, lookups)
                if title in {"Accounts", "Categories", "Payees", "Tags"}:
                    normalizer = normalize_payee_name if title == "Payees" else normalize_tag_name if title == "Tags" else str.casefold
                    key = (row.get("kind", ""), normalizer(row["name"]))
                    if key in keys:
                        raise StorageValidationError("Duplicate normalized name.")
                    keys.add(key)
            except (StorageValidationError, ValueError, TypeError, ArithmeticError):
                _raise_safe(f"{title} row {position}: invalid domain or reference fields; inspect the source privately.")
    try:
        validate_source_tables(tables)
        # Decode every receipt cell, including owners with no current projection.
        for title in ("Transactions", "MixedUseExpenses"):
            for row in tables[title][1]:
                decode_receipt_references(row["receipt_references"])
                if row["recurring_occurrence_type"] == "generated":
                    role = "generated"
                    if row["recurring_source_kind"] == "mixed_use":
                        role += "-source" if title == "MixedUseExpenses" else "-projection"
                    if row["id"] != occurrence_id(row["recurring_schedule_id"], row["recurring_scheduled_date"], role):
                        raise StorageValidationError("Generated occurrence identity differs from its provenance.")
        # Canonical PostgreSQL numeric limits are part of target preflight.
        for _, rows in tables.values():
            for row in rows:
                for field in ("amount", "opening_balance", "total_expense", "allocated_amount", "cost_basis", "salvage_value"):
                    if row.get(field) and abs(Decimal(row[field])) >= Decimal("1e26"):
                        raise StorageValidationError("Amount exceeds target precision.")
    except (StorageValidationError, ValueError, TypeError, ArithmeticError):
        _raise_safe("Source domain/reference/provenance relationships are invalid; inspect the source privately.")
    when = extracted_at or datetime.now(timezone.utc).isoformat()
    try:
        when = timestamp(when)
    except (ValueError, TypeError, AttributeError, StorageValidationError):
        _raise_safe("Extraction time must be an explicit timestamp.")
    content = json.dumps({title: sorted(rows, key=lambda row: row["id"])
                          for title, (_, rows) in tables.items()}, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return Snapshot(binding, when, content)


def extract_workbook(workbook, binding: Binding, *, extracted_at=None):
    """Dedicated read-only adapter: it has no initialization/mutation path."""
    if str(workbook.id) != binding.workbook_key:
        raise MigrationError("The source workbook does not match the explicit binding.")
    try:
        sheets = {sheet.title: sheet for sheet in workbook.worksheets()}
        values = {title: sheets[title].get_all_values() for title in WORKSHEET_HEADERS if title in sheets}
    except Exception:
        _raise_safe("Source workbook extraction failed; no migration writes were attempted.")
    return snapshot_from_values(binding, values, extracted_at=extracted_at)
