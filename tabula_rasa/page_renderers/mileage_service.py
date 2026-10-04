"""Compatibility wiring and safe error presentation for mileage controllers."""

from collections.abc import Callable
from typing import TypeVar

from tabula_rasa.application.mileage import MileageService, MileageValidationError
from tabula_rasa.storage import StorageValidationError

T = TypeVar("T")


def mileage_service(context) -> MileageService:
    """Use supplied services; support existing explicit-storage page contexts."""
    services = context.services
    if services is not None and services.mileage is not None:
        if services.profile_key != context.profile_key:
            raise StorageValidationError(
                "Mileage services do not match the selected business profile."
            )
        return services.mileage
    from tabula_rasa.infrastructure.google_sheets_mileage import (
        GoogleSheetsMileageRepository,
    )

    return MileageService(GoogleSheetsMileageRepository(context.storage))


def mileage_action(operation: Callable[[], T]) -> T:
    """Adapt neutral validation failures to the shell's established error UI."""
    try:
        return operation()
    except MileageValidationError as error:
        raise StorageValidationError(str(error)) from error
