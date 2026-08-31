from __future__ import annotations

import importlib
from unittest.mock import patch

import streamlit as st

from tabula_rasa.hierarchy import hierarchy_paths
from tabula_rasa.page_renderers import accounts, categories, hierarchy_ui
from tabula_rasa.page_renderers.transactions import renderer as transactions_renderer


def test_hierarchy_page_modules_import_without_rendering_or_bootstrap() -> None:
    with (
        patch.object(st, "markdown") as markdown,
        patch.object(st, "error") as error,
        patch.object(st, "secrets", create=True) as secrets,
    ):
        importlib.reload(accounts)
        importlib.reload(categories)
        importlib.reload(hierarchy_ui)

    markdown.assert_not_called()
    error.assert_not_called()
    secrets.assert_not_called()


def test_hierarchy_responsive_css_scopes_table_and_form_behavior() -> None:
    assert '[data-testid="stDataFrameResizable"]' in (
        hierarchy_ui._HIERARCHY_RESPONSIVE_CSS
    )
    assert '[data-testid="stHorizontalBlock"]' in (
        hierarchy_ui._HIERARCHY_RESPONSIVE_CSS
    )
    assert "overflow-x: auto" in hierarchy_ui._HIERARCHY_RESPONSIVE_CSS
    assert "max-width: 100%" in hierarchy_ui._HIERARCHY_RESPONSIVE_CSS


def test_account_page_frame_preserves_columns_states_and_rollups() -> None:
    account_frame, account_ids, account_by_id = accounts._account_frame(
        [
            {
                "id": "root",
                "name": "Operating",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": 100.0,
                "active": True,
                "parent_id": "",
            },
            {
                "id": "child",
                "name": "Petty cash",
                "type": "Cash",
                "classification": "Asset",
                "opening_balance": 25.0,
                "active": False,
                "parent_id": "root",
            },
        ],
        [],
    )

    assert list(account_frame.columns) == [
        "Account",
        "Layer",
        "Parent",
        "Classification",
        "Type",
        "Active",
        "Balance",
        "Transaction count",
    ]
    assert account_ids == ["root", "child"]
    assert set(account_by_id) == {"root", "child"}
    assert account_frame.loc[0, "Balance"] == 125.0
    assert account_frame.loc[0, "Active"] == "Active"
    assert account_frame.loc[1, "Active"] == "Inactive"
    assert account_frame.loc[1, "Layer"] == "Layer 2"


def test_transaction_account_choices_follow_accounts_hierarchy_order() -> None:
    all_accounts = [
        {
            "id": "archived",
            "name": "A Archived",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": False,
            "parent_id": "",
        },
        {
            "id": "archived-child",
            "name": "Z Child",
            "type": "Cash",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": True,
            "parent_id": "archived",
        },
        {
            "id": "current",
            "name": "B Current",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": True,
            "parent_id": "",
        },
        {
            "id": "current-child",
            "name": "A Child",
            "type": "Cash",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": True,
            "parent_id": "current",
        },
        {
            "id": "other",
            "name": "C Current",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": True,
            "parent_id": "",
        },
        {
            "id": "other-child",
            "name": "B Child",
            "type": "Cash",
            "classification": "Asset",
            "opening_balance": 0.0,
            "active": True,
            "parent_id": "other",
        },
    ]

    _, account_ids, _ = accounts._account_frame(all_accounts, [])
    active_accounts = transactions_renderer._ordered_active_accounts(all_accounts)
    account_paths = hierarchy_paths(all_accounts)
    account_map = {
        account_paths[account["id"]]: account["id"]
        for account in active_accounts
    }

    assert account_ids == [
        "archived",
        "archived-child",
        "current",
        "current-child",
        "other",
        "other-child",
    ]
    assert list(account_map) == [
        "A Archived › Z Child",
        "B Current",
        "B Current › A Child",
        "C Current",
        "C Current › B Child",
    ]
    assert list(account_map.values()) == [
        "archived-child",
        "current",
        "current-child",
        "other",
        "other-child",
    ]


def test_category_page_frame_preserves_columns_paths_and_counts() -> None:
    category_frame, category_ids, category_by_id = categories._category_frame(
        [
            {"id": "travel", "name": "Travel", "kind": "Expense", "parent_id": ""},
            {
                "id": "flights",
                "name": "Flights",
                "kind": "Expense",
                "parent_id": "travel",
            },
        ],
        [{"category_id": "flights"}, {"category_id": "flights"}],
    )

    assert list(category_frame.columns) == [
        "Category",
        "Layer",
        "Parent",
        "Type",
        "Transaction count",
    ]
    assert category_ids == ["travel", "flights"]
    assert set(category_by_id) == {"travel", "flights"}
    assert category_frame.loc[1, "Category"] == "↳ Flights"
    assert category_frame.loc[1, "Parent"] == "Travel"
    assert category_frame.loc[1, "Transaction count"] == 2
