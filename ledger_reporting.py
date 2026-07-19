"""Backend-independent balance and profit-and-loss calculations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _date_text(value: date | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _in_period(
    transaction: Mapping[str, Any], start: date | str | None, end: date | str | None
) -> bool:
    transaction_date = str(transaction["txn_date"])
    start_text = _date_text(start)
    end_text = _date_text(end)
    return not (
        (start_text is not None and transaction_date < start_text)
        or (end_text is not None and transaction_date > end_text)
    )


def account_balances(
    accounts: Iterable[Mapping[str, Any]],
    transactions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Calculate balances including transfers without affecting P&L."""
    accounts = [dict(account) for account in accounts]
    balances = {
        account["id"]: _decimal(account["opening_balance"]) for account in accounts
    }
    for transaction in transactions:
        amount = _decimal(transaction["amount"])
        kind = transaction["kind"]
        source = transaction["account_id"]
        if kind == "Income":
            balances[source] += amount
        elif kind == "Expense":
            balances[source] -= amount
        elif kind == "Transfer":
            balances[source] -= amount
            balances[transaction["to_account_id"]] += amount

    return [
        {
            **account,
            "balance": float(balances[account["id"]]),
        }
        for account in sorted(accounts, key=lambda item: str(item["name"]).casefold())
    ]


def profit_and_loss(
    transactions: Iterable[Mapping[str, Any]],
    *,
    start: date | str | None = None,
    end: date | str | None = None,
) -> dict[str, float]:
    """Return income, expense, and net totals; transfers are excluded."""
    income = Decimal("0")
    expenses = Decimal("0")
    for transaction in transactions:
        if not _in_period(transaction, start, end):
            continue
        if transaction["kind"] == "Income":
            income += _decimal(transaction["amount"])
        elif transaction["kind"] == "Expense":
            expenses += _decimal(transaction["amount"])
    return {
        "income": float(income),
        "expenses": float(expenses),
        "net": float(income - expenses),
    }


def monthly_performance(
    transactions: Iterable[Mapping[str, Any]],
    *,
    start: date | str | None = None,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expenses": Decimal("0")}
    )
    for transaction in transactions:
        if not _in_period(transaction, start, end):
            continue
        month = str(transaction["txn_date"])[:7]
        if transaction["kind"] == "Income":
            totals[month]["income"] += _decimal(transaction["amount"])
        elif transaction["kind"] == "Expense":
            totals[month]["expenses"] += _decimal(transaction["amount"])
    return [
        {
            "month": month,
            "income": float(values["income"]),
            "expenses": float(values["expenses"]),
        }
        for month, values in sorted(totals.items())
    ]


def expenses_by_category(
    transactions: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
    *,
    start: date | str | None = None,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    category_names = {
        category["id"]: category["name"] for category in categories
    }
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for transaction in transactions:
        if transaction["kind"] != "Expense" or not _in_period(
            transaction, start, end
        ):
            continue
        name = category_names.get(transaction.get("category_id"), "Uncategorized")
        totals[str(name)] += _decimal(transaction["amount"])
    return [
        {"category": category, "total": float(total)}
        for category, total in sorted(
            totals.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
