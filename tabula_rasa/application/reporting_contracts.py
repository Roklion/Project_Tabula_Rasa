"""Domain read models and the reporting capability's persistence port.

These projections contain native dates, amounts, booleans, and collections.
They carry neither worksheet rows nor encoded cells or provider clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ReportingAccount:
    id: str
    name: str
    type: str
    classification: str
    opening_balance: Decimal
    active: bool
    parent_id: str = ""


@dataclass(frozen=True)
class ReportingCategory:
    id: str
    name: str
    kind: str
    parent_id: str = ""


@dataclass(frozen=True)
class LedgerTransaction:
    id: str
    date: date
    kind: str
    amount: Decimal
    account_id: str
    to_account_id: str = ""
    category_id: str = ""
    payee_id: str = ""
    payee: str = ""
    description: str = ""
    reference: str = ""
    receipt_count: int = 0
    tag_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: str = ""
    source_type: str = ""
    source_id: str = ""
    recurring_schedule_id: str = ""
    recurring_scheduled_date: date | None = None
    recurring_source_kind: str = ""
    recurring_occurrence_type: str = ""


@dataclass(frozen=True)
class LedgerPosting:
    id: str
    target_type: str
    target_id: str
    side: str
    amount: Decimal
    position: int
    payee_id: str = ""
    payee: str = ""
    description: str = ""


@dataclass(frozen=True)
class LedgerJournal:
    id: str
    date: date
    postings: tuple[LedgerPosting, ...]
    description: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class LedgerSnapshot:
    """One selected ledger's normalized records, including inactive accounts."""

    accounts: tuple[ReportingAccount, ...] = ()
    categories: tuple[ReportingCategory, ...] = ()
    transactions: tuple[LedgerTransaction, ...] = ()
    journals: tuple[LedgerJournal, ...] = ()


@dataclass(frozen=True)
class LedgerFilter:
    """Inclusive date range and current ledger's OR-within-target/tag filters."""

    start: date | None = None
    end: date | None = None
    kind: str | None = None
    account_ids: tuple[str, ...] = ()
    category_ids: tuple[str, ...] = ()
    tag_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LedgerEntry:
    """One complete transaction or journal, never an individually mutable posting."""

    id: str
    kind: str
    date: date
    amount: Decimal
    transaction: LedgerTransaction | None = None
    journal: LedgerJournal | None = None


@dataclass(frozen=True)
class LedgerQuery:
    snapshot: LedgerSnapshot
    entries: tuple[LedgerEntry, ...]


@dataclass(frozen=True)
class PeriodReport:
    totals: dict[str, float]
    monthly: tuple[dict[str, object], ...]
    expense_categories: tuple[dict[str, object], ...]


class LedgerQueryRepository(Protocol):
    """Read normalized domain projections for the explicitly selected ledger.

    The adapter owns fetching, caching, provider validation, and decoding. Read
    failures propagate; the service adds no retries or alternate source of truth.
    """

    def read_ledger(self, *, force_refresh: bool = False) -> LedgerSnapshot: ...
