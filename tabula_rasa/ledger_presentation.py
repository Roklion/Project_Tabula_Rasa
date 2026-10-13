"""Side-effect-free data presentation helpers shared by ledger pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from tabula_rasa.hierarchy import hierarchy_paths
from tabula_rasa.ledger_reporting import account_balances


def money(value: float) -> str:
    return f"${value:,.2f}"


def transaction_type_label(value: object, transaction: Mapping[str, object]) -> str:
    """Add durable mixed-use and recurring indicators to a ledger type."""
    mixed_use = bool(str(transaction.get("source_type") or "").strip() == "mixed_use_expense"
                     and str(transaction.get("source_id") or "").strip())
    suffix = " · ".join(label for label, enabled in (
        ("Mixed-use", mixed_use),
        ("Recurring", bool(str(transaction.get("recurring_schedule_id") or "").strip())),
        ("Depreciation", str(transaction.get("source_type") or "").strip().lower() == "depreciation"),
    ) if enabled)
    return f"{value} · {suffix}" if suffix else str(value)


def _tag_names(
    transaction: Mapping[str, object],
    tags: Sequence[Mapping[str, object]] | Mapping[str, object] | None,
) -> str:
    """Return a compact display value for a transaction's optional Tags."""
    raw_names = transaction.get("tags")
    if isinstance(raw_names, str):
        return raw_names
    if isinstance(raw_names, Sequence) and not isinstance(raw_names, (str, bytes)):
        names = [
            str(item.get("name") or "").strip()
            if isinstance(item, Mapping)
            else str(item).strip()
            for item in raw_names
        ]
        return ", ".join(name for name in names if name)
    if not tags:
        return ""
    by_id = {}
    if isinstance(tags, Mapping):
        for tag_id, tag in tags.items():
            by_id[str(tag_id).strip()] = (
                str(tag.get("name") or "").strip()
                if isinstance(tag, Mapping)
                else str(tag).strip()
            )
    else:
        by_id = {
            str(tag.get("id") or "").strip(): str(tag.get("name") or "").strip()
            for tag in tags
        }
    raw_ids = transaction.get("tag_ids", ())
    if isinstance(raw_ids, str):
        return ""
    if not isinstance(raw_ids, Sequence):
        return ""
    return ", ".join(
        by_id[str(tag_id).strip()]
        for tag_id in raw_ids
        if str(tag_id).strip() in by_id
    )


def ledger_frame(
    transactions: list[dict],
    accounts: list[dict],
    categories: list[dict],
    *,
    display_paths: bool = True,
    tags: Sequence[Mapping[str, object]] | Mapping[str, object] | None = None,
) -> pd.DataFrame:
    account_names = (
        hierarchy_paths(accounts)
        if display_paths
        else {account["id"]: account["name"] for account in accounts}
    )
    category_names = (
        hierarchy_paths(categories)
        if display_paths
        else {category["id"]: category["name"] for category in categories}
    )
    rows = []
    for transaction in transactions:
        row = {
            "ID": transaction["id"],
            "Date": transaction["txn_date"],
            "Type": transaction["kind"],
            "Account": account_names.get(transaction["account_id"], "Unknown"),
            "To account": account_names.get(transaction.get("to_account_id"), ""),
            "Category": category_names.get(transaction.get("category_id"), ""),
            "Payee": transaction.get("payee", ""),
            "Description": transaction.get("description", ""),
            "Reference": transaction.get("reference", ""),
            "Amount": float(transaction["amount"]),
        }
        if tags is not None:
            row["Tags"] = _tag_names(transaction, tags)
        rows.append(row)
    columns = [
        "ID",
        "Date",
        "Type",
        "Account",
        "To account",
        "Category",
        "Payee",
        "Description",
        "Reference",
        "Amount",
    ]
    if tags is not None:
        columns.append("Tags")
    return pd.DataFrame(
        rows,
        columns=columns,
    )


def balances_frame(
    accounts: list[dict], transactions: list[dict], *, journals=(),
) -> pd.DataFrame:
    rows = account_balances(accounts, transactions, journals=journals)
    account_paths = hierarchy_paths(accounts)
    return pd.DataFrame(
        [
            {
                "ID": account["id"],
                "Account": account_paths.get(account["id"], account["name"]),
                "Type": account["type"],
                "Classification": account["classification"],
                "Active": account["active"],
                "Balance": account["balance"],
            }
            for account in rows
        ],
        columns=["ID", "Account", "Type", "Classification", "Active", "Balance"],
    )
