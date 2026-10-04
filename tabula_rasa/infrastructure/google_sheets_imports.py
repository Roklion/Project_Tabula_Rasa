"""Adapt current transaction batch imports to the application import port."""

from collections.abc import Iterable

from tabula_rasa.application.imports import ImportRow, TransactionImportContext
from tabula_rasa.storage import GoogleSheetsStorage


class GoogleSheetsTransactionImportRepository:
    """Keep fresh commit validation and recovery with their existing owners."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def quickbooks_context(self) -> TransactionImportContext:
        self._storage.prefetch_worksheets(
            "Accounts", "Categories", "Transactions", "Payees", "Tags"
        )
        return TransactionImportContext(
            accounts=list(self._storage._account_lookup().values()),
            categories=list(self._storage._category_lookup().values()),
            payees=self._storage.list_payees(),
            transactions=self._storage.list_transactions(),
        )

    def import_csv(self, rows: Iterable[ImportRow]) -> list[dict[str, str]]:
        return self._storage.import_csv_transactions(rows)

    def import_quickbooks(
        self, rows: Iterable[ImportRow], *, auto_create: bool = False
    ) -> list[dict[str, str]]:
        return self._storage.import_quickbooks_transactions(rows, auto_create=auto_create)
