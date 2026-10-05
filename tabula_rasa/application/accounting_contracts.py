"""Persistence-neutral ports for simple transactions and journal entries."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol, TypedDict, NotRequired

from .contracts import ExpectedRecord
from tabula_rasa.transaction import TransactionReferences


class TransactionRecord(TypedDict):
    id: str
    txn_date: str
    kind: str
    amount: str
    account_id: str
    to_account_id: str
    category_id: str
    payee_id: str
    description: str
    reference: str
    created_at: str
    tag_ids: list[str] | str
    receipt_references: list[dict[str, Any]] | str
    payee: NotRequired[str]
    tags: NotRequired[list[str]]
    source_type: NotRequired[str]
    source_id: NotRequired[str]
    recurring_schedule_id: NotRequired[str]
    recurring_scheduled_date: NotRequired[str]
    recurring_source_kind: NotRequired[str]
    recurring_occurrence_type: NotRequired[str]
    baseline: NotRequired[str]


class JournalPosting(TypedDict):
    id: str
    parent_entry_id: str
    position: int | str
    target_type: str
    target_id: str
    side: str
    amount: str
    payee_id: str
    description: str
    payee: NotRequired[str]


class JournalEntry(TypedDict):
    id: str
    txn_date: str
    description: str
    created_at: str
    updated_at: str
    postings: list[JournalPosting]
    total_debits: NotRequired[str]
    total_credits: NotRequired[str]
    baseline: NotRequired[str]


# A narrow mutation callback lets the service apply domain rules and inline
# reference coordination after the adapter's fresh/stale checks, within its
# existing mutation boundary. No locks, rows, ranges or provider clients leak.
BuildTransaction = Callable[
    [TransactionReferences, Mapping[str, Any] | None], Mapping[str, Any]
]


class TransactionRepository(Protocol):
    """One profile's transactions; confirmed results or safe failures only.

    Create checks stable identity before invoking build. Update/delete check
    expected values against fresh data. Build receives fresh references and
    the current record (None for create), exactly once. Implementations own
    serialization, cache invalidation and bounded uncertain-write recovery.
    Bulk operations use the same domain rules against their fresh selection.
    Generic update/delete/bulk operations reject derived projections; source
    workflows retain ownership. Recurring provenance is immutable.
    """

    def prepare_workspace(self) -> None:
        """Prepare aggregate reads used by the transaction workspace."""
        ...

    def list(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        kind: str | None = None,
        account_ids: Iterable[str] | None = None,
        fresh: bool = False,
    ) -> list[TransactionRecord]: ...

    def create(
        self, transaction_id: str, *, build: BuildTransaction
    ) -> TransactionRecord: ...

    def update(
        self,
        transaction_id: str,
        *,
        build: BuildTransaction,
        expected: ExpectedRecord | None = None,
    ) -> TransactionRecord: ...

    def delete(
        self, transaction_id: str, *, expected: ExpectedRecord | None = None
    ) -> None: ...

    def bulk_update(
        self,
        transaction_ids: Sequence[str],
        *,
        expected: Sequence[ExpectedRecord],
        changes: Mapping[str, Any],
    ) -> dict[str, str]: ...

    def bulk_delete(
        self,
        transaction_ids: Sequence[str],
        *,
        expected: Sequence[ExpectedRecord],
    ) -> dict[str, str]: ...


class JournalRepository(Protocol):
    """Entries/postings with stable identities and complete expected snapshots.

    Mutations repeat shared domain reference validation using fresh records,
    enforce global posting identity uniqueness and expected-entry equality,
    and persist the whole entry. Infrastructure owns failure reconciliation.
    """

    def list(
        self, *, start: str | None = None, end: str | None = None, fresh: bool = False
    ) -> list[JournalEntry]: ...

    def get(self, entry_id: str, *, fresh: bool = False) -> JournalEntry: ...

    def create(
        self,
        *,
        entry_id: str,
        txn_date: str,
        description: str,
        postings: Sequence[Mapping[str, Any]],
    ) -> JournalEntry: ...

    def update(
        self,
        entry_id: str,
        *,
        expected: ExpectedRecord,
        txn_date: str | None = None,
        description: str | None = None,
        postings: Sequence[Mapping[str, Any]] | None = None,
    ) -> JournalEntry: ...

    def delete(self, entry_id: str, *, expected: ExpectedRecord) -> None: ...
