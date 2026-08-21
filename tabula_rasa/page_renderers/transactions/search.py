"""Pure helpers for searching the visible transaction ledger fields."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import TypeVar


SEARCHABLE_TRANSACTION_FIELDS = (
    "Type",
    "Account",
    "To account",
    "Category",
    "Payee",
    "Description",
    "Reference",
    "ID",
)

Row = TypeVar("Row", bound=Mapping[str, object])


def _searchable_text(value: object) -> str:
    if value is None or isinstance(value, Real) and math.isnan(value):
        return ""
    return str(value).casefold()


def filter_transaction_rows(rows: Sequence[Row], query: str) -> list[Row]:
    """Return rows whose visible text contains the trimmed query.

    An empty or whitespace-only query is intentionally a no-op.  The helper
    receives the already-rendered ledger rows, so receipt metadata, dates, and
    amounts cannot accidentally become searchable.
    """
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return list(rows)
    return [
        row
        for row in rows
        if any(
            normalized_query in _searchable_text(row.get(field))
            for field in SEARCHABLE_TRANSACTION_FIELDS
        )
    ]
