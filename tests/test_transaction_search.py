from __future__ import annotations

from copy import deepcopy

import pytest

from tabula_rasa.ledger_records import search_ledger_entries
from tabula_rasa.page_renderers.transactions.ledger_filters import (
    transaction_is_source_driven,
    transaction_type_label,
)


SEARCH_FIELDS = (
    "Type",
    "Account",
    "To account",
    "Category",
    "Payee",
    "Tags",
    "Description",
    "Reference",
    "ID",
)


def _search_rows(rows, query):
    """Exercise the live logical-entry search with rendered simple-row summaries."""
    entries = [{"id": row["ID"]} for row in rows]
    return search_ledger_entries(entries, rows, [], [], query)


@pytest.fixture
def rows() -> list[dict[str, object]]:
    return [
        {
            "Date": "2026-01-02",
            "Type": "Income",
            "Account": "Operating account",
            "To account": "",
            "Category": "Consulting",
            "Payee": "Acme customer",
            "Tags": "Project Alpha, Client",
            "Description": "January retainer",
            "Amount": 1250.0,
            "Receipt": "📎",
            "receipt_filename": "receipt-file.pdf",
            "drive_file_id": "hidden-drive-token",
            "Reference": "INV-1042",
            "ID": "txn-acme-1042",
        },
        {
            "Date": "2026-01-03",
            "Type": "Transfer",
            "Account": "Operating account",
            "To account": "Reserve account",
            "Category": "",
            "Payee": "",
            "Description": "Move tax reserve",
            "Amount": 300.0,
            "Receipt": "",
            "Reference": "MOVE-7",
            "ID": "txn-transfer-7",
        },
    ]


@pytest.mark.parametrize("field", SEARCH_FIELDS)
def test_search_matches_each_supported_field(
    rows: list[dict[str, object]], field: str
) -> None:
    value = next(str(row[field]) for row in rows if row[field])

    assert _search_rows(rows, f"  {value.upper()}  ") == [
        {"id": row["ID"]} for row in rows if value.casefold() in str(row.get(field, "")).casefold()
    ]


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_empty_or_whitespace_search_preserves_rows(
    rows: list[dict[str, object]], query: str
) -> None:
    assert _search_rows(rows, query) == [{"id": row["ID"]} for row in rows]


def test_search_preserves_zero_text_in_visible_fields():
    rows = [{"Type": "Expense", "Reference": "0", "ID": "zero"}]

    assert _search_rows(rows, "0") == [{"id": "zero"}]


@pytest.mark.parametrize("query", ["2026-01-02", "1250", "📎", "receipt-file.pdf", "hidden-drive-token"])
def test_search_excludes_date_amount_receipt_and_drive_metadata(
    rows: list[dict[str, object]], query: str
) -> None:
    assert _search_rows(rows, query) == []


def test_search_returns_all_matching_rows_and_does_not_mutate_input(
    rows: list[dict[str, object]],
) -> None:
    original_rows = deepcopy(rows)

    result = _search_rows(rows, "account")

    assert [row["id"] for row in result] == [
        "txn-acme-1042",
        "txn-transfer-7",
    ]
    assert rows == original_rows


def test_search_matches_any_displayed_tag() -> None:
    rows = [
        {"ID": "one", "Tags": "Project Alpha, Client"},
        {"ID": "two", "Tags": "Internal"},
    ]

    assert [row["id"] for row in _search_rows(rows, "client")] == [
        "one"
    ]


def test_ledger_type_label_shows_both_recurring_indicators() -> None:
    transaction = {
        "source_type": "mixed_use_expense",
        "source_id": "source-1",
        "recurring_schedule_id": "schedule-1",
    }
    assert transaction_type_label("Expense", transaction) == (
        "Expense · Mixed-use · Recurring"
    )


def test_depreciation_source_protection_normalizes_external_source_type() -> None:
    transaction = {"source_type": "  DEPRECIATION  ", "source_id": "asset-1"}

    assert transaction_is_source_driven(transaction)
    assert transaction_type_label("Expense", transaction) == "Expense · Depreciation"
