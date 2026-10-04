"""Resolve the reporting capability only for the selected page profile."""

from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.errors import StorageValidationError


def reporting_service(context) -> ReportingService:
    services = context.services
    if services.profile_key != context.profile_key:
        raise StorageValidationError(
            "Reporting services do not match the selected business profile."
        )
    return services.reporting
