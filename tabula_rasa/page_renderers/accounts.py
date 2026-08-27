"""Accounts hierarchy page rendering and its explicit page context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from tabula_rasa.hierarchy import (
    eligible_parent_ids,
    has_hierarchy_children,
    hierarchy_paths,
    ordered_hierarchy,
)
from tabula_rasa.ledger_presentation import balances_frame
from tabula_rasa.ledger_reporting import rollup_account_values
from tabula_rasa.page_renderers.hierarchy_ui import (
    hierarchy_layer_label,
    hierarchy_option_label,
    hierarchy_row_label,
    render_hierarchy_table,
    render_hierarchy_responsive_css,
)
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


ACCOUNT_TYPES = [
    "Bank",
    "Cash",
    "Credit card",
    "Short-term debt",
    "Equity",
    "Other",
]
ACCOUNT_CLASSIFICATIONS = ["Asset", "Liability", "Equity"]
FIXED_TYPE_CLASSIFICATIONS = {
    "Bank": "Asset",
    "Cash": "Asset",
    "Credit card": "Liability",
    "Short-term debt": "Liability",
    "Equity": "Equity",
}


@dataclass(frozen=True)
class AccountsContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]


def _account_frame(
    accounts: list[dict],
    transactions: list[dict],
) -> tuple[pd.DataFrame, list[str], dict[str, dict]]:
    balances = balances_frame(accounts, transactions)
    account_by_id = {
        str(account.get("id") or "").strip(): account
        for account in accounts
        if str(account.get("id") or "").strip()
    }
    ordered = ordered_hierarchy(accounts)
    direct_balance_by_id = balances.set_index("ID")["Balance"].to_dict()
    balance_by_id = rollup_account_values(accounts, direct_balance_by_id)
    transaction_count_by_id: dict[str, int] = {}
    for transaction in transactions:
        involved_account_ids = {
            str(transaction.get("account_id") or "").strip(),
            str(transaction.get("to_account_id") or "").strip(),
        }
        for account_id in involved_account_ids - {""}:
            transaction_count_by_id[account_id] = (
                transaction_count_by_id.get(account_id, 0) + 1
            )
    transaction_count_by_id = rollup_account_values(
        accounts, transaction_count_by_id
    )
    rows = []
    item_ids = []
    for account in ordered:
        account_id = str(account.get("id") or "").strip()
        parent_id = str(account.get("parent_id") or "").strip()
        parent = account_by_id.get(parent_id)
        item_ids.append(account_id)
        rows.append(
            {
                "Account": hierarchy_row_label(account["name"], parent_id),
                "Layer": hierarchy_layer_label(parent_id),
                "Parent": parent.get("name") or "" if parent else "",
                "Classification": account["classification"],
                "Type": account["type"],
                "Active": "Active" if account["active"] else "Inactive",
                "Balance": balance_by_id.get(account_id, 0.0),
                "Transaction count": transaction_count_by_id.get(account_id, 0),
            }
        )
    return (
        pd.DataFrame(
            rows,
            columns=[
                "Account",
                "Layer",
                "Parent",
                "Classification",
                "Type",
                "Active",
                "Balance",
                "Transaction count",
            ],
        ),
        item_ids,
        account_by_id,
    )


def _sync_edit_account_selection(account_selector_key: str) -> None:
    """Keep table and editor selection state aligned when the selector changes."""
    st.session_state["edit_account_id"] = st.session_state[account_selector_key]


def render_accounts(context: AccountsContext) -> None:
    """Render account creation, hierarchy management, and balances."""
    render_hierarchy_responsive_css()
    render_page_header(
        "Accounts", "Track bank, cash, credit card, and other manual balances."
    )
    try:
        context.storage.prefetch_worksheets("Accounts", "Transactions")
        accounts = context.storage.list_accounts(active_only=False)
        transactions = context.storage.list_transactions()
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()

    account_frame, account_ids, account_by_id = _account_frame(
        accounts, transactions
    )
    account_paths = hierarchy_paths(accounts)
    table_key = (
        f"account_table_{context.profile_key}_"
        f"{st.session_state.get('account_table_generation', 0)}"
    )
    st.subheader("Account hierarchy")
    st.caption(
        "Layer 1 rows include their direct balance and child totals; Layer 2 "
        "rows show direct values."
    )
    account_event = render_hierarchy_table(
        account_frame,
        item_ids=account_ids,
        table_key=table_key,
        selection_state_key="edit_account_id",
        empty_message="No accounts yet. Add your first account below.",
        column_config={
            "Balance": st.column_config.NumberColumn(format="$%.2f"),
            "Transaction count": st.column_config.NumberColumn(format="%d"),
        },
    )

    context.reset_widget_state_if_requested(
        "reset_add_account_form",
        keys=(
            f"new_account_name_{context.profile_key}",
            f"new_account_type_{context.profile_key}",
            f"new_account_opening_{context.profile_key}",
        ),
        prefixes=(
            f"new_account_classification_{context.profile_key}_",
            f"new_account_parent_{context.profile_key}_",
        ),
    )
    with st.expander("Add account", expanded=True):
        # The expander supplies the workflow border; keep the keyed inner
        # container as a spacing hook so the form does not become double-card.
        with st.container(key="accounts_add_form"):
            st.caption("Add a Layer 1 account or choose a compatible Layer 1 parent.")
            c1, c2, c3, c4, c5 = st.columns(5, gap="small")
            name = c1.text_input(
                "Account name", key=f"new_account_name_{context.profile_key}"
            )
            account_type = c2.selectbox(
                "Type", ACCOUNT_TYPES, key=f"new_account_type_{context.profile_key}"
            )
            classification_options = (
                [FIXED_TYPE_CLASSIFICATIONS[account_type]]
                if account_type in FIXED_TYPE_CLASSIFICATIONS
                else ACCOUNT_CLASSIFICATIONS
            )
            classification = c3.selectbox(
                "Balance-sheet classification",
                classification_options,
                key=(
                    f"new_account_classification_{context.profile_key}_"
                    f"{account_type}"
                ),
            )
            opening = c4.number_input(
                "Opening balance",
                value=0.0,
                format="%.2f",
                key=f"new_account_opening_{context.profile_key}",
                help=(
                    "Use positive balances for assets and negative balances for "
                    "liabilities and equity."
                ),
            )
            parent_options = [""] + eligible_parent_ids(
                accounts,
                compatibility_field="classification",
                compatibility_value=classification,
            )
            parent_id = c5.selectbox(
                "Parent account (optional)",
                parent_options,
                key=(
                    f"new_account_parent_{context.profile_key}_"
                    f"{classification}"
                ),
                format_func=lambda value: hierarchy_option_label(value, account_paths),
            )
            add_error = st.empty()
            if st.button("Add account", type="primary"):
                payload = {
                    "name": name,
                    "account_type": account_type,
                    "classification": classification,
                    "opening_balance": opening,
                    "parent_id": parent_id,
                }
                context.confirmed_write(
                    "create_account",
                    payload,
                    lambda: context.storage.create_account(
                        name,
                        account_type,
                        opening,
                        classification=classification,
                        parent_id=parent_id,
                    ),
                    "Account added.",
                    on_success=lambda: context.schedule_widget_reset(
                        "reset_add_account_form"
                    ),
                    report_error=add_error.error,
                )

    if accounts:
        selected_rows = account_event.selection.rows
        if st.session_state.get("edit_account_id") not in account_by_id:
            st.session_state["edit_account_id"] = account_ids[0]
        st.caption("Select an account row (or double-click it) to edit it.")
        with st.expander("Edit or deactivate account", expanded=bool(selected_rows)):
            account_selector_key = (
                f"edit_account_id_{context.profile_key}_"
                f"{st.session_state.get('workbook_data_revision', 0)}"
            )
            if (
                account_selector_key not in st.session_state
                or st.session_state[account_selector_key]
                != st.session_state["edit_account_id"]
            ):
                st.session_state[account_selector_key] = st.session_state[
                    "edit_account_id"
                ]
            account_id = st.selectbox(
                "Account to manage",
                account_ids,
                format_func=account_paths.get,
                key=account_selector_key,
                on_change=_sync_edit_account_selection,
                args=(account_selector_key,),
            )
            st.session_state["edit_account_id"] = account_id
            selected = account_by_id[account_id]
            with st.container():
                st.caption(
                    "Renaming, promotion, or reparenting keeps this account's "
                    "stable ID and transaction references."
                )
                edited_name = st.text_input(
                    "Edit account name",
                    value=selected["name"],
                    key=f"edit_account_name_{account_id}",
                )
                edited_type = st.selectbox(
                    "Edit account type",
                    ACCOUNT_TYPES,
                    index=ACCOUNT_TYPES.index(selected["type"]),
                    key=f"edit_account_type_{account_id}",
                )
                edited_classification_options = (
                    [FIXED_TYPE_CLASSIFICATIONS[edited_type]]
                    if edited_type in FIXED_TYPE_CLASSIFICATIONS
                    else ACCOUNT_CLASSIFICATIONS
                )
                edited_classification = st.selectbox(
                    "Edit balance-sheet classification",
                    edited_classification_options,
                    index=edited_classification_options.index(
                        FIXED_TYPE_CLASSIFICATIONS.get(
                            edited_type, selected["classification"]
                        )
                    ),
                    key=f"edit_account_classification_{account_id}_{edited_type}",
                )
                edited_opening = st.number_input(
                    "Edit opening balance",
                    value=float(selected["opening_balance"]),
                    format="%.2f",
                    key=f"edit_account_opening_{account_id}",
                    help=(
                        "Use positive balances for assets and negative balances for "
                        "liabilities and equity."
                    ),
                )
                edited_active = st.checkbox(
                    "Active",
                    value=selected["active"],
                    key=f"edit_account_active_{account_id}",
                )
                has_children = has_hierarchy_children(accounts, account_id)
                edited_parent_options = [""] + eligible_parent_ids(
                    accounts,
                    compatibility_field="classification",
                    compatibility_value=edited_classification,
                    item_id=account_id,
                )
                current_parent_id = str(selected.get("parent_id") or "").strip()
                edited_parent_id = st.selectbox(
                    "Edit parent account",
                    edited_parent_options,
                    index=(
                        edited_parent_options.index(current_parent_id)
                        if current_parent_id in edited_parent_options
                        else 0
                    ),
                    key=(
                        f"edit_account_parent_{context.profile_key}_{account_id}_"
                        f"{edited_classification}"
                    ),
                    format_func=lambda value: hierarchy_option_label(
                        value, account_paths
                    ),
                    disabled=has_children,
                )
                if has_children:
                    st.info(
                        "This Layer 1 account has children. Promote or reparent "
                        "those children before moving this account under a parent."
                    )
                save_error = st.empty()
                if st.button(
                    "Save account changes",
                    type="primary",
                    key=f"save_account_{account_id}",
                ):
                    payload = {
                        "id": account_id,
                        "name": edited_name,
                        "type": edited_type,
                        "classification": edited_classification,
                        "opening_balance": edited_opening,
                        "active": edited_active,
                        "parent_id": edited_parent_id,
                    }
                    context.confirmed_write(
                        "edit_account",
                        payload,
                        lambda: context.storage.edit_account(
                            account_id,
                            name=edited_name,
                            type=edited_type,
                            classification=edited_classification,
                            opening_balance=edited_opening,
                            active=edited_active,
                            parent_id=edited_parent_id,
                        ),
                        "Account updated.",
                        report_error=save_error.error,
                    )
            st.caption(
                "Accounts are deactivated rather than deleted so transaction "
                "references remain valid."
            )
