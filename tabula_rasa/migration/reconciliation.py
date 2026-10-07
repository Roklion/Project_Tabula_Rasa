"""Normalized, private comparisons; reports never contain source values."""

from datetime import date, datetime, timezone
from decimal import Decimal
import json

from tabula_rasa.ledger_validation import decode_receipt_references
from tabula_rasa.reference_data import as_bool, normalize_tag_ids

NUMBERS = {"amount", "opening_balance", "total_expense", "allocated_amount", "business_use_percentage",
           "cost_basis", "salvage_value", "miles", "useful_life_quarters", "recurrence_interval", "position"}


def normalized(field, value):
    if field == "tag_ids":
        return normalize_tag_ids(value)
    if field == "receipt_references":
        return decode_receipt_references(value)
    if field == "schedule_overrides":
        overrides = json.loads(value or "{}") if isinstance(value, str) else value
        return {int(sequence): (Decimal(details["amount"]), details["reason"])
                for sequence, details in overrides.items()}
    if field == "active":
        return as_bool(value)
    if value is None:
        return ""
    if field in NUMBERS and value != "":
        return Decimal(str(value))
    if field.endswith("_at") and value:
        instant = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.astimezone(timezone.utc)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def mismatched_fields(actual, expected):
    """Aggregate updated_at is target-owned; original instants live in mappings."""
    return sorted(field for field, value in expected.items() if field != "updated_at"
                  and (field not in actual or normalized(field, actual[field]) != normalized(field, value)))
