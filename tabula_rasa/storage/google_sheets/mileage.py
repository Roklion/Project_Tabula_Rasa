"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import uuid4
from tabula_rasa.quickbooks_mileage_import import mileage_fingerprint
from tabula_rasa.quickbooks_mileage_import import missing_required_columns as missing_quickbooks_mileage_columns
from tabula_rasa.quickbooks_mileage_import import normalize_rows as normalize_quickbooks_mileage_rows
from .errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _clean_text,
    _encode_tag_ids,
    _iso_date,
    _normalize_tag_ids,
    _positive_miles,
    _utc_now,
)
from .base import _workbook_mutation_lock

class MileageMixin:
    """Mixin for the mileage storage boundary."""

    def _prepare_mileage_trip(
        self,
        data: Mapping[str, Any],
        *,
        trip_id: str | None = None,
        created_at: str | None = None,
        original_tag_ids: Any = "",
        tags: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict[str, str]:
        trip_date = _iso_date(data.get("trip_date"))
        miles = _positive_miles(data.get("miles"))
        vehicle = _clean_text(data.get("vehicle"), "Vehicle")
        start_location = _clean_text(
            data.get("start_location"), "Starting location", required=True
        )
        destination = _clean_text(
            data.get("destination"), "Destination", required=True
        )
        business_purpose = _clean_text(
            data.get("business_purpose"), "Business purpose", required=True
        )
        notes = _clean_text(data.get("notes"), "Notes")
        tags = dict(tags) if tags is not None else self._tag_lookup(force_refresh=True)
        tag_ids = _normalize_tag_ids(data.get("tag_ids", ""))
        original_tag_ids = _normalize_tag_ids(original_tag_ids)
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
                raise StorageValidationError("Tag is inactive")
        new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
        if new_tag_name:
            new_tag = self.create_tag(new_tag_name)
            if new_tag["id"] not in tag_ids:
                tag_ids.append(new_tag["id"])
            tags[new_tag["id"]] = new_tag
            tag_ids = _normalize_tag_ids(tag_ids)
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
                raise StorageValidationError("Tag is inactive")
        return {
            "id": trip_id or str(uuid4()),
            "trip_date": trip_date,
            "miles": miles,
            "vehicle": vehicle,
            "start_location": start_location,
            "destination": destination,
            "business_purpose": business_purpose,
            "notes": notes,
            "tag_ids": _encode_tag_ids(tag_ids),
            "created_at": created_at or _utc_now(),
        }

    def list_mileage_trips(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        _force_refresh: bool = False,
    ) -> list[dict[str, str]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        trips = []
        trip_ids: set[str] = set()
        tags = self._tag_lookup(force_refresh=_force_refresh)
        for row in self._rows("Mileage", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Mileage ID", required=True)
            if item["id"] in trip_ids:
                raise StorageValidationError("Mileage IDs must be unique")
            trip_ids.add(item["id"])
            item["trip_date"] = _iso_date(item.get("trip_date"))
            item["miles"] = _positive_miles(item.get("miles"))
            item["vehicle"] = _clean_text(item.get("vehicle"), "Vehicle")
            item["start_location"] = _clean_text(
                item.get("start_location"), "Starting location", required=True
            )
            item["destination"] = _clean_text(
                item.get("destination"), "Destination", required=True
            )
            item["business_purpose"] = _clean_text(
                item.get("business_purpose"), "Business purpose", required=True
            )
            item["notes"] = _clean_text(item.get("notes"), "Notes")
            if start_text and item["trip_date"] < start_text:
                continue
            if end_text and item["trip_date"] > end_text:
                continue
            normalized_tag_ids = _normalize_tag_ids(item.get("tag_ids", ""))
            if any(tag_id not in tags for tag_id in normalized_tag_ids):
                raise StorageValidationError("Tag does not exist")
            item["tag_ids"] = normalized_tag_ids
            item["tags"] = [tags[tag_id]["name"] for tag_id in normalized_tag_ids]
            trips.append(item)
        return sorted(
            trips,
            # Python's sort is stable, so same-timestamp rows retain the
            # worksheet insertion order. New round-trip writes intentionally
            # put the reversed return leg before outbound.
            key=lambda item: (item["trip_date"], item["created_at"]),
            reverse=True,
        )

    def create_mileage_trip(self, **data: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            record = self._prepare_mileage_trip(data)
            self._append("Mileage", record)
            return record

    def create_mileage_round_trip(
        self,
        *,
        return_miles: Any | None = None,
        **data: Any,
    ) -> list[dict[str, str]]:
        """Create outbound and reversed return entries in one batch write.

        ``return_miles`` is optional for compatibility with callers that use
        one distance for both legs.  When supplied, it is validated and used
        only for the reversed return entry.
        """
        with self._workbook_locks.ledger:
            created_at = _utc_now()
            new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
            prepared_data = dict(data)
            prepared_data["new_tag_name"] = ""
            outbound = self._prepare_mileage_trip(
                prepared_data,
                created_at=created_at,
            )
            return_data = dict(prepared_data)
            return_data.update(
                {
                    "start_location": data.get("destination"),
                    "destination": data.get("start_location"),
                }
            )
            if return_miles is not None:
                return_data["miles"] = return_miles
            return_trip = self._prepare_mileage_trip(
                return_data,
                created_at=created_at,
            )
            if new_tag_name:
                new_tag = self.create_tag(new_tag_name)
                for trip in (outbound, return_trip):
                    tag_ids = _normalize_tag_ids(trip["tag_ids"])
                    if new_tag["id"] not in tag_ids:
                        tag_ids.append(new_tag["id"])
                    trip["tag_ids"] = _encode_tag_ids(tag_ids)
            # Keep the public return value in semantic outbound/return order, but
            # write the rows in the order the log should display for a new pair.
            # Existing rows are not rewritten or migrated.
            records = [outbound, return_trip]
            self._append_many("Mileage", [return_trip, outbound])
            return records

    def edit_mileage_trip(self, trip_id: str, **changes: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            current = self._find_row("Mileage", trip_id)
            merged = dict(current.values)
            merged.update(changes)
            updated = self._prepare_mileage_trip(
                merged,
                trip_id=trip_id,
                created_at=current.values["created_at"],
                original_tag_ids=current.values.get("tag_ids", ""),
            )
            self._replace_row("Mileage", current, updated)
            return updated

    def delete_mileage_trip(self, trip_id: str) -> None:
        with self._workbook_locks.ledger:
            current = self._find_row("Mileage", trip_id)
            original = dict(current.values)
            current_row = current
            worksheet = self._worksheet("Mileage")

            def write() -> None:
                self._api(
                    lambda: worksheet.delete_rows(current_row.row_number),
                    retry_safe=False,
                )

            def state() -> str:
                try:
                    latest = self._find_row("Mileage", trip_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh() -> None:
                nonlocal current_row
                current_row = self._find_row("Mileage", trip_id)
                if current_row.values != original:
                    raise StorageConflictError(
                        "The mileage trip changed while deletion was being retried."
                    )

            self._write_with_uncertain_readback(
                "mileage deletion", write, state, before_retry=refresh,
                invalidate=("Mileage",),
            )

    def preview_quickbooks_mileage(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        _force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Validate a QuickBooks Download Trips export without writing it."""
        source_rows = list(rows)
        source_columns = {
            str(column)
            for row in source_rows
            for column in row
        }
        missing = missing_quickbooks_mileage_columns(source_columns)
        if missing:
            normalized = {
                "rows": [],
                "errors": [
                    "QuickBooks mileage export is missing columns: "
                    + ", ".join(missing)
                ],
                "personal_rows": [],
                "unreviewed_rows": [],
            }
        else:
            normalized = normalize_quickbooks_mileage_rows(source_rows)

        existing = {
            mileage_fingerprint(item)
            for item in self.list_mileage_trips(_force_refresh=_force_refresh)
        }
        seen: set[str] = set()
        ready: list[dict[str, str]] = []
        duplicate_rows: list[int] = []
        for source_item in normalized["rows"]:
            item = dict(source_item)
            row_number = int(item.pop("_source_row"))
            identity = mileage_fingerprint(item)
            if identity in existing or identity in seen:
                duplicate_rows.append(row_number)
            else:
                seen.add(identity)
                ready.append(item)
        return {
            "rows": ready,
            "errors": normalized["errors"],
            "duplicate_rows": duplicate_rows,
            "personal_rows": normalized["personal_rows"],
            "unreviewed_rows": normalized["unreviewed_rows"],
            "summary": {
                "ready": len(ready),
                "duplicates": len(duplicate_rows),
                "personal_skipped": len(normalized["personal_rows"]),
                "unreviewed_skipped": len(normalized["unreviewed_rows"]),
            },
        }

    @_workbook_mutation_lock
    def import_quickbooks_mileage(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        """Revalidate and batch append unique business mileage trips."""
        preview = self.preview_quickbooks_mileage(
            list(rows),
            _force_refresh=True,
        )
        if preview["errors"]:
            raise StorageValidationError("\n".join(preview["errors"]))
        tags = self._tag_lookup()
        prepared = [
            self._prepare_mileage_trip(item, tags=tags) for item in preview["rows"]
        ]
        self._append_many("Mileage", prepared)
        return prepared

__all__ = ["MileageMixin"]
