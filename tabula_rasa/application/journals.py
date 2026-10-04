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
