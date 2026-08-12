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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total balance", money(float(balances["Balance"].sum())))
    c2.metric("Income this month", money(monthly_totals["income"]))
    c3.metric("Expenses this month", money(monthly_totals["expenses"]))
    c4.metric("Net this month", money(monthly_totals["net"]))
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Recent activity")
        recent = ledger_frame(transactions[:8], accounts, categories)
        if recent.empty:
            st.info("No transactions yet. Add your first one from Transactions.")
        else:
            display = recent[
                ["Date", "Type", "Payee", "Category", "Account", "Amount"]
            ].copy()
            display["Amount"] = display.apply(
                lambda row: -row.Amount if row.Type == "Expense" else row.Amount,
                axis=1,
            )
            st.dataframe(
                display,
                hide_index=True,
                width="stretch",
                column_config={
                    "Amount": st.column_config.NumberColumn(format="$%.2f")
                },
            )
    with right:
        st.subheader("Account balances")
        st.dataframe(
            balances[["Account", "Classification", "Type", "Balance"]],
            hide_index=True,
            width="stretch",
            column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
        )
