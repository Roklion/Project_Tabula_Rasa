"""Composition root for the current Sheets runtime; no Streamlit dependency."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from tabula_rasa.application import ApplicationServices, assemble_application_services
from tabula_rasa.business_profiles import (
    BusinessProfileConfigurationError,
    select_profile_secrets,
)
from tabula_rasa.infrastructure.google_sheets import (
    GoogleSheetsAccountRepository,
    GoogleSheetsLedgerSetupRepository,
    GoogleSheetsPayeeRepository,
    GoogleSheetsTagRepository,
    GoogleSheetsTransactionRepository,
    GoogleSheetsJournalRepository,
)
from tabula_rasa.storage import GoogleSheetsStorage


@dataclass(frozen=True)
class SheetsApplication:
    """Neutral services plus the explicitly transitional legacy facade.

    Keep the provider-specific bridge outside ApplicationServices. Remove it
    when callers have migrated to their domain services under issue #219.
    """

    services: ApplicationServices
    legacy_storage: GoogleSheetsStorage = field(repr=False)


def create_sheets_application(
    profile_key: str,
    secrets: Mapping[str, object],
) -> SheetsApplication:
    """Build one graph from the selected profile's existing Sheets backend."""
    # select_profile_secrets has a first-profile default for legacy callers.
    # A composition request must always name its profile explicitly.
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise BusinessProfileConfigurationError(
            "Application services require a selected business profile."
        )
    selected_secrets = select_profile_secrets(secrets, profile_key)
    storage = GoogleSheetsStorage.from_secrets(selected_secrets)
    services = assemble_application_services(
        profile_key,
        ledger_repository=GoogleSheetsLedgerSetupRepository(storage),
        account_repository=GoogleSheetsAccountRepository(storage),
        payee_repository=GoogleSheetsPayeeRepository(storage),
        tag_repository=GoogleSheetsTagRepository(storage),
        transaction_repository=GoogleSheetsTransactionRepository(storage),
        journal_repository=GoogleSheetsJournalRepository(storage),
    )
    return SheetsApplication(services=services, legacy_storage=storage)
