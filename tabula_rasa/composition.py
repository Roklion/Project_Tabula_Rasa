"""Trusted per-profile bookkeeping composition; no Streamlit dependency."""

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
from tabula_rasa.infrastructure.google_sheets import (
    GoogleSheetsAccountRepository,
    GoogleSheetsCategoryRepository,
    GoogleSheetsPayeeRepository,
    GoogleSheetsTagRepository,
    GoogleSheetsTransactionRepository,
    GoogleSheetsJournalRepository,
)
from tabula_rasa.infrastructure.google_sheets_assets import GoogleSheetsAssetRepository
from tabula_rasa.infrastructure.google_sheets_mixed_use import GoogleSheetsMixedUseRepository
from tabula_rasa.infrastructure.google_sheets_recurring import GoogleSheetsRecurringRepository
from tabula_rasa.infrastructure.google_sheets_imports import GoogleSheetsTransactionImportRepository
from tabula_rasa.storage import GoogleSheetsStorage


@dataclass(frozen=True)
class SheetsApplication:
    """Bookkeeping services and explicit Sheets workbook administration.

    Only backup/operator workflows receive workbook_admin. Ordinary pages
    receive services, so provider-specific methods are not an application API.
    """

    services: ApplicationServices
    workbook_admin: GoogleSheetsStorage = field(repr=False)


@dataclass(frozen=True)
class PostgresApplication:
    services: ApplicationServices
    workbook_admin: None = None


def _backend_configuration(profile_key, secrets, *, explicit=False):
    configurations = secrets.get("bookkeeping_backends", {})
    if not isinstance(configurations, Mapping):
        raise BusinessProfileConfigurationError("bookkeeping_backends must be a trusted per-profile mapping.")
    configured = configurations.get(profile_key)
    if profile_key not in configurations and not explicit:
        return {"backend": "sheets"}
    if (not isinstance(configured, Mapping) or not isinstance(configured.get("backend"), str)
            or configured["backend"] not in {"sheets", "postgres", "maintenance"}):
        raise BusinessProfileConfigurationError("An explicit valid bookkeeping backend is required for this profile.")
    if configured["backend"] == "postgres" and (
            not isinstance(configured.get("entity_id"), str) or not configured["entity_id"].strip()
            or not isinstance(configured.get("mode"), str)
            or configured["mode"] not in {"rehearsal", "commercial_production"}):
        raise BusinessProfileConfigurationError("PostgreSQL requires an explicit entity and activation environment.")
    return configured


def _document_store(profile_key, selected_secrets, secrets, drive_client_factory):
    drive_settings = selected_secrets.get("google_drive")
    receipt_folder = drive_settings.get("receipt_folder") if isinstance(drive_settings, Mapping) else None
    folder_id = str(receipt_folder.get("id", "")) if isinstance(receipt_folder, Mapping) else ""

    def create_drive_client():
        from tabula_rasa.google_drive import GoogleDriveClient, GoogleDriveConfigurationError, load_oauth_config
        if not isinstance(drive_settings, Mapping):
            raise GoogleDriveConfigurationError("Google Drive is not connected for this business profile.")
        return GoogleDriveClient(load_oauth_config(secrets), drive_settings)

    return GoogleDriveDocumentStore(profile_key, folder_id,
                                    drive_client_factory if drive_client_factory is not None else create_drive_client)


def create_application(profile_key, secrets, *, database=None, drive_client_factory=None):
    """Resolve trusted configuration after the caller resolves authorized scope.

    Configuration is not tenant authorization. Pool/schema lifecycle belongs
    to the caller; ordinary requests never migrate, activate or dual-write.
    """
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise BusinessProfileConfigurationError("Application services require a selected business profile.")
    selected = select_profile_secrets(secrets, profile_key)
    configured = _backend_configuration(profile_key, secrets, explicit=True)
    backend = configured["backend"]
    if backend == "sheets":
        return create_sheets_application(profile_key, secrets, drive_client_factory=drive_client_factory)
    if backend == "maintenance":
        raise BusinessProfileConfigurationError("This profile is in bookkeeping maintenance.")
    if database is None:
        raise BusinessProfileConfigurationError("The selected PostgreSQL backend requires its configured database.")
    from tabula_rasa.migration.model import Binding
    from tabula_rasa.infrastructure.postgres.cutover import PostgresCutoverController
    from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
    from tabula_rasa.infrastructure.entity_documents import EntityDocumentStore
    binding = Binding(profile_key, str(selected["spreadsheet_id"]).strip(), configured["entity_id"])
    store = EntityDocumentStore(binding.entity_id, profile_key,
                                _document_store(profile_key, selected, secrets, drive_client_factory))
    PostgresCutoverController(database).require_postgres(binding, mode=configured["mode"], document_scope=store.scope_key)
    services = create_postgres_services(database, binding.entity_id,
        document_store=store if store.scope_key else None,
        document_store_kind="google_drive" if store.scope_key else None)
    return PostgresApplication(services)


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
    if _backend_configuration(profile_key, secrets)["backend"] != "sheets":
        raise BusinessProfileConfigurationError("This profile is not configured for the Sheets runtime.")
    storage = GoogleSheetsStorage.from_secrets(selected_secrets)

    services = assemble_application_services(
        profile_key,
        ledger_repository=GoogleSheetsLedgerSetupRepository(storage),
        reporting_repository=GoogleSheetsLedgerQueryRepository(storage),
        receipt_repository=GoogleSheetsReceiptRepository(profile_key, storage),
        document_store=_document_store(profile_key, selected_secrets, secrets, drive_client_factory),
        mileage_repository=GoogleSheetsMileageRepository(storage),
        account_repository=GoogleSheetsAccountRepository(storage),
        category_repository=GoogleSheetsCategoryRepository(storage),
        import_repository=GoogleSheetsTransactionImportRepository(storage),
        payee_repository=GoogleSheetsPayeeRepository(storage),
        tag_repository=GoogleSheetsTagRepository(storage),
        transaction_repository=GoogleSheetsTransactionRepository(storage),
        journal_repository=GoogleSheetsJournalRepository(storage),
        asset_repository=GoogleSheetsAssetRepository(storage),
        mixed_use_repository=GoogleSheetsMixedUseRepository(storage),
        recurring_repository=GoogleSheetsRecurringRepository(storage),
    )
    return SheetsApplication(services=services, workbook_admin=storage)
