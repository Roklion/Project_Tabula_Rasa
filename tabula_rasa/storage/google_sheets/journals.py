"""Balanced multi-line journal persistence for Google Sheets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from tabula_rasa.journal import JournalValidationError, normalize_journal_postings

from .base import _StoredRow
from .errors import (
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    _mutation_guidance,
)
from .schema import WORKSHEET_HEADERS
from .validation import (
    _as_bool,
    _clean_text,
    _iso_date,
    _utc_now,
    _validate_journal_tables,
)


_ENTRY_FIELDS = WORKSHEET_HEADERS["JournalEntries"]
_POSTING_FIELDS = WORKSHEET_HEADERS["JournalPostings"]


def _stored_values(fields: Sequence[str], record: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(record.get(field, "") or "") for field in fields}


class JournalsMixin:
    """Storage operations for one parent journal and its posting set."""

    def _journal_snapshot(
        self, *, force_refresh: bool
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, _StoredRow],
        dict[str, _StoredRow],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        snapshot = self._snapshot(
            (
                "JournalEntries",
                "JournalPostings",
                "Accounts",
                "Categories",
                "Payees",
            ),
            force_refresh=force_refresh,
        )
        entry_rows = self._rows_by_id(snapshot["JournalEntries"], "JournalEntries")
        posting_rows = self._rows_by_id(
            snapshot["JournalPostings"], "JournalPostings"
        )
        account_rows = self._rows_by_id(snapshot["Accounts"], "Accounts")
        category_rows = self._rows_by_id(snapshot["Categories"], "Categories")
        payee_rows = self._rows_by_id(snapshot["Payees"], "Payees")
        accounts = {
            record_id: dict(row.values) for record_id, row in account_rows.items()
        }
        categories = {
            record_id: dict(row.values) for record_id, row in category_rows.items()
        }
        payees = {
            record_id: dict(row.values) for record_id, row in payee_rows.items()
        }
        complete = _validate_journal_tables(
            [row.values for row in entry_rows.values()],
            [row.values for row in posting_rows.values()],
            account_ids=accounts,
            category_ids=categories,
            payee_ids=payees,
        )
        for entry in complete:
            for posting in entry["postings"]:
                payee_id = posting["payee_id"]
                posting["payee"] = payees.get(payee_id, {}).get("name", "")
        return complete, entry_rows, posting_rows, accounts, categories, payees

    @staticmethod
    def _rows_by_id(
        rows: Iterable[_StoredRow], title: str
    ) -> dict[str, _StoredRow]:
        result: dict[str, _StoredRow] = {}
        for row in rows:
            record_id = _clean_text(
                row.values.get("id"), f"{title} ID", required=True
            )
            if record_id in result:
                raise StorageValidationError(f"Duplicate ID detected in {title}")
            result[record_id] = row
        return result

    @staticmethod
    def _entry_signature(entry: Mapping[str, Any]) -> tuple[Any, ...]:
        postings = entry.get("postings")
        if not isinstance(postings, Sequence) or isinstance(postings, (str, bytes)):
            postings = ()

        def posting_position(posting: Any) -> tuple[int, int]:
            if not isinstance(posting, Mapping):
                return (1, 0)
            try:
                return (0, int(str(posting.get("position", 0) or 0)))
            except (TypeError, ValueError):
                return (1, 0)

        def posting_signature(posting: Any) -> tuple[str, ...]:
            if not isinstance(posting, Mapping):
                # A caller-provided stale baseline is untrusted input. Make it
                # deterministically different from every valid stored posting
                # so edit/delete report a normal conflict instead of exposing
                # a raw type error.
                return ("<invalid-journal-posting>",)
            return tuple(str(posting.get(field, "") or "") for field in _POSTING_FIELDS)

        ordered = sorted(
            postings,
            key=posting_position,
        )
        return (
            tuple(str(entry.get(field, "") or "") for field in _ENTRY_FIELDS),
            tuple(posting_signature(posting) for posting in ordered),
        )

    @classmethod
    def _entry_matches(
        cls, actual: Mapping[str, Any], expected: Mapping[str, Any]
    ) -> bool:
        return cls._entry_signature(actual) == cls._entry_signature(expected)

    @staticmethod
    def _find_complete_entry(
        entries: Iterable[Mapping[str, Any]], entry_id: str
    ) -> dict[str, Any] | None:
        matches = [dict(entry) for entry in entries if entry.get("id") == entry_id]
        if len(matches) > 1:
            raise StorageValidationError("Journal entry IDs must be unique")
        return matches[0] if matches else None

    @staticmethod
    def _public_entry(
        entry: Mapping[str, Any], payees: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, Any]:
        result = dict(entry)
        postings = []
        for source in entry.get("postings", ()):
            posting = dict(source)
            posting["payee"] = payees.get(posting.get("payee_id", ""), {}).get(
                "name", ""
            )
            postings.append(posting)
        result["postings"] = postings
        result["total_debits"] = format(
            sum(
                (
                    Decimal(posting["amount"])
                    for posting in postings
                    if posting["side"] == "Debit"
                ),
                Decimal("0.00"),
            ),
            "f",
        )
        result["total_credits"] = format(
            sum(
                (
                    Decimal(posting["amount"])
                    for posting in postings
                    if posting["side"] == "Credit"
                ),
                Decimal("0.00"),
            ),
            "f",
        )
        return result

    def list_journal_entries(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        start_text = _iso_date(start) if start is not None else None
        end_text = _iso_date(end) if end is not None else None
        entries, *_ = self._journal_snapshot(force_refresh=_force_refresh)
        result = [
            entry
            for entry in entries
            if (start_text is None or entry["txn_date"] >= start_text)
            and (end_text is None or entry["txn_date"] <= end_text)
        ]
        return sorted(
            result,
            key=lambda entry: (
                entry["txn_date"],
                entry["created_at"],
                entry["id"],
            ),
            reverse=True,
        )

    def get_journal_entry(
        self, entry_id: str, *, _force_refresh: bool = False
    ) -> dict[str, Any]:
        entry_id = _clean_text(entry_id, "Journal entry ID", required=True)
        entries, *_ = self._journal_snapshot(force_refresh=_force_refresh)
        entry = self._find_complete_entry(entries, entry_id)
        if entry is None:
            raise StorageNotFoundError("Journal entry no longer exists")
        return entry

    @staticmethod
    def _prepare_postings(
        entry_id: str,
        postings: Iterable[Mapping[str, Any]],
        *,
        accounts: Mapping[str, Mapping[str, Any]],
        categories: Mapping[str, Mapping[str, Any]],
        payees: Mapping[str, Mapping[str, Any]],
        original_entry: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        source_postings = list(postings)
        if any(
            _clean_text(posting.get("parent_entry_id"), "Journal parent entry ID")
            not in {"", entry_id}
            for posting in source_postings
        ):
            raise StorageValidationError(
                "Journal posting belongs to a different parent entry"
            )
        try:
            normalized = normalize_journal_postings(source_postings)
        except JournalValidationError as exc:
            raise StorageValidationError(str(exc)) from exc
        original_postings = {
            str(posting.get("id", "")): posting
            for posting in (original_entry or {}).get("postings", ())
        }
        prepared: list[dict[str, Any]] = []
        for posting in normalized:
            posting_id = posting["id"]
            original = original_postings.get(posting_id, {})
            target_type = posting["target_type"]
            target_id = posting["target_id"]
            if target_type == "account":
                account = accounts.get(target_id)
                if account is None:
                    raise StorageValidationError("Journal account does not exist")
                same_historical_target = (
                    original.get("target_type") == "account"
                    and original.get("target_id") == target_id
                )
                if not _as_bool(account.get("active"), "Account active") and not same_historical_target:
                    raise StorageValidationError("Journal account is inactive")
            elif target_id not in categories:
                raise StorageValidationError("Journal category does not exist")

            payee_id = posting["payee_id"]
            if payee_id:
                payee = payees.get(payee_id)
                if payee is None:
                    raise StorageValidationError("Journal payee does not exist")
                same_historical_payee = original.get("payee_id") == payee_id
                if not _as_bool(payee.get("active"), "Payee active") and not same_historical_payee:
                    raise StorageValidationError("Journal payee is inactive")
            prepared.append({**posting, "parent_entry_id": entry_id})
        return prepared

    @staticmethod
    def _append_cells_request(
        *, sheet_id: int, headers: Sequence[str], records: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        return {
            "appendCells": {
                "sheetId": sheet_id,
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "stringValue": str(record.get(header, "") or "")
                                }
                            }
                            for header in headers
                        ]
                    }
                    for record in records
                ],
                "fields": "userEnteredValue",
            }
        }

    def _replace_cells_request(
        self, title: str, row: _StoredRow, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        headers = self._headers(title)
        return {
            "updateCells": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "startRowIndex": row.row_number - 1,
                    "endRowIndex": row.row_number,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(headers),
                },
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "stringValue": str(record.get(header, "") or "")
                                }
                            }
                            for header in headers
                        ]
                    }
                ],
                "fields": "userEnteredValue",
            }
        }

    def _delete_row_request(self, title: str, row: _StoredRow) -> dict[str, Any]:
        return {
            "deleteDimension": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "dimension": "ROWS",
                    "startIndex": row.row_number - 1,
                    "endIndex": row.row_number,
                }
            }
        }

    def _write_journal_once(
        self,
        operation: str,
        requests: Sequence[Mapping[str, Any]],
        readback_applied: Callable[[], bool],
    ) -> None:
        """Run one journal batch and one readback only after an uncertain result."""
        titles = ("JournalEntries", "JournalPostings")
        try:
            self._batch_update_spreadsheet(requests)
        except StorageUnavailableError as error:
            for title in titles:
                self._invalidate(title)
            if not error.retryable:
                raise
            try:
                applied = readback_applied()
            except (StorageError, OSError) as read_error:
                for title in titles:
                    self._invalidate(title)
                raise StorageUnavailableError(
                    _mutation_guidance(operation), retryable=False
                ) from read_error
            except Exception:
                for title in titles:
                    self._invalidate(title)
                raise
            for title in titles:
                self._invalidate(title)
            if applied:
                return
            raise StorageUnavailableError(
                _mutation_guidance(operation), retryable=False
            ) from error
        else:
            for title in titles:
                self._invalidate(title)

    def create_journal_entry(
        self,
        *,
        entry_id: str,
        txn_date: date | str,
        description: str = "",
        postings: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        with self._workbook_locks.ledger:
            entry_id = _clean_text(entry_id, "Journal entry ID", required=True)
            (
                entries,
                _entry_rows,
                posting_rows,
                accounts,
                categories,
                payees,
            ) = self._journal_snapshot(force_refresh=True)
            existing = self._find_complete_entry(entries, entry_id)
            prepared_postings = self._prepare_postings(
                entry_id,
                postings,
                accounts=accounts,
                categories=categories,
                payees=payees,
                original_entry=existing,
            )
            if existing is not None:
                repeated = {
                    **existing,
                    "txn_date": _iso_date(txn_date),
                    "description": _clean_text(description, "Journal description"),
                    "postings": prepared_postings,
                }
                if self._entry_signature(existing)[1] == self._entry_signature(repeated)[1] and all(
                    existing[field] == repeated[field]
                    for field in ("id", "txn_date", "description")
                ):
                    return existing
                raise StorageConflictError(
                    "Journal entry ID already exists with different data"
                )
            duplicate_posting_ids = set(posting_rows) & {
                posting["id"] for posting in prepared_postings
            }
            if duplicate_posting_ids:
                raise StorageConflictError("Journal posting ID already exists")
            timestamp = _utc_now()
            entry = {
                "id": entry_id,
                "txn_date": _iso_date(txn_date),
                "description": _clean_text(description, "Journal description"),
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            final_entry = {**entry, "postings": prepared_postings}
            entry_headers = self._headers("JournalEntries")
            posting_headers = self._headers("JournalPostings")
            requests = [
                self._append_cells_request(
                    sheet_id=self._sheet_id("JournalEntries"),
                    headers=entry_headers,
                    records=[entry],
                ),
                self._append_cells_request(
                    sheet_id=self._sheet_id("JournalPostings"),
                    headers=posting_headers,
                    records=prepared_postings,
                ),
            ]

            def applied() -> bool:
                current = self.get_journal_entry(entry_id, _force_refresh=True)
                return self._entry_matches(current, final_entry)

            self._write_journal_once("journal create", requests, applied)
            return self._public_entry(final_entry, payees)

    def edit_journal_entry(
        self,
        entry_id: str,
        *,
        expected_entry: Mapping[str, Any],
        txn_date: date | str | None = None,
        description: str | None = None,
        postings: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._workbook_locks.ledger:
            entry_id = _clean_text(entry_id, "Journal entry ID", required=True)
            (
                entries,
                entry_rows,
                posting_rows,
                accounts,
                categories,
                payees,
            ) = self._journal_snapshot(force_refresh=True)
            current = self._find_complete_entry(entries, entry_id)
            if current is None:
                raise StorageNotFoundError("Journal entry no longer exists")
            if not self._entry_matches(current, expected_entry):
                raise StorageConflictError(
                    "The journal entry changed; refresh it before editing."
                )
            updated_postings = self._prepare_postings(
                entry_id,
                postings if postings is not None else current["postings"],
                accounts=accounts,
                categories=categories,
                payees=payees,
                original_entry=current,
            )
            current_posting_ids = {
                posting["id"] for posting in current["postings"]
            }
            collisions = (
                {posting["id"] for posting in updated_postings}
                & (set(posting_rows) - current_posting_ids)
            )
            if collisions:
                raise StorageConflictError("Journal posting ID already exists")
            updated_parent = {
                "id": entry_id,
                "txn_date": _iso_date(
                    current["txn_date"] if txn_date is None else txn_date
                ),
                "description": _clean_text(
                    current["description"] if description is None else description,
                    "Journal description",
                ),
                "created_at": current["created_at"],
                "updated_at": current["updated_at"],
            }
            candidate = {**updated_parent, "postings": updated_postings}
            if self._entry_matches(current, candidate):
                return current
            updated_parent["updated_at"] = _utc_now()
            final_entry = {**updated_parent, "postings": updated_postings}
            current_rows = [posting_rows[posting_id] for posting_id in current_posting_ids]
            requests: list[dict[str, Any]] = [
                self._replace_cells_request(
                    "JournalEntries", entry_rows[entry_id], updated_parent
                )
            ]
            requests.extend(
                self._delete_row_request("JournalPostings", row)
                for row in sorted(
                    current_rows, key=lambda item: item.row_number, reverse=True
                )
            )
            requests.append(
                self._append_cells_request(
                    sheet_id=self._sheet_id("JournalPostings"),
                    headers=self._headers("JournalPostings"),
                    records=updated_postings,
                )
            )

            def applied() -> bool:
                latest = self.get_journal_entry(entry_id, _force_refresh=True)
                return self._entry_matches(latest, final_entry)

            self._write_journal_once("journal edit", requests, applied)
            return self._public_entry(final_entry, payees)

    def delete_journal_entry(
        self, entry_id: str, *, expected_entry: Mapping[str, Any]
    ) -> None:
        with self._workbook_locks.ledger:
            entry_id = _clean_text(entry_id, "Journal entry ID", required=True)
            entries, entry_rows, posting_rows, *_ = self._journal_snapshot(
                force_refresh=True
            )
            current = self._find_complete_entry(entries, entry_id)
            if current is None:
                raise StorageNotFoundError("Journal entry no longer exists")
            if not self._entry_matches(current, expected_entry):
                raise StorageConflictError(
                    "The journal entry changed; refresh it before deleting."
                )
            current_posting_ids = {
                posting["id"] for posting in current["postings"]
            }
            requests = [
                self._delete_row_request("JournalPostings", row)
                for row in sorted(
                    (posting_rows[posting_id] for posting_id in current_posting_ids),
                    key=lambda item: item.row_number,
                    reverse=True,
                )
            ]
            requests.append(
                self._delete_row_request("JournalEntries", entry_rows[entry_id])
            )

            def applied() -> bool:
                latest, *_ = self._journal_snapshot(force_refresh=True)
                return self._find_complete_entry(latest, entry_id) is None

            self._write_journal_once("journal deletion", requests, applied)


__all__ = ["JournalsMixin"]
