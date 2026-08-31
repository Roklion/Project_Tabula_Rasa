"""Dashboard page rendering and its explicit page context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st
import pandas as pd

from tabula_rasa.ledger_presentation import balances_frame, ledger_frame, money
from tabula_rasa.ledger_reporting import profit_and_loss
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


_CLASSIFICATION_ORDER = {"Asset": 0, "Liability": 1, "Equity": 2}

_DASHBOARD_RESPONSIVE_CSS = """
<style>
@media (max-width: 1450px) {
    .st-key-dashboard_detail [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    .st-key-dashboard_detail [data-testid="stColumn"] {
        flex: 1 1 100%;
        min-width: 100%;
    }
}
</style>
"""


@dataclass(frozen=True)
class DashboardContext:
    """Dependencies explicitly provided by the application shell."""

    profile_key: str
    storage: GoogleSheetsStorage


def _sorted_dashboard_balances(
    balances: pd.DataFrame, accounts: list[dict]
) -> pd.DataFrame:
    """Order dashboard balances by accounting classification, then account."""
    classification_rank = balances["Classification"].map(_CLASSIFICATION_ORDER)
    account_names = {
        str(account.get("id") or ""): str(account.get("name") or "")
        for account in accounts
    }
    return (
        balances.assign(
            _classification_rank=classification_rank.fillna(
                len(_CLASSIFICATION_ORDER)
            ),
            _account_sort_key=(
                balances["ID"]
                .map(account_names)
                .fillna(balances["Account"])
                .astype(str)
                .str.casefold()
            ),
        )
        .sort_values(
            ["_classification_rank", "_account_sort_key"],
            kind="stable",
            ignore_index=True,
        )
        .drop(columns=["_classification_rank", "_account_sort_key"])
    )


def render_dashboard(context: DashboardContext) -> None:
    """Render the Dashboard for the selected business profile."""
    render_page_header(
        "Your books at a glance",
        "A current view of cash, income, and spending.",
    )
    try:
        today = date.today()
        month_start = today.replace(day=1)
        context.storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        accounts = context.storage.list_accounts(active_only=False)
        categories = context.storage.list_categories()
        transactions = context.storage.list_transactions()
        monthly_totals = profit_and_loss(
            transactions, start=month_start, end=today
        )
        balances = balances_frame(accounts, transactions)
    except StorageError as error:
        st.error(str(error))
        st.stop()

    with st.container(key="dashboard_metrics"):
        c1, c2, c3, c4 = st.columns([1.25, 1, 1, 1], gap="small")
        with c1:
            with st.container(key="dashboard_total_balance"):
                st.metric("Total balance", money(float(balances["Balance"].sum())))
        with c2:
            st.metric("Income this month", money(monthly_totals["income"]))
        with c3:
            st.metric("Expenses this month", money(monthly_totals["expenses"]))
        with c4:
            with st.container(key="dashboard_net_month"):
                st.metric("Net this month", money(monthly_totals["net"]))
    st.markdown(_DASHBOARD_RESPONSIVE_CSS, unsafe_allow_html=True)
    with st.container(key="dashboard_detail"):
        left, right = st.columns([1.35, 1], gap="small")
        with left:
            with st.container(key="dashboard_activity"):
                st.subheader("Recent activity")
                st.caption("Latest eight transactions")
                recent = ledger_frame(transactions[:8], accounts, categories)
                if recent.empty:
                    st.info("No transactions yet. Add your first one from Transactions.")
                else:
                    display = recent[
                        ["Date", "Type", "Payee", "Category", "Account", "Amount"]
                    ].copy()
                    expense_rows = display["Type"] == "Expense"
                    display.loc[expense_rows, "Amount"] *= -1
                    st.dataframe(
                        display,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Date": st.column_config.TextColumn(width=80),
                            "Type": st.column_config.TextColumn(width=65),
                            "Payee": st.column_config.TextColumn(width=75),
                            "Category": st.column_config.TextColumn(width=145),
                            "Account": st.column_config.TextColumn(width=150),
                            "Amount": st.column_config.NumberColumn(
                                format="$%.2f", width=80
                            ),
                        },
                    )
        with right:
            with st.container(key="dashboard_balances"):
                st.subheader("Account balances")
                st.caption("Current balances by account")
                dashboard_balances = _sorted_dashboard_balances(balances, accounts)
                st.dataframe(
                    dashboard_balances[
                        ["Account", "Classification", "Type", "Balance"]
                    ],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Account": st.column_config.TextColumn(width=170),
                        "Classification": st.column_config.TextColumn(width=90),
                        "Type": st.column_config.TextColumn(width=75),
                        "Balance": st.column_config.NumberColumn(
                            format="$%.2f", width=90
                        ),
                    },
                )
