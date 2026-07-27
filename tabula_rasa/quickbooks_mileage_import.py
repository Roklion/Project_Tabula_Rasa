"""Normalize QuickBooks Online Download Trips CSV rows."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


FIELD_ALIASES = {
    "Date": ("date", "trip date"),
    "Type": ("type", "trip type", "classification"),
    "Trip Purpose": ("trip purpose", "purpose", "business purpose"),
    "Vehicle": ("vehicle", "vehicle used"),
    "Start Address": (
        "start address",
        "starting address",
        "start point",
        "starting point",
        "from",
    ),
    "End Address": (
        "end address",
        "ending address",
        "end point",
        "ending point",
        "destination",
        "to",
    ),
    "Distance": (
        "distance",
        "distance mi",
        "distance miles",
        "distance km",
        "distance kilometers",
        "distance kilometres",
        "business miles",
        "miles",
        "kilometers",
        "kilometres",
    ),
}
REQUIRED_COLUMNS = set(FIELD_ALIASES)
PERSONAL_TYPES = {"personal", "private"}
UNREVIEWED_TYPES = {"", "unreviewed", "uncategorized", "uncategorised"}
BUSINESS_TYPES = {"business"}
MILES_PER_KILOMETER = Decimal("0.621371192237334")


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value))
    normalized = re.sub(r"\s*\([^)]*\)\s*$", "", normalized)
    return " ".join(normalized.replace("_", " ").split()).casefold()


def _row_lookup(source: Mapping[str, Any]) -> dict[str, Any]:
    return {_key(name): value for name, value in source.items()}


def _value(source: Mapping[str, Any], field: str) -> Any:
    lookup = _row_lookup(source)
    return next(
        (lookup[alias] for alias in FIELD_ALIASES[field] if alias in lookup),
        "",
    )


def missing_required_columns(columns: Iterable[Any]) -> list[str]:
    """Return canonical QuickBooks fields not represented by the source headers."""
    present = {_key(column) for column in columns}
    return [
        field
        for field, aliases in FIELD_ALIASES.items()
        if not any(alias in present for alias in aliases)
    ]


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Date must use MM/DD/YYYY, MM/DD/YY, or YYYY-MM-DD")


def _distance(value: Any, header_names: Iterable[Any]) -> str:
    text = _text(value).casefold().replace(",", "")
    unit = "miles"
    if re.search(r"\b(km|kilometers?|kilometres?)\b", text):
        unit = "kilometers"
    elif not re.search(r"\b(mi|miles?)\b", text):
        distance_headers = [
            _text(header).casefold()
            for header in header_names
            if _key(header) in FIELD_ALIASES["Distance"]
        ]
        if any(
            re.search(r"\b(km|kilometers?|kilometres?)\b", header)
            for header in distance_headers
        ):
            unit = "kilometers"
    numeric = re.sub(r"\s*(mi|miles?|km|kilometers?|kilometres?)\s*$", "", text)
    try:
        distance = Decimal(numeric)
    except InvalidOperation as error:
        raise ValueError("Distance must be a number") from error
    if not distance.is_finite() or distance <= 0:
        raise ValueError("Distance must be greater than zero")
    if unit == "kilometers":
        distance *= MILES_PER_KILOMETER
    return format(distance.quantize(Decimal("0.1")), "f")


def mileage_fingerprint(row: Mapping[str, Any]) -> str:
    """Return a stable identity for duplicate mileage detection."""
    fields = (
        "trip_date",
        "miles",
        "vehicle",
        "start_location",
        "destination",
        "business_purpose",
    )
    payload = [
        " ".join(_text(row.get(field)).split()).casefold()
        for field in fields
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


def normalize_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Map business trips and classify skipped rows, collecting all errors."""
    normalized: list[dict[str, str]] = []
    errors: list[str] = []
    personal_rows: list[int] = []
    unreviewed_rows: list[int] = []
    for number, source in enumerate(rows, start=2):
        if not any(_text(value) for value in source.values()):
            continue
        trip_type = _text(_value(source, "Type")).casefold()
        if trip_type in PERSONAL_TYPES:
            personal_rows.append(number)
            continue
        if trip_type in UNREVIEWED_TYPES:
            unreviewed_rows.append(number)
            continue
        if trip_type not in BUSINESS_TYPES:
            errors.append(
                f"QuickBooks mileage row {number}: unknown trip type "
                f"'{_text(_value(source, 'Type'))}'"
            )
            continue
        try:
            start_location = _text(_value(source, "Start Address"))
            destination = _text(_value(source, "End Address"))
            purpose = _text(_value(source, "Trip Purpose"))
            if not start_location:
                raise ValueError("Start Address is required")
            if not destination:
                raise ValueError("End Address is required")
            if not purpose:
                raise ValueError("Trip Purpose is required for business trips")
            normalized.append(
                {
                    "_source_row": str(number),
                    "trip_date": _date(_value(source, "Date")),
                    "miles": _distance(_value(source, "Distance"), source.keys()),
                    "vehicle": _text(_value(source, "Vehicle")),
                    "start_location": start_location,
                    "destination": destination,
                    "business_purpose": purpose,
                    "notes": "",
                }
            )
        except ValueError as error:
            errors.append(f"QuickBooks mileage row {number}: {error}")
    return {
        "rows": normalized,
        "errors": errors,
        "personal_rows": personal_rows,
        "unreviewed_rows": unreviewed_rows,
    }
