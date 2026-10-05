"""Small ports owned by the application capabilities that consume them."""

from collections.abc import Iterable, Mapping, Sequence
from typing import NotRequired, Protocol, TypedDict


class AccountRecord(TypedDict):
    """The existing account shape, including normalized read values."""

    id: str
    name: str
    type: str
    classification: str
    opening_balance: str | float
    active: str | bool
    created_at: str
    parent_id: str
    baseline: NotRequired[str]


class AccountChanges(TypedDict, total=False):
    name: str
    type: str
    classification: str
    opening_balance: object
    active: bool | str
    parent_id: str | None


class CategoryRecord(TypedDict):
    """A stable category identity and its existing two-level hierarchy."""

    id: str
    name: str
    kind: str
    parent_id: str
    baseline: NotRequired[str]


class CategoryChanges(TypedDict, total=False):
    name: str
    kind: str
    parent_id: str | None


class ManagedReferenceRecord(TypedDict):
    """Payee and tag records retain stable identities and display names."""

    id: str
    name: str
    active: str
    created_at: str
    baseline: NotRequired[str]


class ManagedReferenceChanges(TypedDict, total=False):
    name: str
    active: bool | str


class ManagedMutationResult(TypedDict):
    status: str
    count: NotRequired[str]


ExpectedRecord = Mapping[str, object]
ExpectedRecords = Iterable[ExpectedRecord] | Mapping[str, ExpectedRecord]


class AccountRepository(Protocol):
    """One profile's account persistence and final mutation invariants.

    Implementations check fresh uniqueness, hierarchy, and references at the
    mutation boundary and own uncertain-write recovery and cache invalidation.
    Services must not add reads or retries around these operations.
    """

    def list(self, *, active_only: bool = True) -> list[AccountRecord]: ...

    def create(
        self,
        name: str,
        account_type: str,
        opening_balance: str,
        *,
        classification: str,
        parent_id: str,
    ) -> AccountRecord: ...

    def update(
        self, account_id: str, *, changes: AccountChanges,
        expected: ExpectedRecord | None = None,
    ) -> AccountRecord: ...


class CategoryRepository(Protocol):
    """One profile's categories and final fresh hierarchy/reference checks.

    Persistence owns uniqueness, current relationships, cache invalidation,
    and uncertain-write recovery. Services add no independent reads or retries.
    """

    def list(self, kind: str | None = None) -> list[CategoryRecord]: ...

    def create(self, name: str, kind: str, *, parent_id: str) -> CategoryRecord: ...

    def update(
        self, category_id: str, *, changes: CategoryChanges,
        expected: ExpectedRecord | None = None,
    ) -> CategoryRecord: ...

    def delete(self, category_id: str, *, expected: ExpectedRecord | None = None) -> None: ...


class PayeeRepository(Protocol):
    """One profile's managed payees, preserving references on mutation.

    Implementations enforce normalized uniqueness, fresh references, and supplied
    expected records. They own persistence recovery and cache invalidation.
    """

    def list(self, *, active_only: bool = False) -> list[ManagedReferenceRecord]: ...

    def create(self, name: str, *, active: bool = True) -> ManagedReferenceRecord: ...

    def update(
        self,
        payee_id: str,
        *,
        changes: ManagedReferenceChanges,
        expected: ExpectedRecord | None = None,
    ) -> ManagedReferenceRecord: ...

    def merge(
        self,
        target_id: str,
        source_ids: Sequence[str],
        *,
        expected: ExpectedRecords | None = None,
    ) -> ManagedMutationResult: ...

    def remove(
        self, payee_id: str, *, expected: ExpectedRecord | None = None
    ) -> ManagedMutationResult: ...


class TagRepository(Protocol):
    """One profile's managed tags, preserving all tagged references.

    Implementations enforce normalized uniqueness, fresh references, and supplied
    expected records. They own persistence recovery and cache invalidation.
    """

    def list(self, *, active_only: bool = False) -> list[ManagedReferenceRecord]: ...

    def create(self, name: str, *, active: bool = True) -> ManagedReferenceRecord: ...

    def update(
        self,
        tag_id: str,
        *,
        changes: ManagedReferenceChanges,
        expected: ExpectedRecord | None = None,
    ) -> ManagedReferenceRecord: ...

    def merge(
        self,
        target_id: str,
        source_ids: Sequence[str],
        *,
        expected: ExpectedRecords | None = None,
    ) -> ManagedMutationResult: ...

    def remove(
        self, tag_id: str, *, expected: ExpectedRecord | None = None
    ) -> ManagedMutationResult: ...


class LedgerSetupRepository(Protocol):
    """The current ledger's display identity and supported initial defaults.

    Implementations own persistence and propagate failures without reporting
    success. This initial compatibility port leaves the existing default rules
    in the backend until the setup workflow moves to the application layer.
    """

    @property
    def ledger_name(self) -> str: ...

    def ensure_defaults(self) -> dict[str, int]:
        """Return counts of created accounts/categories, or fail."""
        ...
