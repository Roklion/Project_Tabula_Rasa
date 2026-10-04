"""Adapt the existing Sheets facade without copying its persistence behavior."""

from collections.abc import Sequence
from typing import cast

from tabula_rasa.application.contracts import (
    AccountChanges,
    AccountRecord,
    ExpectedRecord,
    ExpectedRecords,
    ManagedMutationResult,
    ManagedReferenceChanges,
    ManagedReferenceRecord,
)
from tabula_rasa.storage import GoogleSheetsStorage

from tabula_rasa.application.accounting_contracts import (
    BuildTransaction,
    TransactionRecord,
    JournalEntry,
)


class GoogleSheetsLedgerSetupRepository:
    """Ledger setup port backed by the same facade used by transitional pages."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    @property
    def ledger_name(self) -> str:
        return self._storage.workbook_title

    def ensure_defaults(self) -> dict[str, int]:
        return self._storage.ensure_defaults()


class GoogleSheetsAccountRepository:
    """Reuse account persistence, including fresh invariants and recovery."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list(self, *, active_only: bool = True) -> list[AccountRecord]:
        return cast(
            list[AccountRecord], self._storage.list_accounts(active_only=active_only)
        )

    def create(
        self,
        name: str,
        account_type: str,
        opening_balance: str,
        *,
        classification: str,
        parent_id: str,
    ) -> AccountRecord:
        return cast(
            AccountRecord,
            self._storage.create_account(
                name,
                account_type,
                opening_balance,
                classification=classification,
                parent_id=parent_id,
            ),
        )

    def update(self, account_id: str, *, changes: AccountChanges) -> AccountRecord:
        return cast(AccountRecord, self._storage.edit_account(account_id, **changes))


class GoogleSheetsPayeeRepository:
    """Reuse the managed payee workflow and its bounded write recovery."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list(self, *, active_only: bool = False) -> list[ManagedReferenceRecord]:
        return cast(
            list[ManagedReferenceRecord],
            self._storage.list_payees(active_only=active_only),
        )

    def create(self, name: str, *, active: bool = True) -> ManagedReferenceRecord:
        return cast(
            ManagedReferenceRecord, self._storage.create_payee(name, active=active)
        )

    def update(
        self,
        payee_id: str,
        *,
        changes: ManagedReferenceChanges,
        expected: ExpectedRecord | None = None,
    ) -> ManagedReferenceRecord:
        return cast(
            ManagedReferenceRecord,
            self._storage.edit_payee(payee_id, expected_payee=expected, **changes),
        )

    def merge(
        self,
        target_id: str,
        source_ids: Sequence[str],
        *,
        expected: ExpectedRecords | None = None,
    ) -> ManagedMutationResult:
        return cast(
            ManagedMutationResult,
            self._storage.merge_payees(target_id, source_ids, expected_payees=expected),
        )

    def remove(
        self, payee_id: str, *, expected: ExpectedRecord | None = None
    ) -> ManagedMutationResult:
        return cast(
            ManagedMutationResult,
            self._storage.remove_payee(payee_id, expected_payee=expected),
        )


class GoogleSheetsTagRepository:
    """Reuse the managed tag workflow across all existing tagged records."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list(self, *, active_only: bool = False) -> list[ManagedReferenceRecord]:
        return cast(
            list[ManagedReferenceRecord],
            self._storage.list_tags(active_only=active_only),
        )

    def create(self, name: str, *, active: bool = True) -> ManagedReferenceRecord:
        return cast(
            ManagedReferenceRecord, self._storage.create_tag(name, active=active)
        )

    def update(
        self,
        tag_id: str,
        *,
        changes: ManagedReferenceChanges,
        expected: ExpectedRecord | None = None,
    ) -> ManagedReferenceRecord:
        return cast(
            ManagedReferenceRecord,
            self._storage.edit_tag(tag_id, expected_tag=expected, **changes),
        )

    def merge(
        self,
        target_id: str,
        source_ids: Sequence[str],
        *,
        expected: ExpectedRecords | None = None,
    ) -> ManagedMutationResult:
        return cast(
            ManagedMutationResult,
            self._storage.merge_tags(target_id, source_ids, expected_tags=expected),
        )

    def remove(
        self, tag_id: str, *, expected: ExpectedRecord | None = None
    ) -> ManagedMutationResult:
        return cast(
            ManagedMutationResult,
            self._storage.remove_tag(tag_id, expected_tag=expected),
        )


class GoogleSheetsTransactionRepository:
    """Run service preparation within the existing fresh mutation boundary."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list(
        self, *, start=None, end=None, kind=None, account_ids=None, fresh=False
    ) -> list[TransactionRecord]:
        return cast(
            list[TransactionRecord],
            self._storage.list_transactions(
                start=start,
                end=end,
                kind=kind,
                account_ids=account_ids,
                _force_refresh=fresh,
            ),
        )

    def create(
        self, transaction_id: str, *, build: BuildTransaction
    ) -> TransactionRecord:
        return cast(
            TransactionRecord,
            self._storage.create_transaction(
                transaction_id=transaction_id, _build=build
            ),
        )

    def update(
        self, transaction_id: str, *, build: BuildTransaction, expected=None
    ) -> TransactionRecord:
        return cast(
            TransactionRecord,
            self._storage.edit_transaction(
                transaction_id, expected_transaction=expected, _build=build
            ),
        )

    def delete(self, transaction_id: str, *, expected=None) -> None:
        self._storage.delete_transaction(transaction_id, expected_transaction=expected)

    def bulk_update(self, transaction_ids, *, expected, changes):
        return self._storage.bulk_edit_transactions(
            transaction_ids, expected_transactions=expected, changes=changes
        )

    def bulk_delete(self, transaction_ids, *, expected):
        return self._storage.bulk_delete_transactions(
            transaction_ids, expected_transactions=expected
        )


class GoogleSheetsJournalRepository:
    """Persist complete entries with the current batch and readback behavior."""

    def __init__(self, storage: GoogleSheetsStorage) -> None:
        self._storage = storage

    def list(self, *, start=None, end=None, fresh=False) -> list[JournalEntry]:
        return cast(
            list[JournalEntry],
            self._storage.list_journal_entries(
                start=start, end=end, _force_refresh=fresh
            ),
        )

    def get(self, entry_id: str, *, fresh=False) -> JournalEntry:
        return cast(
            JournalEntry,
            self._storage.get_journal_entry(entry_id, _force_refresh=fresh),
        )

    def create(self, *, entry_id, txn_date, description, postings) -> JournalEntry:
        return cast(
            JournalEntry,
            self._storage.create_journal_entry(
                entry_id=entry_id,
                txn_date=txn_date,
                description=description,
                postings=postings,
            ),
        )

    def update(
        self, entry_id, *, expected, txn_date=None, description=None, postings=None
    ) -> JournalEntry:
        return cast(
            JournalEntry,
            self._storage.edit_journal_entry(
                entry_id,
                expected_entry=expected,
                txn_date=txn_date,
                description=description,
                postings=postings,
            ),
        )

    def delete(self, entry_id, *, expected) -> None:
        self._storage.delete_journal_entry(entry_id, expected_entry=expected)
