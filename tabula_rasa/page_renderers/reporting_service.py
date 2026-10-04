"""Resolve the reporting capability only for the selected page profile."""

from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.storage import StorageValidationError


def reporting_service(context) -> ReportingService | None:
    services = context.services
    if services is None or services.reporting is None:
        return None
    if services.profile_key != context.profile_key:
        raise StorageValidationError(
            "Reporting services do not match the selected business profile."
        )
    return services.reporting
