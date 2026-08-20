"""Transactions page coordination."""

from __future__ import annotations

import streamlit as st

from tabula_rasa.hierarchy import hierarchy_paths, ordered_hierarchy
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.creation import render_add_transaction
from tabula_rasa.page_renderers.transactions.ledger import render_ledger
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import StorageError


def render_transactions(context: TransactionsContext) -> None:
    """Render transaction entry, ledger editing, and receipt workflows."""
    render_page_header("Transactions")
    tab_add, tab_ledger = st.tabs(["Add transaction", "View & edit ledger"])
    try:
        context.storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        accounts = context.storage.list_accounts(active_only=False)
        active_accounts = [account for account in accounts if account["active"]]
        categories = context.storage.list_categories()
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()

    account_paths = hierarchy_paths(accounts)
    category_paths = hierarchy_paths(categories)
    account_map = {
        account_paths[account_id]: account_id
        for account in ordered_hierarchy(active_accounts)
        if (account_id := str(account.get("id") or "").strip())
    }
    with tab_add:
        render_add_transaction(
            context,
            account_map=account_map,
            categories=categories,
            category_paths=category_paths,
        )

    with tab_ledger:
        render_ledger(
            context,
            accounts=accounts,
            categories=categories,
            account_paths=account_paths,
            category_paths=category_paths,
        )
