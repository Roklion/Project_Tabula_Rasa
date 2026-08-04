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


def rollup_account_values(
    accounts: Iterable[Mapping[str, Any]], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Add each Layer 2 value to its Layer 1 parent's value."""
    records = [dict(account) for account in accounts]
    rollups = {
        str(account.get("id") or "").strip(): values.get(
            str(account.get("id") or "").strip(), 0
        )
        for account in records
        if str(account.get("id") or "").strip()
    }
    for account in records:
        account_id = str(account.get("id") or "").strip()
        parent_id = str(account.get("parent_id") or "").strip()
        if account_id and parent_id in rollups:
            rollups[parent_id] += values.get(account_id, 0)
    return rollups


def balance_sheet(
    accounts: Iterable[Mapping[str, Any]],
    transactions: Iterable[Mapping[str, Any]],
    *,
    as_of: date | str | None = None,
) -> dict[str, Any]:
    """Return classified balances and an accounting-equation check."""
    transaction_rows = [
        dict(transaction)
        for transaction in transactions
        if as_of is None
        or str(transaction["txn_date"]) <= str(_date_text(as_of))
    ]
    balance_rows = account_balances(accounts, transaction_rows)
    sections: dict[str, list[dict[str, Any]]] = {
        "Asset": [],
        "Liability": [],
        "Equity": [],
    }
    totals = {classification: Decimal("0") for classification in sections}
    for account in balance_rows:
        classification = str(account.get("classification", "Asset")).title()
        if classification not in sections:
            classification = "Asset"
        raw_balance = _decimal(account["balance"])
        presented_balance = (
            raw_balance if classification == "Asset" else -raw_balance
        )
        sections[classification].append(
            {
                "id": str(account.get("id") or "").strip(),
                "name": account["name"],
                "type": account["type"],
                "parent_id": str(account.get("parent_id") or "").strip(),
                "balance": float(presented_balance),
                "direct_balance": float(presented_balance),
                "rollup_balance": float(presented_balance),
            }
        )
        totals[classification] += presented_balance

    for rows in sections.values():
        rollup_balances = rollup_account_values(
            rows,
            {row["id"]: _decimal(row["direct_balance"]) for row in rows},
        )
        for row in rows:
            row["rollup_balance"] = float(rollup_balances[row["id"]])

    current_earnings = sum(
        (
            _decimal(transaction["amount"])
            if transaction["kind"] == "Income"
            else -_decimal(transaction["amount"])
            if transaction["kind"] == "Expense"
            else Decimal("0")
        )
        for transaction in transaction_rows
    )
    total_equity = totals["Equity"] + current_earnings
    difference = totals["Asset"] - totals["Liability"] - total_equity
    return {
        "assets": sections["Asset"],
        "liabilities": sections["Liability"],
        "equity": sections["Equity"],
        "current_earnings": float(current_earnings),
        "total_assets": float(totals["Asset"]),
        "total_liabilities": float(totals["Liability"]),
        "total_equity": float(total_equity),
        "difference": float(difference),
    }


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
    return [
        {"category": row["category"], "total": row["rollup_total"]}
        for row in sorted(
            (
                row
                for row in category_activity_rollups(
                    transactions,
                    categories,
                    kind="Expense",
                    start=start,
                    end=end,
                )
                if row["layer"] == 1
            ),
            key=lambda row: (
                -row["rollup_total"],
                row["category"].casefold(),
            ),
        )
    ]


def category_activity_rollups(
    transactions: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    start: date | str | None = None,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    """Return Layer 1 rollups and Layer 2 direct activity without duplication."""
    category_rows = []
    for category in categories:
        row = dict(category)
        row["id"] = str(row.get("id") or "").strip()
        row["parent_id"] = str(row.get("parent_id") or "").strip()
        category_rows.append(row)
    by_id = {
        category_id: category
        for category in category_rows
        if (category_id := str(category.get("id") or ""))
        and category.get("kind") == kind
    }
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for transaction in transactions:
        if transaction["kind"] != kind or not _in_period(transaction, start, end):
            continue
        raw_category_id = transaction.get("category_id")
        category_id = (
            str(raw_category_id).strip() if raw_category_id is not None else ""
        )
        totals[category_id if category_id in by_id else ""] += _decimal(
            transaction["amount"]
        )

    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []
    valid_parent_ids = {
        str(category.get("id") or "")
        for category in category_rows
        if category.get("kind") == kind and category.get("id")
    }
    for category in category_rows:
        category_id = str(category.get("id") or "")
        if category.get("kind") != kind or not category_id:
            continue
        raw_parent_id = category.get("parent_id")
        parent_id = str(raw_parent_id).strip() if raw_parent_id else ""
        if parent_id and parent_id in valid_parent_ids:
            children[parent_id].append(category)
        else:
            roots.append(category)

    rows: list[dict[str, Any]] = []
    visited: set[str] = set()
    for root in sorted(
        roots,
        key=lambda item: str(item.get("name") or "").casefold(),
    ):
        root_id = str(root.get("id") or "")
        child_rows = sorted(
            children.get(root_id, []),
            key=lambda item: str(item.get("name") or "").casefold(),
        )
        direct_total = totals[root_id]
        child_totals = [
            totals[str(child.get("id") or "")] for child in child_rows
        ]
        if direct_total == 0 and all(total == 0 for total in child_totals):
            continue
        rollup_total = direct_total + sum(child_totals, start=Decimal("0"))
        rows.append(
            {
                "id": root_id,
                "category": root.get("name") or "",
                "parent_id": "",
                "layer": 1,
                "direct_total": float(direct_total),
                "rollup_total": float(rollup_total),
            }
        )
        visited.add(root_id)
        rows.extend(
            {
                "id": str(child.get("id") or ""),
                "category": child.get("name") or "",
                "parent_id": root_id,
                "layer": 2,
                "direct_total": float(totals[str(child.get("id") or "")]),
                "rollup_total": float(totals[str(child.get("id") or "")]),
            }
            for child in child_rows
            if totals[str(child.get("id") or "")] != 0
        )
        visited.update(str(child.get("id") or "") for child in child_rows)

    for category in sorted(
        category_rows,
        key=lambda item: str(item.get("name") or "").casefold(),
    ):
        category_id = str(category.get("id") or "")
        if (
            category.get("kind") != kind
            or not category_id
            or category_id in visited
        ):
            continue
        direct_total = totals[category_id]
        if direct_total != 0:
            rows.append(
                {
                    "id": category.get("id", ""),
                    "category": category.get("name") or "",
                    "parent_id": "",
                    "layer": 1,
                    "direct_total": float(direct_total),
                    "rollup_total": float(direct_total),
                }
            )

    if totals[""] != 0:
        uncategorized_total = float(totals[""])
        rows.append(
            {
                "id": "",
                "category": "Uncategorized",
                "parent_id": "",
                "layer": 1,
                "direct_total": uncategorized_total,
                "rollup_total": uncategorized_total,
            }
        )
    return rows
