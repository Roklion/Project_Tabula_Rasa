"""Sheets mileage serialization and mutation boundary; no mileage business rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from tabula_rasa.application.mileage import MileageTag, MileageTrip
from tabula_rasa.application.mileage_contracts import (
    PrepareImport,
    PrepareNewTrips,
    PrepareUpdatedTrip,
)
from tabula_rasa.storage.google_sheets.errors import (
    StorageConflictError,
    StorageNotFoundError,
)
from tabula_rasa.storage.google_sheets.validation import (
    _as_bool,
    _encode_tag_ids,
    _normalize_tag_ids,
)
from tabula_rasa.storage.google_sheets.baselines import MILEAGE_FIELDS, check_expected_snapshot

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


def mileage_trip_to_record(trip: MileageTrip) -> dict[str, str]:
    """Serialize the current workbook fields, omitting resolved display labels."""
    record = trip.as_record()
    record.pop("tags")
    record.pop("baseline", None)
    record["tag_ids"] = _encode_tag_ids(trip.tag_ids)
    return record


class GoogleSheetsMileageRepository:
    """Adapt one existing profile facade and reuse its locks/caches/write policy."""

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

    def _create_tag(self, name: str) -> MileageTag:
        return mileage_tag_from_record(self._storage.create_tag(name))

    def add_trips(self, prepare: PrepareNewTrips) -> tuple[MileageTrip, ...]:
        with self._storage._workbook_locks.ledger:
            trips = tuple(prepare(self.list_tags(fresh=True), self._create_tag))
            if len(trips) == 1:
                self._storage._append("Mileage", mileage_trip_to_record(trips[0]))
            else:
                # The service's semantic order is outbound/return. Equal-time
                # new pairs are displayed return first by worksheet insertion.
                self._storage._append_many(
                    "Mileage",
                    [mileage_trip_to_record(trip) for trip in reversed(trips)],
                )
            return trips

    def update_trip(self, trip_id: str, prepare: PrepareUpdatedTrip, *, expected=None) -> MileageTrip:
        with self._storage._workbook_locks.ledger:
            current = self._storage._find_row("Mileage", trip_id)
            check_expected_snapshot(current.values, expected, fields=MILEAGE_FIELDS, label="mileage trip")
            updated = prepare(
                mileage_trip_from_record(current.values),
                self.list_tags(fresh=True),
                self._create_tag,
            )
            self._storage._replace_row(
                "Mileage", current, mileage_trip_to_record(updated)
            )
            return updated

    def import_trips(self, prepare: PrepareImport) -> tuple[MileageTrip, ...]:
        with self._storage._workbook_locks.ledger:
            # One fresh Tag read supports both existing-row validation and all
            # imported records, preserving the import's bounded read footprint.
            tags = self.list_tags(fresh=True)
            trips = tuple(prepare(self.list_trips(fresh=True), tags))
            self._storage._append_many(
                "Mileage", [mileage_trip_to_record(trip) for trip in trips]
            )
            return trips

    def delete_trip(self, trip_id: str, *, expected=None) -> None:
        with self._storage._workbook_locks.ledger:
            current = self._storage._find_row("Mileage", trip_id)
            check_expected_snapshot(current.values, expected, fields=MILEAGE_FIELDS, label="mileage trip")
            original = dict(current.values)
            current_row = current
            worksheet = self._storage._worksheet("Mileage")

            def write() -> None:
                self._storage._api(
                    lambda: worksheet.delete_rows(current_row.row_number),
                    retry_safe=False,
                )

            def state() -> str:
                try:
                    latest = self._storage._find_row("Mileage", trip_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh() -> None:
                nonlocal current_row
                current_row = self._storage._find_row("Mileage", trip_id)
                if current_row.values != original:
                    raise StorageConflictError(
                        "The mileage trip changed while deletion was being retried."
                    )

            self._storage._write_with_uncertain_readback(
                "mileage deletion",
                write,
                state,
                before_retry=refresh,
                invalidate=("Mileage",),
            )
