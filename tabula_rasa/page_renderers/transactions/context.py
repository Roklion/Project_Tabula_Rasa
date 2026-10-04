"""Application-shell dependencies for the Transactions page."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


@dataclass(frozen=True)
class TransactionsContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    profile_secrets: Mapping[str, object]
    configuration_revision: str
    get_drive_client: Callable[[str, str], object]
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]
    mark_workbook_data_changed: Callable[[], None] | None = None
    services: ApplicationServices | None = None
