"""Sheets schedule persistence and process-local reconciliation coordination."""

from tabula_rasa.application.recurring_contracts import RecurringSnapshot
from tabula_rasa.errors import StorageConflictError
from tabula_rasa.recurring import SCHEDULE_FIELDS
from tabula_rasa.transaction import TransactionReferences, utc_now


class GoogleSheetsRecurringRepository:
    def __init__(self, storage):
        self._storage = storage

    def _references(self):
        storage = self._storage
        return TransactionReferences(
            storage._account_lookup(force_refresh=True),
            storage._category_lookup(force_refresh=True),
            storage._payee_lookup(force_refresh=True),
            storage._tag_lookup(force_refresh=True),
        )

    def snapshot(self, *, fresh=False):
        storage = self._storage
        return RecurringSnapshot(
            [
                dict(row.values)
                for row in storage._rows("RecurringSchedules", force_refresh=fresh)
            ],
            [
                dict(row.values)
                for row in storage._rows("Transactions", force_refresh=fresh)
            ],
            [
                dict(row.values)
                for row in storage._rows("MixedUseExpenses", force_refresh=fresh)
            ],
        )

    def create(self, schedule_id, *, build):
        storage = self._storage
        with storage._workbook_locks.ledger:
            existing = {
                str(row.values.get("id")): row.values
                for row in storage._rows("RecurringSchedules", force_refresh=True)
            }
            record = dict(build(self._references(), existing.get(schedule_id)))
            if schedule_id in existing:
                if not storage._logical_record_matches(
                    existing[schedule_id],
                    record,
                    ignored=frozenset(
                        {"created_at", "updated_at", "attention_code", "attention_at"}
                    ),
                ):
                    raise StorageConflictError(
                        "Recurring schedule ID is already in use"
                    )
            else:
                storage._append("RecurringSchedules", record)
            return record

    def update(self, schedule_id, *, expected, build):
        storage = self._storage
        with storage._workbook_locks.ledger:
            row = storage._find_row("RecurringSchedules", schedule_id)
            if expected is not None and any(
                str(expected.get(field, "") or "")
                != str(row.values.get(field, "") or "")
                for field in SCHEDULE_FIELDS
                if field not in {"updated_at", "attention_code", "attention_at"}
            ):
                raise StorageConflictError(
                    "The recurring schedule changed; refresh it before editing."
                )
            record = dict(build(self._references(), dict(row.values)))
            storage._replace_row("RecurringSchedules", row, record)
            return record

    def reconcile(self, process):
        from dataclasses import replace

        with self._storage._workbook_locks.ledger:
            snapshot = self.snapshot(fresh=True)
            return process(replace(snapshot, references=self._references()))

    def attention(self, schedule_id, code):
        storage = self._storage
        row = storage._find_row("RecurringSchedules", schedule_id)
        if code or row.values.get("attention_code") or row.values.get("attention_at"):
            record = {
                **row.values,
                "attention_code": code,
                "attention_at": utc_now() if code else "",
            }
            storage._replace_row("RecurringSchedules", row, record)

    def create_expense(self, data, *, mixed=False):
        if mixed:
            return self._storage.create_recurring_mixed_use_expense(**data)
        return self._storage.create_recurring_expense(**data)

    def convert_expense(self, identity, changes, *, expected, mixed=False):
        if mixed:
            return self._storage.create_recurring_expense_from_mixed_use(
                identity, **changes, expected_source=expected
            )
        return self._storage.create_recurring_expense_from_transaction(
            identity, **changes, expected_transaction=expected
        )


def recurring_service_for_storage(storage):
    """Compatibility callers share the same profile-bound service owners."""
    from tabula_rasa.application.mixed_use import MixedUseService
    from tabula_rasa.application.recurring import RecurringService
    from tabula_rasa.infrastructure.google_sheets import transaction_service_for_storage
    from tabula_rasa.infrastructure.google_sheets_mixed_use import (
        GoogleSheetsMixedUseRepository,
    )

    transactions = transaction_service_for_storage(storage)
    mixed_use = MixedUseService(
        GoogleSheetsMixedUseRepository(storage), transactions=transactions
    )
    return RecurringService(
        GoogleSheetsRecurringRepository(storage),
        transactions=transactions,
        mixed_use=mixed_use,
    )
