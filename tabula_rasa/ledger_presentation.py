"""Side-effect-free data presentation helpers shared by ledger pages."""

from __future__ import annotations

import pandas as pd

from tabula_rasa.hierarchy import hierarchy_paths
from tabula_rasa.ledger_reporting import account_balances


def money(value: float) -> str:
    return f"${value:,.2f}"


def ledger_frame(
    transactions: list[dict],
    accounts: list[dict],
    categories: list[dict],
    *,
    display_paths: bool = True,
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
    rows = [
        {
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
        for transaction in transactions
    ]
    return pd.DataFrame(
        rows,
        columns=[
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
        ],
    )


def balances_frame(accounts: list[dict], transactions: list[dict]) -> pd.DataFrame:
    rows = account_balances(accounts, transactions)
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
