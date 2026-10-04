"""Balanced journal workflows shared by the current UI and future API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from tabula_rasa.journal import normalize_journal_input
from tabula_rasa.ledger_validation import iso_date
from tabula_rasa.reference_data import clean_text

from .accounting_contracts import JournalRepository, JournalEntry
from .contracts import ExpectedRecord


class JournalService:
    """Normalize/balance postings; persist through the selected entry port."""

    def __init__(self, repository: JournalRepository) -> None:
        self._repository = repository

    def list(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        fresh: bool = False,
    ) -> list[JournalEntry]:
        return self._repository.list(
            start=iso_date(start) if start is not None else None,
            end=iso_date(end) if end is not None else None,
            fresh=fresh,
        )

    def get(self, entry_id: str, *, fresh: bool = False) -> JournalEntry:
        return self._repository.get(
            clean_text(entry_id, "Journal entry ID", required=True), fresh=fresh
        )

    def create(
        self,
        *,
        entry_id: str,
        txn_date: date | str,
        description: str = "",
        postings: Iterable[Mapping[str, Any]],
    ) -> JournalEntry:
        entry_id = clean_text(entry_id, "Journal entry ID", required=True)
        return self._repository.create(
            entry_id=entry_id,
            txn_date=iso_date(txn_date),
            description=clean_text(description, "Journal description"),
            postings=normalize_journal_input(entry_id, postings),
        )

    def update(
        self,
        entry_id: str,
        *,
        expected: ExpectedRecord,
        txn_date: date | str | None = None,
        description: str | None = None,
        postings: Iterable[Mapping[str, Any]] | None = None,
    ) -> JournalEntry:
        entry_id = clean_text(entry_id, "Journal entry ID", required=True)
        return self._repository.update(
            entry_id,
            expected=expected,
            txn_date=iso_date(txn_date) if txn_date is not None else None,
            description=clean_text(description, "Journal description")
            if description is not None
            else None,
            postings=normalize_journal_input(entry_id, postings)
            if postings is not None
            else None,
        )

    def delete(self, entry_id: str, *, expected: ExpectedRecord) -> None:
        return self._repository.delete(
            clean_text(entry_id, "Journal entry ID", required=True), expected=expected
        )

    def prepare_depreciation(self, asset, references, transactions, *, through):
        """Prepare the existing Simple Ledger postings for an asset's due periods.

        A repository invokes this with fresh asset/history/references inside its
        source mutation boundary. This preserves the supported one-record event
        representation while keeping accounting orchestration provider neutral.
        """
        from tabula_rasa.asset import prepare_asset
        from tabula_rasa.depreciation_posting import (
            asset_schedule,
            depreciation_entry_id,
            validate_depreciation_accounts,
            validate_depreciation_history,
        )
        from tabula_rasa.errors import StorageConflictError
        from tabula_rasa.transaction import prepare_transaction

        asset = prepare_asset(
            asset, asset_id=asset["id"], created_at=asset["created_at"]
        )
        validate_depreciation_accounts(
            asset,
            references.accounts,
            references.categories,
            required=True,
            active=True,
        )
        history = [
            record
            for record in transactions
            if str(record.get("source_type") or "").strip().lower() == "depreciation"
            and str(record.get("source_id") or "").strip() == asset["id"]
        ]
        validate_depreciation_history(
            [asset], history, references.accounts, references.categories
        )
        existing = {}
        for record in transactions:
            identity = str(record.get("id") or "").strip()
            if identity in existing:
                raise StorageConflictError("Transaction IDs must be unique")
            existing[identity] = record
        pending = []
        for period in asset_schedule(asset):
            if period.scheduled_date.isoformat() > through:
                break
            identity = depreciation_entry_id(asset["id"], period.sequence)
            if identity in existing:
                record = existing[identity]
                if (
                    str(record.get("source_type") or "").strip().lower()
                    != "depreciation"
                    or str(record.get("source_id") or "").strip() != asset["id"]
                ):
                    raise StorageConflictError(
                        "Depreciation entry ID is already in use"
                    )
                continue

            def reject_inline(name):
                raise ValueError(
                    "Depreciation postings cannot create managed references"
                )

            record = prepare_transaction(
                dict(
                    txn_date=period.scheduled_date,
                    kind="Expense",
                    amount=period.depreciation_amount,
                    account_id=asset["accumulated_depreciation_account_id"],
                    category_id=asset["depreciation_expense_account_id"],
                    description=f"Asset depreciation · {asset['name']} · Quarter {period.sequence}",
                    reference=asset["reference"],
                ),
                transaction_id=identity,
                accounts=references.accounts,
                categories=references.categories,
                payees=references.payees,
                tags=references.tags,
                create_payee=reject_inline,
                create_tag=reject_inline,
                allow_zero_amount=True,
            )
            record.update(source_type="depreciation", source_id=asset["id"])
            pending.append(record)
        return pending
