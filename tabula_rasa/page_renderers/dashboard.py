"""Dashboard page rendering and its explicit page context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st

from tabula_rasa.ledger_presentation import balances_frame, ledger_frame, money
from tabula_rasa.ledger_reporting import profit_and_loss
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


@dataclass(frozen=True)
class DashboardContext:
    """Dependencies explicitly provided by the application shell."""

    profile_key: str
    storage: GoogleSheetsStorage


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
    left, right = st.columns([1.6, 1], gap="large")
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
                        "Amount": st.column_config.NumberColumn(format="$%.2f")
                    },
                )
    with right:
        with st.container(key="dashboard_balances"):
            st.subheader("Account balances")
            st.caption("Current balances by account")
            st.dataframe(
                balances[["Account", "Classification", "Type", "Balance"]],
                hide_index=True,
                width="stretch",
                column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
            )
