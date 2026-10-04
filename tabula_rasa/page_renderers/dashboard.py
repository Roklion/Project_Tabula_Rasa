"""Dashboard page rendering and its explicit page context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st
import pandas as pd

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.hierarchy import ordered_accounts
from tabula_rasa.ledger_presentation import balances_frame, money
from tabula_rasa.ledger_records import combine_ledger_entries, ledger_summary_frame
from tabula_rasa.ledger_reporting import profit_and_loss
from tabula_rasa.presentation import render_global_footer, render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


_CLASSIFICATION_ORDER = {"Asset": 0, "Liability": 1, "Equity": 2}

_DASHBOARD_RESPONSIVE_CSS = """
<style>
/* Container queries follow the available content width, including sidebar state. */
.st-key-dashboard_detail {
    container-type: inline-size;
}

@container (max-width: 1020px) {
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
    services: ApplicationServices | None = None


def _sorted_dashboard_balances(
    balances: pd.DataFrame, accounts: list[dict]
) -> pd.DataFrame:
    """Order dashboard balances by accounting classification, then account."""
    classification_rank = balances["Classification"].map(_CLASSIFICATION_ORDER)
    account_order = {
        str(account.get("id") or ""): rank
        for rank, account in enumerate(ordered_accounts(accounts))
    }
    return (
        balances.assign(
            _classification_rank=classification_rank.fillna(
                len(_CLASSIFICATION_ORDER)
            ),
            _account_sort_key=balances["ID"].map(account_order).fillna(
                len(account_order)
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
        journals = context.storage.list_journal_entries()
        monthly_totals = profit_and_loss(
            transactions, start=month_start, end=today, journals=journals, categories=categories
        )
        balances = balances_frame(accounts, transactions, journals=journals)
    except StorageError as error:
        st.error(str(error))
        render_global_footer()
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
                st.caption("Latest eight entries" if journals else "Latest eight transactions")
                recent = ledger_summary_frame(
                    combine_ledger_entries(transactions, journals)[:8], accounts, categories,
                )
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
                            "Date": st.column_config.TextColumn(width=70),
                            "Type": st.column_config.TextColumn(width=55),
                            "Payee": st.column_config.TextColumn(width=65),
                            "Category": st.column_config.TextColumn(width=125),
                            "Account": st.column_config.TextColumn(width=130),
                            "Amount": st.column_config.NumberColumn(
                                format="$%.2f", width=75
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
                        "Account": st.column_config.TextColumn(width=160),
                        "Classification": st.column_config.TextColumn(width=80),
                        "Type": st.column_config.TextColumn(width=70),
                        "Balance": st.column_config.NumberColumn(
                            format="$%.2f", width=80
                        ),
                    },
                )
