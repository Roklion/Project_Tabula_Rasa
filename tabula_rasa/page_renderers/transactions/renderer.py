"""Transactions page coordination."""

from __future__ import annotations

import streamlit as st

from tabula_rasa.hierarchy import hierarchy_paths, ordered_hierarchy
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.creation import render_add_transaction
from tabula_rasa.page_renderers.transactions.ledger import render_ledger
from tabula_rasa.page_renderers.transactions.payees_tags import (
    PayeesTagsContext,
    render_payees_tags,
)
from tabula_rasa.presentation import render_global_footer, render_page_header
from tabula_rasa.storage import StorageError


def _ordered_active_accounts(accounts: list[dict]) -> list[dict]:
    """Return active accounts in the Accounts table's hierarchy order."""
    return [
        account for account in ordered_hierarchy(accounts) if account["active"]
    ]


def render_transactions(context: TransactionsContext) -> None:
    """Render transaction entry, ledger editing, and receipt workflows."""
    render_page_header(
        "Transactions",
        "Record activity, manage the ledger, and keep receipt links with each row.",
    )
    tab_add, tab_ledger, tab_payees_tags = st.tabs(
        ["Add transaction", "View & edit ledger", "Payees & Tags"]
    )
    page_footer = st.empty()

    def render_error_footer() -> None:
        with page_footer.container():
            render_global_footer()

    try:
        context.storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Payees",
            "Transactions",
            "Tags",
            "MixedUseExpenses",
            "Mileage",
        )
        accounts = context.storage.list_accounts(active_only=False)
        active_accounts = _ordered_active_accounts(accounts)
        categories = context.storage.list_categories()
        payees = context.storage.list_payees()
        tags = context.storage.list_tags()
    except StorageError as error:
        context.report_storage_error(error)
        render_error_footer()
        st.stop()

    account_paths = hierarchy_paths(accounts)
    category_paths = hierarchy_paths(categories)
    account_map = {
        account_paths[account_id]: account_id
        for account in active_accounts
        if (account_id := str(account.get("id") or "").strip())
    }
    with tab_add:
        with st.container(key="transactions_add_surface"):
            render_add_transaction(
                context,
                account_map=account_map,
                categories=categories,
                category_paths=category_paths,
                payees=payees,
                tags=tags,
            )

    with tab_ledger:
        with st.container(key="transactions_ledger_surface"):
            render_ledger(
                context,
                accounts=accounts,
                categories=categories,
                account_paths=account_paths,
                category_paths=category_paths,
                payees=payees,
                tags=tags,
                render_error_footer=render_error_footer,
            )

    with tab_payees_tags:
        with st.container(key="transactions_payees_tags_surface"):
            render_payees_tags(
                PayeesTagsContext(
                    profile_key=context.profile_key,
                    storage=context.storage,
                    confirmed_write=context.confirmed_write,
                    report_storage_error=context.report_storage_error,
                )
            )
