"""Trusted PostgreSQL composition; Sheets is retained for operator recovery only."""
from collections.abc import Mapping
from dataclasses import dataclass
from tabula_rasa.application import ApplicationServices
from tabula_rasa.business_profiles import BusinessProfileConfigurationError, select_profile_secrets
from tabula_rasa.infrastructure.drive_composition import create_drive_document_store


@dataclass(frozen=True)
class PostgresApplication:
    services: ApplicationServices
    workbook_admin: None = None


def _backend_configuration(profile_key, secrets):
    configurations = secrets.get("bookkeeping_backends", {})
    if not isinstance(configurations, Mapping):
        raise BusinessProfileConfigurationError("bookkeeping_backends must be a trusted per-profile mapping.")
    configured = configurations.get(profile_key)
    if (not isinstance(configured, Mapping) or not isinstance(configured.get("backend"), str)
            or configured["backend"] not in {"sheets", "postgres", "maintenance"}):
        raise BusinessProfileConfigurationError("An explicit valid bookkeeping backend is required for this profile.")
    if configured["backend"] == "postgres" and (
            # This is the stored cutover policy, independent of the HTTP
            # deployment environment. Rehearsal also supports lasting owner
            # operation under the documented non-commercial recovery contract.
            not isinstance(configured.get("entity_id"), str) or not configured["entity_id"].strip()
            or not isinstance(configured.get("mode"), str)
            or configured["mode"] not in {"rehearsal", "commercial_production"}):
        raise BusinessProfileConfigurationError("PostgreSQL requires an explicit entity and activation environment.")
    return configured


def _document_store(profile_key, selected_secrets, secrets, drive_client_factory):
    return create_drive_document_store(profile_key, selected_secrets, secrets,
                                       client_factory=drive_client_factory)


def create_application(profile_key, secrets, *, database=None, drive_client_factory=None):
    """Resolve trusted configuration after the caller resolves authorized scope.

    Configuration is not tenant authorization. Pool/schema lifecycle belongs
    to the caller; ordinary requests never migrate, activate or dual-write.
    """
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise BusinessProfileConfigurationError("Application services require a selected business profile.")
    selected = select_profile_secrets(secrets, profile_key)
    configured = _backend_configuration(profile_key, secrets)
    backend = configured["backend"]
    if backend == "sheets":
        raise BusinessProfileConfigurationError("Sheets bookkeeping is retired. Use the PostgreSQL browser application.")
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
