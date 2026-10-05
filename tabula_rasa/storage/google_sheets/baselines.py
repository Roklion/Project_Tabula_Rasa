"""Complete normalized snapshots for newly guarded compatibility paths."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from .errors import StorageConflictError, StorageValidationError
from .validation import _as_bool, _clean_text, _normalize_tag_ids


def check_expected_snapshot(
    current: Mapping[str, object], expected: Mapping[str, object] | None, *,
    fields: Sequence[str], label: str,
) -> None:
    if expected is None:
        return
    if "baseline" in expected or any(field not in expected for field in fields):
        raise StorageValidationError(f"A complete loaded {label} snapshot is required")

    def value(record, field):
        raw = record.get(field)
        if field == "active":
            return _as_bool(raw)
        if field in {"opening_balance", "miles"}:
            try:
                return Decimal(str(raw))
            except (InvalidOperation, ValueError):
                raise StorageValidationError(f"Invalid loaded {label} snapshot") from None
        if field == "tag_ids":
            return tuple(sorted(_normalize_tag_ids(raw)))
        return _clean_text(raw, field)

    if any(value(current, field) != value(expected, field) for field in fields):
        raise StorageConflictError(f"The {label} changed. Reload it before trying again.")


ACCOUNT_FIELDS = (
    "id", "name", "type", "classification", "opening_balance", "active", "created_at", "parent_id",
)
CATEGORY_FIELDS = ("id", "name", "kind", "parent_id")
MILEAGE_FIELDS = (
    "id", "trip_date", "miles", "vehicle", "start_location", "destination",
    "business_purpose", "notes", "tag_ids", "created_at",
)
