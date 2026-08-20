"""Transaction creation controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext


def render_add_transaction(
    context: TransactionsContext,
    *,
    account_map: Mapping[str, str],
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
) -> None:
    """Render the existing profile-scoped transaction creation workflow."""
    st.subheader("Add transaction")
    st.caption("Record income, expenses, or transfers in the active account set.")
    transaction_form_keys = (
        "add_transaction_date",
        "add_transaction_amount",
        "add_transaction_account_income",
        "add_transaction_account_expense",
        "add_transaction_account_transfer",
        "add_transaction_to_account",
        "add_transaction_category_income",
        "add_transaction_category_expense",
        "add_transaction_payee",
        "add_transaction_reference",
        "add_transaction_description",
    )
    context.reset_widget_state_if_requested(
        "reset_add_transaction_form",
        keys=transaction_form_keys,
    )
    kind = st.segmented_control(
        "Transaction type",
        ["Income", "Expense", "Transfer"],
        default="Expense",
    )
    if not account_map:
        st.warning("Create an active account before recording transactions.")
        return

    categories_for_kind = [
        category for category in categories if category["kind"] == kind
    ]
    if kind != "Transfer" and not categories_for_kind:
        st.warning(f"Create a {kind.lower()} category first.")
        return

    with st.form("add_transaction", clear_on_submit=False):
        transaction_date = st.date_input(
            "Date",
            date.today(),
            key="add_transaction_date",
        )
        category_id = None
        if kind == "Transfer":
            amount = st.number_input(
                "Amount",
                min_value=0.01,
                step=1.0,
                format="%.2f",
                key="add_transaction_amount",
            )
        else:
            c1, c2 = st.columns(2)
            category_map = {
                category_paths[category_id]: category_id
                for category in categories_for_kind
                if (category_id := str(category.get("id") or "").strip())
            }
            category_id = category_map[
                c1.selectbox(
                    "Category",
                    list(category_map),
                    key=("add_transaction_category_" f"{kind.casefold()}"),
                )
            ]
            amount = c2.number_input(
                "Amount",
                min_value=0.01,
                step=1.0,
                format="%.2f",
                key="add_transaction_amount",
            )
        source = st.selectbox(
            "From Account",
            list(account_map),
            key=f"add_transaction_account_{kind.casefold()}",
        )
        to_account = None
        if kind == "Transfer":
            choices = [name for name in account_map if name != source]
            to_account = (
                st.selectbox(
                    "To account",
                    choices,
                    key="add_transaction_to_account",
                )
                if choices
                else None
            )
        c1, c2 = st.columns(2)
        payee = c1.text_input(
            "Payee / customer",
            key="add_transaction_payee",
        )
        reference = c2.text_input(
            "Reference (optional)",
            key="add_transaction_reference",
        )
        description = st.text_input(
            "Description / memo",
            key="add_transaction_description",
        )
        submitted = st.form_submit_button(
            "Save transaction", type="primary", width="stretch"
        )
        if submitted:
            if kind == "Transfer" and not to_account:
                st.error("Create a second active account before recording a transfer.")
            else:
                payload = {
                    "txn_date": transaction_date,
                    "kind": kind,
                    "amount": amount,
                    "account_id": account_map[source],
                    "to_account_id": account_map.get(to_account, ""),
                    "category_id": category_id or "",
                    "payee": payee,
                    "description": description,
                    "reference": reference,
                }
                context.confirmed_write(
                    "create_transaction",
                    payload,
                    lambda: context.storage.create_transaction(**payload),
                    "Transaction saved.",
                    on_success=lambda: context.schedule_widget_reset(
                        "reset_add_transaction_form"
                    ),
                )
