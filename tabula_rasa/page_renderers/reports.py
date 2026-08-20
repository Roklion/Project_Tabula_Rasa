"""Reports page rendering and its explicit page context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from tabula_rasa.hierarchy import hierarchy_paths, ordered_hierarchy
from tabula_rasa.ledger_presentation import money
from tabula_rasa.ledger_reporting import (
    balance_sheet,
    category_activity_rollups,
    monthly_performance,
    profit_and_loss,
)
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


_REPORTS_RESPONSIVE_CSS = """
<style>
@media (max-width: 1100px) {
    .st-key-reports_summary_metrics [data-testid="stHorizontalBlock"],
    .st-key-reports_charts [data-testid="stHorizontalBlock"],
    .st-key-reports_statement_metrics [data-testid="stHorizontalBlock"],
    .st-key-reports_statement_tables [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    .st-key-reports_summary_metrics [data-testid="stColumn"],
    .st-key-reports_charts [data-testid="stColumn"],
    .st-key-reports_statement_metrics [data-testid="stColumn"],
    .st-key-reports_statement_tables [data-testid="stColumn"] {
        flex: 1 1 100%;
        min-width: 100%;
    }
}
</style>
"""


@dataclass(frozen=True)
class ReportsContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    report_storage_error: Callable[[StorageError], None]


def _statement_frame(
    rows: list[dict],
    *,
    current_earnings: float | None = None,
) -> pd.DataFrame:
    ordered_rows = ordered_hierarchy(rows)
    all_ids = {str(row.get("id") or "").strip() for row in ordered_rows}
    child_parent_ids = {
        parent_id
        for row in ordered_rows
        if (parent_id := str(row.get("parent_id") or "").strip())
        and parent_id in all_ids
    }
    display_rows = []
    for row in ordered_rows:
        row_id = str(row.get("id") or "").strip()
        parent_id = str(row.get("parent_id") or "").strip()
        is_child = bool(parent_id) and parent_id in all_ids
        has_children = row_id in child_parent_ids
        display_rows.append(
            {
                "Account": f'↳ {row["name"]}' if is_child else row["name"],
                "Type": (
                    row["type"]
                    if is_child or not has_children
                    else "Layer 1 total"
                ),
                "Balance": (
                    row["direct_balance"]
                    if is_child or not has_children
                    else row["rollup_balance"]
                ),
            }
        )
        if has_children and row["direct_balance"]:
            display_rows.append(
                {
                    "Account": "↳ Direct activity",
                    "Type": row["type"],
                    "Balance": row["direct_balance"],
                }
            )
    if current_earnings is not None:
        display_rows.append(
            {
                "Account": "Current earnings",
                "Type": "Calculated",
                "Balance": current_earnings,
            }
        )
    return pd.DataFrame(display_rows, columns=["Account", "Type", "Balance"])


def render_reports(context: ReportsContext) -> None:
    """Render reports for the selected business profile."""
    render_page_header(
        "Reports",
        "Analyze income and spending for a selected period, then review the balance sheet.",
    )
    st.markdown(_REPORTS_RESPONSIVE_CSS, unsafe_allow_html=True)
    st.caption("Income and expense analytics")
    c1, c2 = st.columns(2)
    start = c1.date_input(
        "From", date(date.today().year, 1, 1), key="report_start"
    )
    end = c2.date_input("To", date.today(), key="report_end")
    try:
        context.storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        transactions = context.storage.list_transactions()
        categories = context.storage.list_categories()
        accounts = context.storage.list_accounts(active_only=False)
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()
    category_paths = hierarchy_paths(categories)
    summary = profit_and_loss(transactions, start=start, end=end)
    with st.container(key="reports_summary_metrics"):
        a, b, c = st.columns(3, gap="small")
        a.metric("Income", money(summary["income"]))
        b.metric("Expenses", money(summary["expenses"]))
        c.metric("Net", money(summary["net"]))
    monthly = pd.DataFrame(
        monthly_performance(transactions, start=start, end=end)
    ).rename(columns={"month": "Month", "income": "Income", "expenses": "Expenses"})
    category_detail_rows = category_activity_rollups(
        transactions,
        categories,
        kind="Expense",
        start=start,
        end=end,
    )
    by_category = pd.DataFrame(
        [
            {"Category": row["category"], "Total": row["rollup_total"]}
            for row in sorted(
                (row for row in category_detail_rows if row["layer"] == 1),
                key=lambda row: (-row["rollup_total"], row["category"].casefold()),
            )
        ]
    )
    with st.container(key="reports_charts"):
        left, right = st.columns(2)
        with left:
            st.subheader("Monthly performance")
            if not monthly.empty:
                monthly_chart = px.bar(
                    monthly,
                    x="Month",
                    y=["Income", "Expenses"],
                    barmode="group",
                    color_discrete_sequence=["#3267D6", "#8EA5D5"],
                    labels={"value": "Amount", "variable": "Series"},
                )
                monthly_chart.update_layout(
                    height=300,
                    margin={"l": 12, "r": 12, "t": 28, "b": 12},
                    legend_title_text="",
                )
                monthly_chart.update_yaxes(
                    title="Amount",
                    tickprefix="$",
                    tickformat=",.2f",
                    rangemode="tozero",
                )
                st.plotly_chart(
                    monthly_chart,
                    width="stretch",
                )
            else:
                st.info("No activity in this period.")
        with right:
            st.subheader("Expenses by category")
            if not by_category.empty:
                category_chart = px.bar(
                    by_category,
                    x="Total",
                    y="Category",
                    orientation="h",
                    color_discrete_sequence=["#3267D6"],
                    labels={"Total": "Amount", "Category": "Expense category"},
                )
                category_chart.update_layout(
                    height=300,
                    margin={"l": 12, "r": 12, "t": 28, "b": 12},
                    showlegend=False,
                )
                category_chart.update_xaxes(
                    title="Amount",
                    tickprefix="$",
                    tickformat=",.2f",
                    rangemode="tozero",
                )
                st.plotly_chart(
                    category_chart,
                    width="stretch",
                )
            else:
                st.info("No expenses in this period.")
    if category_detail_rows:
        st.caption("Layer 1 totals include direct activity and all Layer 2 children.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Category": (
                            row["category"]
                            if row["layer"] == 1
                            else f'↳ {row["category"]}'
                        ),
                        "Layer": f'Layer {row["layer"]}',
                        "Parent": (
                            category_paths.get(row["parent_id"], "")
                            if row["parent_id"]
                            else ""
                        ),
                        "Direct activity": row["direct_total"],
                        "Layer 1 total": (
                            row["rollup_total"] if row["layer"] == 1 else None
                        ),
                    }
                    for row in category_detail_rows
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Direct activity": st.column_config.NumberColumn(format="$%.2f"),
                "Layer 1 total": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    st.divider()
    st.subheader("Balance sheet")
    st.caption("The As of date is independent from the income-and-expense period.")
    as_of = st.date_input("As of", date.today(), key="balance_sheet_date")
    statement = balance_sheet(accounts, transactions, as_of=as_of)
    with st.container(key="reports_statement_metrics"):
        asset_metric, liability_metric, equity_metric = st.columns(3)
        asset_metric.metric("Total assets", money(statement["total_assets"]))
        liability_metric.metric(
            "Total liabilities", money(statement["total_liabilities"])
        )
        equity_metric.metric("Total equity", money(statement["total_equity"]))

    with st.container(key="reports_statement_tables"):
        asset_column, liability_column, equity_column = st.columns(3)
        for column, title, frame in (
            (asset_column, "Assets", _statement_frame(statement["assets"])),
            (
                liability_column,
                "Liabilities",
                _statement_frame(statement["liabilities"]),
            ),
            (
                equity_column,
                "Equity",
                _statement_frame(
                    statement["equity"],
                    current_earnings=statement["current_earnings"],
                ),
            ),
        ):
            with column:
                st.markdown(f"**{title}**")
                if frame.empty:
                    st.caption("No accounts")
                else:
                    st.dataframe(
                        frame,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Balance": st.column_config.NumberColumn(format="$%.2f")
                        },
                    )
    if abs(statement["difference"]) < 0.005:
        st.markdown("**Status: Balanced** — Assets = Liabilities + Equity.")
        st.success("Balance sheet is balanced.")
    else:
        st.markdown("**Status: Out of balance** — review the difference below.")
        st.warning(
            "Balance sheet is out of balance by "
            f"{money(statement['difference'])}. Review opening balances and "
            "account classifications."
        )
    st.caption(
        "Liabilities and equity are presented with conventional positive "
        "balances. Enter their opening ledger balances as negative amounts."
    )
