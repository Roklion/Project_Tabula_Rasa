from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from tabula_rasa.page_renderers.transactions.search import filter_transaction_rows


SEARCH_FIELDS = (
    "Type",
    "Account",
    "To account",
    "Category",
    "Payee",
    "Description",
    "Reference",
    "ID",
)


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
            "Description": "January retainer",
            "Amount": 1250.0,
            "Receipt": "📎",
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

    assert filter_transaction_rows(rows, f"  {value.upper()}  ") == [
        row for row in rows if value.casefold() in str(row[field]).casefold()
    ]


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_empty_or_whitespace_search_preserves_rows(
    rows: list[dict[str, object]], query: str
) -> None:
    assert filter_transaction_rows(rows, query) == rows


def test_search_preserves_falsy_visible_values():
    rows = [{"Type": "Expense", "Reference": 0, "ID": 0}]

    assert filter_transaction_rows(rows, "0") == rows


@pytest.mark.parametrize(
    "missing_value", [float("nan"), Decimal("NaN"), Decimal("sNaN")]
)
def test_search_ignores_nan_values(missing_value: object):
    rows = [{"Type": "Expense", "Reference": missing_value, "ID": 1}]

    assert filter_transaction_rows(rows, "nan") == []


def test_search_handles_non_float_real_values():
    rows = [{"Type": "Expense", "Reference": Fraction(1, 3), "ID": 1}]

    assert filter_transaction_rows(rows, "1/3") == rows


@pytest.mark.parametrize("query", ["2026-01-02", "1250", "📎", "receipt-file.pdf"])
def test_search_excludes_date_amount_receipt_and_drive_metadata(
    rows: list[dict[str, object]], query: str
) -> None:
    assert filter_transaction_rows(rows, query) == []


def test_search_returns_all_matching_rows_and_does_not_mutate_input(
    rows: list[dict[str, object]],
) -> None:
    original_rows = list(rows)

    result = filter_transaction_rows(rows, "account")

    assert [row["ID"] for row in result] == [
        "txn-acme-1042",
        "txn-transfer-7",
    ]
    assert rows == original_rows
