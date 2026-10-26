"""Read-only format-13 mileage adapter using shared mileage validation."""

from __future__ import annotations

from datetime import date
from functools import wraps
from typing import Any

from tabula_rasa.application.mileage import (
    MileageService,
    MileageValidationError,
)

from .errors import StorageValidationError


def _compatible_errors(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except MileageValidationError as error:
            raise StorageValidationError(str(error)) from error

    return wrapped


class MileageMixin:
    """Expose supported source validation reads without mileage writers."""

    def _mileage_service(self) -> MileageService:
        # Lazy to avoid cycling infrastructure construction through the facade.
        from tabula_rasa.infrastructure.google_sheets_mileage import (
            GoogleSheetsMileageRepository,
        )

        return MileageService(GoogleSheetsMileageRepository(self))


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


__all__ = ["MileageMixin"]
