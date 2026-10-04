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
