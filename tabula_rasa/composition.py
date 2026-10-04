"""Composition root for the current Sheets runtime; no Streamlit dependency."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from tabula_rasa.application import ApplicationServices, assemble_application_services
from tabula_rasa.business_profiles import (
    BusinessProfileConfigurationError,
    select_profile_secrets,
)
from tabula_rasa.infrastructure.google_sheets import GoogleSheetsLedgerSetupRepository
from tabula_rasa.infrastructure.google_drive_documents import GoogleDriveDocumentStore
from tabula_rasa.infrastructure.google_sheets_mileage import GoogleSheetsMileageRepository
from tabula_rasa.infrastructure.google_sheets_receipts import GoogleSheetsReceiptRepository
from tabula_rasa.infrastructure.google_sheets_reporting import GoogleSheetsLedgerQueryRepository
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
    *,
    drive_client_factory: Callable[[], object] | None = None,
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
    drive_settings = selected_secrets.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder") if isinstance(drive_settings, Mapping) else None
    )
    folder_id = str(receipt_folder.get("id", "")) if isinstance(receipt_folder, Mapping) else ""

    def create_drive_client() -> object:
        # Receipt availability does not gate ledger startup. Construct OAuth
        # infrastructure only when a document operation needs it.
        from tabula_rasa.google_drive import (
            GoogleDriveClient,
            GoogleDriveConfigurationError,
            load_oauth_config,
        )

        if not isinstance(drive_settings, Mapping):
            raise GoogleDriveConfigurationError(
                "Google Drive is not connected for this business profile."
            )
        return GoogleDriveClient(load_oauth_config(secrets), drive_settings)

    services = assemble_application_services(
        profile_key,
        ledger_repository=GoogleSheetsLedgerSetupRepository(storage),
        reporting_repository=GoogleSheetsLedgerQueryRepository(storage),
        receipt_repository=GoogleSheetsReceiptRepository(profile_key, storage),
        document_store=GoogleDriveDocumentStore(
            profile_key, folder_id,
            drive_client_factory if drive_client_factory is not None else create_drive_client,
        ),
        mileage_repository=GoogleSheetsMileageRepository(storage),
    )
    return SheetsApplication(services=services, legacy_storage=storage)
