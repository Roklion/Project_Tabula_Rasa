"""Adapt the existing Sheets facade without copying its persistence behavior."""

from tabula_rasa.storage import GoogleSheetsStorage


class GoogleSheetsLedgerSetupRepository:
    """Ledger setup port backed by the same facade used by transitional pages."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    @property
    def ledger_name(self) -> str:
        return self._storage.workbook_title

    def ensure_defaults(self) -> dict[str, int]:
        return self._storage.ensure_defaults()
