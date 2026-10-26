"""Read-only Sheets mileage serialization for source validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from tabula_rasa.application.mileage import MileageTag, MileageTrip
from tabula_rasa.storage.google_sheets.validation import (
    _as_bool,
    _normalize_tag_ids,
)

if TYPE_CHECKING:
    from tabula_rasa.storage import GoogleSheetsStorage


def mileage_tag_from_record(record: Mapping[str, Any]) -> MileageTag:
    return MileageTag(
        id=record["id"],
        name=record["name"],
        active=_as_bool(record["active"], "Tag active"),
        created_at=record.get("created_at", ""),
    )


def mileage_trip_from_record(record: Mapping[str, Any]) -> MileageTrip:
    """Decode only the stored representation; the service validates its fields."""
    return MileageTrip(
        id=record.get("id", ""),
        trip_date=record.get("trip_date", ""),
        miles=record.get("miles", ""),
        vehicle=record.get("vehicle", ""),
        start_location=record.get("start_location", ""),
        destination=record.get("destination", ""),
        business_purpose=record.get("business_purpose", ""),
        notes=record.get("notes", ""),
        tag_ids=tuple(_normalize_tag_ids(record.get("tag_ids", ""))),
        created_at=record.get("created_at", ""),
    )


class GoogleSheetsMileageRepository:
    """Read one explicit profile facade using its current source cache."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list_tags(self, *, fresh: bool = False) -> tuple[MileageTag, ...]:
        return tuple(
            mileage_tag_from_record(item)
            for item in self._storage.list_tags(_force_refresh=fresh)
        )

    def list_trips(self, *, fresh: bool = False) -> tuple[MileageTrip, ...]:
        return tuple(
            mileage_trip_from_record(row.values)
            for row in self._storage._rows("Mileage", force_refresh=fresh)
        )
