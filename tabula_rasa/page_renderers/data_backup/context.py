"""Explicit application-shell dependencies for the Data & backup page."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.google_drive import GoogleDriveClient
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


@dataclass(frozen=True)
class DataBackupContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    drive_settings: Mapping[str, object] | None
    synology_recovery_settings: object
    configuration_revision: str
    get_drive_client: Callable[[str, str], GoogleDriveClient]
    receipt_manifest_for_backup: Callable[..., dict[str, object]]
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    services: ApplicationServices | None = None
