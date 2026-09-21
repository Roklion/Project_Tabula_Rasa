from __future__ import annotations

from decimal import Decimal

import pytest

from tabula_rasa.journal import JournalValidationError, normalize_journal_postings


def posting(
    posting_id: str,
    *,
    target_type: str = "account",
    target_id: str = "target-1",
    debit: object = "",
    credit: object = "",
) -> dict[str, object]:
    return {
        "id": posting_id,
        "target_type": target_type,
        "target_id": target_id,
        "debit": debit,
        "credit": credit,
        "payee_id": "",
        "description": "",
    }


def test_normalizes_balanced_editor_rows_and_ignores_blank_placeholder() -> None:
    rows = normalize_journal_postings(
        [
            posting("line-1", target_type="category", debit="100.006"),
            posting("line-2", credit="100.01"),
            {"id": "blank-line", "position": 3},
            {"id": "blank-zero", "debit": 0.0, "credit": 0.0},
        ]
    )

    assert [(row["id"], row["position"], row["side"]) for row in rows] == [
        ("line-1", 1, "Debit"),
        ("line-2", 2, "Credit"),
    ]
    assert [row["amount"] for row in rows] == ["100.01", "100.01"]


def test_normalizes_canonical_side_and_amount() -> None:
    rows = normalize_journal_postings(
        [
            {
                "id": "line-1",
                "target_type": "category",
                "target_id": "category-1",
                "side": "debit",
                "amount": Decimal("25"),
            },
            {
                "id": "line-2",
                "target_type": "account",
                "target_id": "account-1",
                "side": "CREDIT",
                "amount": "25.00",
            },
        ]
    )

    assert [(row["side"], row["amount"]) for row in rows] == [
        ("Debit", "25.00"),
        ("Credit", "25.00"),
    ]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([posting("line-1", debit="10", credit="10")], "both"),
        (
            [posting("line-1", debit="0"), posting("line-2", credit="0")],
            "one debit or credit",
        ),
        (
            [posting("line-1", debit="0.004"), posting("line-2", credit="0.004")],
            "at least one cent",
        ),
        (
            [posting("line-1", debit="NaN"), posting("line-2", credit="NaN")],
            "greater than zero",
        ),
        (
            [posting("line-1", debit="sNaN"), posting("line-2", credit="sNaN")],
            "greater than zero",
        ),
        (
            [posting("line-1", debit="10"), posting("line-2", credit="9")],
            "balance",
        ),
        (
            [posting("line-1", debit="10"), posting("line-1", credit="10")],
            "IDs must be unique",
        ),
        (
            [posting("line-1", debit="10"), {"id": "line-2", "description": "partial"}],
            "target type",
        ),
    ],
)
def test_rejects_invalid_postings(
    rows: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(JournalValidationError, match=message):
        normalize_journal_postings(rows)
