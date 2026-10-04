"""Compatibility facade for the extracted profile-local mileage service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from functools import wraps
from typing import Any

from tabula_rasa.application.mileage import (
    MileageService,
    MileageValidationError,
    prepare_mileage_trip,
)

from .errors import StorageValidationError
from .validation import _normalize_tag_ids


def _compatible_errors(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except MileageValidationError as error:
            raise StorageValidationError(str(error)) from error

    return wrapped


class MileageMixin:
    """Keep the established dictionary API while sharing the service's owner."""

    def _mileage_service(self) -> MileageService:
        # Lazy to avoid cycling infrastructure construction through the facade.
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            GoogleSheetsMileageRepository,
        )

        return MileageService(GoogleSheetsMileageRepository(self))

    @staticmethod
    def _mileage_input(data: Mapping[str, Any]) -> dict[str, Any]:
        return {**data, "tag_ids": _normalize_tag_ids(data.get("tag_ids", ""))}

    @_compatible_errors
    def _prepare_mileage_trip(
        self,
        data: Mapping[str, Any],
        *,
        trip_id: str | None = None,
        created_at: str | None = None,
        original_tag_ids: Any = "",
        tags: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict[str, str]:
        """Compatibility for callers of the former private normalization helper."""
        from tabula_rasa.application.mileage import _apply_new_tag
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            GoogleSheetsMileageRepository,
            mileage_tag_from_record,
            mileage_trip_to_record,
        )

        repository = GoogleSheetsMileageRepository(self)
        references = (
            tuple(mileage_tag_from_record(item) for item in tags.values())
            if tags is not None
            else repository.list_tags(fresh=True)
        )
        trip = prepare_mileage_trip(
            self._mileage_input(data),
            references,
            trip_id=trip_id,
            created_at=created_at,
            original_tag_ids=_normalize_tag_ids(original_tag_ids),
        )
        return mileage_trip_to_record(
            _apply_new_tag((trip,), data.get("new_tag_name"), repository._create_tag)[0]
        )

    @_compatible_errors
    def list_mileage_trips(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            trip.as_record()
            for trip in self._mileage_service().list_trips(
                start=start, end=end, fresh=_force_refresh
            )
        ]

    @_compatible_errors
    def create_mileage_trip(self, **data: Any) -> dict[str, str]:
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            mileage_trip_to_record,
        )

        return mileage_trip_to_record(
            self._mileage_service().create_trip(**self._mileage_input(data))
        )

    @_compatible_errors
    def create_mileage_round_trip(
        self,
        *,
        return_miles: Any | None = None,
        **data: Any,
    ) -> list[dict[str, str]]:
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            mileage_trip_to_record,
        )

        return [
            mileage_trip_to_record(trip)
            for trip in self._mileage_service().create_round_trip(
                **self._mileage_input(data),
                return_miles=return_miles,
            )
        ]

    @_compatible_errors
    def edit_mileage_trip(self, trip_id: str, **changes: Any) -> dict[str, str]:
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            mileage_trip_to_record,
        )

        if "tag_ids" in changes:
            changes = self._mileage_input(changes)
        return mileage_trip_to_record(
            self._mileage_service().edit_trip(trip_id, **changes)
        )

    def delete_mileage_trip(self, trip_id: str) -> None:
        self._mileage_service().delete_trip(trip_id)

    @_compatible_errors
    def preview_quickbooks_mileage(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        _force_refresh: bool = False,
    ) -> dict[str, Any]:
        return (
            self._mileage_service()
            .preview_quickbooks_mileage(rows, fresh=_force_refresh)
            .as_record()
        )

    @_compatible_errors
    def import_quickbooks_mileage(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            mileage_trip_to_record,
        )

        return [
            mileage_trip_to_record(trip)
            for trip in self._mileage_service().import_quickbooks_mileage(rows)
        ]


__all__ = ["MileageMixin"]
