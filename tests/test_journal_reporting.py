from decimal import Decimal

import pytest

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.ledger_reporting import (
    account_balances, balance_sheet, category_activity_rollups, monthly_performance,
    profit_and_loss,
)


ACCOUNTS = [
    {"id": "cash", "name": "Cash", "type": "Cash", "classification": "Asset", "opening_balance": "200"},
    {"id": "equity", "name": "Capital", "type": "Equity", "classification": "Equity", "opening_balance": "-200"},
    {"id": "debt", "name": "Debt", "type": "Credit card", "classification": "Liability", "opening_balance": "0"},
]
CATEGORIES = [
    {"id": "office", "name": "Office", "kind": "Expense"},
    {"id": "meals", "name": "Meals", "kind": "Expense"},
    {"id": "sales", "name": "Sales", "kind": "Income"},
]


def journal(*lines, entry_id="j1", txn_date="2026-09-20"):
    return {"id": entry_id, "txn_date": txn_date, "description": "Adjustment", "postings": [
        {"id": f"{entry_id}-{index}", "parent_entry_id": entry_id, "position": index,
         "target_type": target_type, "target_id": target_id, "side": side, "amount": amount,
         "payee_id": "", "description": ""}
        for index, (target_type, target_id, side, amount) in enumerate(lines, 1)
    ]}


def test_split_expense_changes_balances_earnings_and_category_totals_once():
    entries = [journal(("category", "office", "Debit", "100.00"),
                       ("category", "meals", "Debit", "50.00"),
                       ("account", "cash", "Credit", "150.00"))]
    balances = {row["id"]: row["balance"] for row in account_balances(ACCOUNTS, [], journals=entries)}
    assert balances == {"cash": 50.0, "equity": -200.0, "debt": 0.0}
    assert profit_and_loss([], journals=entries, categories=CATEGORIES) == {"income": 0, "expenses": 150, "net": -150}
    statement = balance_sheet(ACCOUNTS, [], journals=entries, categories=CATEGORIES)
    assert statement["current_earnings"] == -150
    assert statement["total_equity"] == 50
    assert statement["difference"] == 0
    rollups = category_activity_rollups([], CATEGORIES, kind="Expense", journals=entries)
    assert {row["id"]: row["direct_total"] for row in rollups} == {"office": 100, "meals": 50}


def test_income_expense_reversal_and_liability_use_explicit_direction():
    entries = [journal(("account", "debt", "Debit", "70"),
                       ("category", "sales", "Credit", "50"),
                       ("category", "office", "Credit", "20"))]
    assert profit_and_loss([], journals=entries, categories=CATEGORIES) == {"income": 50, "expenses": -20, "net": 70}
    statement = balance_sheet(ACCOUNTS, [], journals=entries, categories=CATEGORIES)
    assert statement["total_liabilities"] == -70
    assert statement["total_equity"] == 270
    assert statement["difference"] == 0
    assert next(row for row in statement["assets"] if row["id"] == "cash")["balance"] == 200


def test_account_only_journal_and_simple_transfer_never_affect_profit():
    entries = [journal(("account", "debt", "Debit", "10"), ("account", "cash", "Credit", "10"))]
    simple = [{"id": "t1", "kind": "Transfer", "amount": "20", "account_id": "cash", "to_account_id": "debt", "txn_date": "2026-09-20"}]
    assert profit_and_loss(simple, journals=entries) == {"income": 0, "expenses": 0, "net": 0}
    assert balance_sheet(ACCOUNTS, simple, journals=entries)["difference"] == 0


def test_journal_period_and_asof_dates_apply_to_complete_entry():
    entries = [journal(("category", "office", "Debit", "5"), ("account", "cash", "Credit", "5"))]
    assert profit_and_loss([], end="2026-09-19", journals=entries, categories=CATEGORIES)["expenses"] == 0
    assert balance_sheet(ACCOUNTS, [], as_of="2026-09-19", journals=entries, categories=CATEGORIES)["current_earnings"] == 0
    assert monthly_performance([], journals=entries, categories=CATEGORIES) == [{"month": "2026-09", "income": 0, "expenses": 5}]


def test_simple_postings_have_deterministic_identity_and_balanced_direction():
    transactions = [{"id": "t1", "kind": "Expense", "amount": "1.01", "account_id": "cash", "category_id": "office"}]
    postings = list(accounting_postings(transactions))
    assert postings == list(accounting_postings(transactions))
    assert [(row["target_id"], row["side"], row["amount"]) for row in postings] == [
        ("office", "Debit", Decimal("1.01")), ("cash", "Credit", Decimal("1.01")),
    ]
    assert len({row["id"] for row in postings}) == 2


def test_journal_profit_reporting_requires_category_lookup_not_silent_omission():
    entries = [journal(("category", "office", "Debit", "5"), ("account", "cash", "Credit", "5"))]
    with pytest.raises(ValueError, match="managed category"):
        profit_and_loss([], journals=entries)
