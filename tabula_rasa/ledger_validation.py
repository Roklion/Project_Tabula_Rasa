"""Scalar ledger validation shared by application rules and adapters."""

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
