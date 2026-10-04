"""Selected-profile mileage capability and safe error presentation."""

from collections.abc import Callable
from typing import TypeVar

from tabula_rasa.application.mileage import MileageService, MileageValidationError
from tabula_rasa.errors import StorageValidationError

T = TypeVar("T")


def mileage_service(context) -> MileageService:
    """Use the application's selected-profile mileage service."""
    services = context.services
    if services.profile_key != context.profile_key:
        raise StorageValidationError(
            "Mileage services do not match the selected business profile."
        )
    return services.mileage


def mileage_action(operation: Callable[[], T]) -> T:
    """Adapt neutral validation failures to the shell's established error UI."""
    try:
        return operation()
    except MileageValidationError as error:
        raise StorageValidationError(str(error)) from error
