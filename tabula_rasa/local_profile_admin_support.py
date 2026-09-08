"""Shared, non-rendering helpers for local profile administration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageAuthenticationError,
    StorageError,
    StorageInitializationError,
    StorageValidationError,
    StorageWorkbookAccessError,
)
from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.local_profile_store import LocalProfileStoreError


def masked_spreadsheet_id(spreadsheet_id: object) -> str:
    value = str(spreadsheet_id)
    return f"…{value[-8:]}" if len(value) > 8 else value


def profile_setup_error_message(
    error: StorageError,
    settings: Mapping[str, Any],
) -> str:
    spreadsheet = masked_spreadsheet_id(settings.get("spreadsheet_id", ""))
    credential = settings.get("gcp_service_account", {})
    service_account = str(credential.get("client_email", "unknown"))

    if isinstance(error, StorageAuthenticationError):
        detail = (
            "Service-account authentication failed. The uploaded key may be "
            "invalid, disabled, revoked, or no longer active."
        )
    elif isinstance(error, StorageWorkbookAccessError):
        detail = (
            "Workbook access failed. Verify the spreadsheet ID, enable the "
            "Google Sheets API in the service-account project, and share the "
            "spreadsheet with this service account."
        )
    elif isinstance(error, StorageInitializationError):
        detail = (
            "The workbook opened, but initialization failed. Confirm the "
            "service account has Editor access and the ledger tabs are not "
            "protected."
        )
    elif isinstance(error, StorageValidationError):
        detail = f"Workbook structure validation failed: {error}."
    else:
        detail = "Google Sheets setup failed unexpectedly. Retry the request."

    return (
        f"{detail} Spreadsheet: {spreadsheet}. "
        f"Service account: {service_account}. No profile was saved."
    )


def validate_profile_edit_action(
    save_settings: bool,
    rotate_credential: bool,
    credential_file: Any,
) -> None:
    if save_settings and credential_file is not None:
        raise LocalProfileStoreError(
            "To replace the credential, use the 'Validate and rotate credential' button."
        )
    if rotate_credential and credential_file is None:
        raise LocalProfileStoreError(
            "Upload a replacement Google service-account JSON for rotation."
        )


def initialize_candidate_storage(
    settings: Mapping[str, Any],
) -> GoogleSheetsStorage:
    candidate_storage = GoogleSheetsStorage.from_secrets(settings)
    try:
        candidate_storage.ensure_defaults()
    except (
        StorageAuthenticationError,
        StorageWorkbookAccessError,
        StorageInitializationError,
        StorageValidationError,
    ):
        raise
    except StorageError as error:
        raise StorageInitializationError(
            "The workbook opened, but default accounts and categories "
            "could not be initialized"
        ) from error
    return candidate_storage


def configured_profiles_or_empty(effective_secrets: Mapping[str, Any]) -> list[Any]:
    """Treat a clean install without hosted profiles as having no profiles."""
    configured = effective_secrets.get("business_profiles")
    if configured is None or (isinstance(configured, Mapping) and not configured):
        return []
    return load_business_profiles(effective_secrets)
