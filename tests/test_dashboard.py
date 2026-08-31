from __future__ import annotations

import importlib
from unittest.mock import patch

import streamlit as st

from tabula_rasa.ledger_presentation import balances_frame, ledger_frame
from tabula_rasa.page_renderers import dashboard


def test_dashboard_module_import_does_not_render_or_bootstrap() -> None:
    with (
        patch.object(st, "markdown") as markdown,
        patch.object(st, "error") as error,
        patch.object(st, "secrets", create=True) as secrets,
    ):
        imported = importlib.reload(dashboard)

    assert imported.render_dashboard is not None
    markdown.assert_not_called()
    error.assert_not_called()
    secrets.assert_not_called()


def test_dashboard_context_requires_selected_profile_and_storage() -> None:
    storage = object()

    context = dashboard.DashboardContext("north", storage)  # type: ignore[arg-type]

    assert context.profile_key == "north"
    assert context.storage is storage


def test_dashboard_frames_preserve_visible_table_fields() -> None:
    accounts = [
        {
            "id": "checking",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "active": True,
            "opening_balance": "100.00",
        }
    ]
    categories = [{"id": "sales", "name": "Sales", "kind": "Income"}]
    transactions = [
        {
            "id": "income-1",
            "txn_date": "2026-08-01",
            "kind": "Income",
            "amount": "25.00",
            "account_id": "checking",
            "to_account_id": "",
            "category_id": "sales",
        }
    ]

    activity = ledger_frame(transactions, accounts, categories)
    balances = balances_frame(accounts, transactions)

    assert list(activity.columns) == [
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
    assert list(balances[["Account", "Classification", "Type", "Balance"]]) == [
        "Account",
        "Classification",
        "Type",
        "Balance",
    ]


def test_empty_balances_frame_preserves_dashboard_columns() -> None:
    balances = balances_frame([], [])

    assert list(balances.columns) == [
        "ID",
        "Account",
        "Type",
        "Classification",
        "Active",
        "Balance",
    ]


def test_dashboard_balances_sort_by_classification_then_account() -> None:
    accounts = [
            {
                "id": "capital",
                "name": "Capital",
                "type": "Equity",
                "classification": "Equity",
                "active": True,
                "opening_balance": "0.00",
            },
            {
                "id": "payable",
                "name": "Payable",
                "type": "Credit card",
                "classification": "Liability",
                "active": True,
                "opening_balance": "0.00",
            },
            {
                "id": "savings",
                "name": "Apple",
                "parent_id": "checking",
                "type": "Bank",
                "classification": "Asset",
                "active": True,
                "opening_balance": "0.00",
            },
            {
                "id": "checking",
                "name": "zebra",
                "type": "Bank",
                "classification": "Asset",
                "active": True,
                "opening_balance": "0.00",
            },
    ]
    balances = balances_frame(accounts, [])

    sorted_balances = dashboard._sorted_dashboard_balances(balances, accounts)

    assert list(sorted_balances["Classification"]) == [
        "Asset",
        "Asset",
        "Liability",
        "Equity",
    ]
    assert list(sorted_balances["Account"]) == [
        "zebra › Apple",
        "zebra",
        "Payable",
        "Capital",
    ]
