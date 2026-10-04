"""Normalize the current Sheets ledger into the reporting read-model port."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tabula_rasa.application.reporting_contracts import (
    LedgerJournal,
    LedgerPosting,
    LedgerSnapshot,
    LedgerTransaction,
    ReportingAccount,
    ReportingCategory,
)
from tabula_rasa.storage import GoogleSheetsStorage, decode_receipt_references


class GoogleSheetsLedgerQueryRepository:
    """Reuse the selected facade's validation/cache; expose only domain values."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def read_ledger(self, *, force_refresh: bool = False) -> LedgerSnapshot:
        if not force_refresh:
            self._storage.prefetch_worksheets("Accounts", "Categories", "Transactions")
        accounts = tuple(
            ReportingAccount(
                id=row["id"], name=row["name"], type=row["type"],
                classification=row["classification"],
                opening_balance=Decimal(str(row["opening_balance"])),
                active=row["active"], parent_id=row.get("parent_id", ""),
            )
            for row in self._storage.list_accounts(
                active_only=False, _force_refresh=force_refresh,
            )
        )
        categories = tuple(
            ReportingCategory(
                id=row["id"], name=row["name"], kind=row["kind"],
                parent_id=row.get("parent_id", ""),
            )
            for row in self._storage.list_categories(_force_refresh=force_refresh)
        )
        transactions = tuple(
            LedgerTransaction(
                id=row["id"], date=date.fromisoformat(row["txn_date"]),
                kind=row["kind"], amount=Decimal(row["amount"]),
                account_id=row["account_id"], to_account_id=row.get("to_account_id", ""),
                category_id=row.get("category_id", ""), payee_id=row.get("payee_id", ""),
                payee=row.get("payee", ""), description=row.get("description", ""),
                reference=row.get("reference", ""),
                receipt_count=len(decode_receipt_references(row.get("receipt_references", ""))),
                tag_ids=tuple(row.get("tag_ids", ())), tags=tuple(row.get("tags", ())),
                created_at=row.get("created_at", ""), source_type=row.get("source_type", ""),
                source_id=row.get("source_id", ""),
                recurring_schedule_id=row.get("recurring_schedule_id", ""),
                recurring_scheduled_date=(
                    date.fromisoformat(row["recurring_scheduled_date"])
                    if row.get("recurring_scheduled_date") else None
                ),
                recurring_source_kind=row.get("recurring_source_kind", ""),
                recurring_occurrence_type=row.get("recurring_occurrence_type", ""),
            )
            for row in self._storage.list_transactions(_force_refresh=force_refresh)
        )
        journals = tuple(
            LedgerJournal(
                id=row["id"], date=date.fromisoformat(row["txn_date"]),
                description=row.get("description", ""), created_at=row.get("created_at", ""),
                updated_at=row.get("updated_at", ""),
                postings=tuple(
                    LedgerPosting(
                        id=line["id"], target_type=line["target_type"],
                        target_id=line["target_id"], side=line["side"],
                        amount=Decimal(line["amount"]), position=int(line["position"]),
                        payee_id=line.get("payee_id", ""), payee=line.get("payee", ""),
                        description=line.get("description", ""),
                    )
                    for line in row["postings"]
                ),
            )
            for row in self._storage.list_journal_entries(_force_refresh=force_refresh)
        )
        return LedgerSnapshot(accounts, categories, transactions, journals)
