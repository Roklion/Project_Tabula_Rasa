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


def masked_spreadsheet_id(spreadsheet_id: object) -> str:
    value = str(spreadsheet_id)
    return f"…{value[-8:]}" if len(value) > 8 else value


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
