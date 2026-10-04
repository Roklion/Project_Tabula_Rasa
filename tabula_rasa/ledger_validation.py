"""Scalar ledger validation shared by application rules and adapters."""

import json
from collections.abc import Mapping, Sequence
from tabula_rasa.reference_data import normalize_tag_ids as _normalize_tag_ids
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.reference_data import clean_text as _clean_text
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    decode_receipt_reference_list,
)


def decode_receipt_references(value: Any) -> list[dict[str, Any]]:
    """Return validated Drive receipt references from a transaction record."""
    try:
        return decode_receipt_reference_list(value)
    except ReceiptManifestError as exc:
        message = (
            "Transaction receipt references are unreadable"
            if "unreadable" in str(exc).casefold()
            else "Transaction receipt references are invalid"
        )
        raise StorageValidationError(message) from exc


def positive_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise StorageValidationError("Amount must be numeric") from None
    if not amount.is_finite() or amount <= 0:
        raise StorageValidationError("Amount must be greater than zero")
    return format(amount.quantize(Decimal("0.01")), "f")


def iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = _clean_text(value, "Date", required=True)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise StorageValidationError("Date must use YYYY-MM-DD format") from None


def encode_tag_ids(value: Any) -> str:
    return json.dumps(
        _normalize_tag_ids(value), separators=(",", ":"), ensure_ascii=False
    )


def positive_integer(value: Any, label: str = "Value") -> int:
    """Return a strict positive integer, rejecting bools and fractions."""
    if isinstance(value, bool):
        raise StorageValidationError(f"{label} must be a positive integer")
    if isinstance(value, float) and not value.is_integer():
        raise StorageValidationError(f"{label} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise StorageValidationError(f"{label} must be a positive integer") from None
    text = str(value).strip()
    if not isinstance(value, float) and text not in {str(number), f"+{number}"}:
        raise StorageValidationError(f"{label} must be a positive integer")
    if number < 1:
        raise StorageValidationError(f"{label} must be a positive integer")
    return number


def validate_recurring_provenance(record: Mapping[str, Any], label: str) -> None:
    """Require recurring provenance columns to be present together."""
    fields = (
        "recurring_schedule_id",
        "recurring_scheduled_date",
        "recurring_source_kind",
        "recurring_occurrence_type",
    )
    present = [bool(str(record.get(field, "") or "").strip()) for field in fields]
    if any(present) and not all(present):
        raise StorageValidationError(
            f"{label} recurring provenance fields must be provided together"
        )
    if any(
        str(record.get(field, "") or "") != str(record.get(field, "") or "").strip()
        for field in fields
    ):
        raise StorageValidationError(
            f"{label} recurring provenance fields must not be padded"
        )


def validate_unique_recurring_occurrences(
    records: Sequence[Mapping[str, Any]], label: str
) -> None:
    seen: set[tuple[str, str]] = set()
    for record in records:
        schedule_id = str(record.get("recurring_schedule_id", "") or "").strip()
        scheduled_date = str(record.get("recurring_scheduled_date", "") or "").strip()
        if not schedule_id or not scheduled_date:
            continue
        key = (schedule_id, scheduled_date)
        if key in seen:
            raise StorageValidationError(
                f"{label} contains duplicate recurring occurrence dates"
            )
        seen.add(key)
