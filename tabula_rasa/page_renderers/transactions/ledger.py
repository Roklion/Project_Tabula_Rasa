"""Ledger orchestration facade for filters, bulk actions, editing, and copy."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
import hashlib
import streamlit as st
from tabula_rasa.hierarchy import ordered_accounts
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.receipts import clear_missing_editor_receipt_recoveries
from tabula_rasa.page_renderers.transactions.receipts import editor_receipt_recovery_active
from tabula_rasa.page_renderers.transactions.receipts import editor_receipt_recovery_transaction_ids
from tabula_rasa.page_renderers.transactions.receipts import render_filtered_editor_receipt_recovery
from tabula_rasa.page_renderers.transactions.search import filter_transaction_rows
from tabula_rasa.storage import StorageError
from .ledger_bulk import render_bulk_actions
from .ledger_editor import render_transaction_editor
from .ledger_filters import (
    _bulk_selection_key,
    _change_ledger_mode,
    _clear_bulk_selection,
    _mixed_use_transaction_ids,
    _selection_ids,
    transaction_has_receipts,
    transaction_is_mixed_use,
    transaction_is_source_driven,
    transaction_type_label,
)
from .transaction_copy import (
    _clear_copy_state,
    _copy_generation_key,
    _copy_source_key,
    _copyable_tag_ids,
    _editable_account_ids,
    _finish_copy_save,
    _make_created_copy_visible,
    _pending_edit_transaction_key,
    copied_transaction_description,
)

def render_ledger(
    context: TransactionsContext,
    *,
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    render_error_footer: Callable[[], None],
) -> None:
    """Render structured filters, the ledger, and single-row editing."""
    st.subheader("View & edit ledger")
    st.caption("Filter the ledger, then choose Edit or Bulk mode explicitly.")
    pending_edit_transaction = st.session_state.pop(
        _pending_edit_transaction_key(context.profile_key), None
    )
    if isinstance(pending_edit_transaction, Mapping):
        # Apply the newly created copy before the edit selectbox is instantiated.
        _make_created_copy_visible(context.profile_key, pending_edit_transaction)
    copy_source_id = str(
        st.session_state.get(_copy_source_key(context.profile_key), "") or ""
    )
    copy_filters_locked = bool(copy_source_id)
    c1, c2, c3 = st.columns(3)
    start = c1.date_input(
        "From",
        date(date.today().year, 1, 1),
        key="ledger_start",
        disabled=copy_filters_locked,
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    end = c2.date_input(
        "To",
        date.today(),
        key="ledger_end",
        disabled=copy_filters_locked,
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    filter_type = c3.selectbox(
        "Type",
        ["All", "Income", "Expense", "Transfer"],
        key=f"ledger_filter_type_{context.profile_key}",
        disabled=copy_filters_locked,
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    ledger_account_map = {
        account_paths[account_id]: account_id
        for account in ordered_accounts(accounts)
        if (account_id := str(account.get("id") or "").strip())
    }
    selected_account_names = st.multiselect(
        "Accounts",
        list(ledger_account_map),
        key=f"ledger_filter_accounts_{context.profile_key}",
        placeholder="All accounts",
        disabled=copy_filters_locked,
        help=(
            "Includes transactions where a selected account is either side "
            "of a transfer."
        ),
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    selected_account_ids = [
        ledger_account_map[name] for name in selected_account_names
    ]
    ledger_tag_map = {
        str(tag["id"]): str(tag["name"])
        for tag in tags
        if str(tag.get("id") or "").strip()
        and str(tag.get("name") or "").strip()
    }
    tag_filter_options = [tag_id for tag_id in ledger_tag_map]
    selected_tag_ids = st.multiselect(
        "Tags",
        tag_filter_options,
        key=f"ledger_filter_tags_{context.profile_key}",
        placeholder="All tags",
        format_func=ledger_tag_map.get,
        disabled=copy_filters_locked,
        help="Includes transactions assigned at least one selected Tag.",
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    table_generation = st.session_state.get("transaction_ledger_generation", 0)
    search_state_key = (
        f"ledger_search_{context.profile_key}_{table_generation}"
    )

    def clear_search() -> None:
        st.session_state[search_state_key] = ""
        _clear_bulk_selection(context.profile_key)

    search_query = st.text_input(
        "Search transactions",
        key=search_state_key,
        placeholder="Type, account, payee, Tag, description, reference, or ID",
        disabled=copy_filters_locked,
        help=(
            "Searches Type, Account, To account, Category, Payee, "
            "Tags, Description, Reference, and ID."
        ),
        on_change=_clear_bulk_selection,
        args=(context.profile_key,),
    )
    if search_query.strip():
        st.button(
            "Clear search",
            key=f"ledger_search_clear_{context.profile_key}_{table_generation}",
            disabled=copy_filters_locked,
            on_click=clear_search,
        )
    mode_key = f"transaction_ledger_mode_{context.profile_key}"
    if copy_source_id:
        # A copy always opens the existing single-row editor, even when the
        # user started from a one-row Bulk selection.
        st.session_state[mode_key] = "Edit"
    mode = st.segmented_control(
        "Ledger mode",
        ["Edit", "Bulk"],
        default="Edit",
        key=mode_key,
        help="Edit manages one row. Bulk enables only the approved multi-row actions.",
        on_change=_change_ledger_mode,
        args=(context.profile_key,),
    )
    mode = mode or "Edit"
    try:
        all_transactions = (
            context.storage.list_transactions(_force_refresh=True)
            if editor_receipt_recovery_active(context)
            else context.storage.list_transactions()
        )
        recovery_notices = clear_missing_editor_receipt_recoveries(
            context,
            all_transactions,
        )
        for notice in recovery_notices:
            st.warning(notice)
        structured_transactions = context.storage.list_transactions(
            start=start,
            end=end,
            kind=None if filter_type == "All" else filter_type,
            account_ids=selected_account_ids or None,
        )
        if selected_tag_ids:
            selected_tag_id_set = set(selected_tag_ids)
            structured_transactions = [
                transaction
                for transaction in structured_transactions
                if selected_tag_id_set.intersection(
                    str(tag_id)
                    for tag_id in transaction.get("tag_ids", [])
                )
            ]
    except StorageError as error:
        context.report_storage_error(error)
        render_error_footer()
        st.stop()
    transaction_frame = ledger_frame(
        structured_transactions,
        accounts,
        categories,
        tags=tags,
    )
    transaction_by_id = {
        str(transaction.get("id") or ""): transaction
        for transaction in structured_transactions
    }
    transaction_frame["Type"] = [
        transaction_type_label(value, transaction_by_id.get(str(row_id), {}))
        for value, row_id in zip(
            transaction_frame["Type"],
            transaction_frame["ID"],
            strict=False,
        )
    ]
    transaction_frame["Receipt"] = [
        "\U0001f4ce" if transaction_has_receipts(transaction) else ""
        for transaction in structured_transactions
    ]
    transaction_frame = transaction_frame.sort_values(
        "Date",
        ascending=False,
        kind="stable",
        ignore_index=True,
    )
    transaction_frame = transaction_frame[
        [
            "Date",
            "Type",
            "Account",
            "To account",
            "Category",
            "Payee",
            "Amount",
            "Tags",
            "Description",
            "Receipt",
            "Reference",
            "ID",
        ]
    ]
    searchable_rows = transaction_frame.to_dict(orient="records")
    matched_rows = filter_transaction_rows(searchable_rows, search_query)
    matched_ids = {str(row["ID"]) for row in matched_rows}
    transactions = [
        transaction
        for transaction in structured_transactions
        if str(transaction.get("id", "")) in matched_ids
    ]
    transaction_frame = transaction_frame[
        transaction_frame["ID"].astype(str).isin(matched_ids)
    ].reset_index(drop=True)
    transaction_ids = [str(transaction_id) for transaction_id in transaction_frame["ID"]]
    transaction_ids_set = set(transaction_ids)
    if copy_source_id and copy_source_id not in transaction_ids_set:
        # Do not let a filter change turn the copy form into an editor for a
        # different row while its source is hidden.
        _clear_copy_state(context.profile_key)
        copy_source_id = ""
    selection_scope = (
        context.profile_key,
        st.session_state.get("transaction_ledger_generation", 0),
        st.session_state.get("workbook_data_revision", 0),
        start.isoformat(),
        end.isoformat(),
        filter_type,
        tuple(sorted(selected_account_ids)),
        tuple(sorted(selected_tag_ids)),
        search_query.strip(),
        mode,
        tuple(transaction_ids),
    )
    previous_scope = st.session_state.get("transaction_bulk_scope")
    selected_scope_ids = tuple(
        str(transaction_id)
        for transaction_id in st.session_state.get(
            _bulk_selection_key(context.profile_key), ()
        )
    )
    scope_changed = previous_scope != selection_scope
    selection_is_stale = any(
        transaction_id not in transaction_ids_set for transaction_id in selected_scope_ids
    )
    if scope_changed or selection_is_stale:
        if selected_scope_ids:
            _clear_bulk_selection(context.profile_key)
        st.session_state["transaction_bulk_scope"] = selection_scope
    transaction_ledger_key = (
        f"transaction_ledger_{context.profile_key}_"
        f"{st.session_state.get('transaction_ledger_generation', 0)}"
    )
    if st.session_state.get("transaction_ledger_mode_generation", 0):
        transaction_ledger_key += f"_{st.session_state['transaction_ledger_mode_generation']}"
    if mode == "Bulk":
        transaction_ledger_key += (
            "_bulk_"
            f"{st.session_state.get('transaction_bulk_selection_generation', 0)}"
        )
    if not all_transactions:
        st.info("No transactions exist yet. Add a transaction to populate the ledger.")
    elif transaction_frame.empty:
        if search_query.strip():
            st.info(
                "No transactions match your search and current filters. "
                "Clear search or adjust the filters."
            )
        else:
            st.info(
                "No transactions match the active date, type, or account filters."
            )
    st.caption(f"Showing {len(transaction_frame)} transaction(s).")
    if transaction_ids:
        if st.session_state.get("edit_transaction_id") not in transaction_ids:
            st.session_state["edit_transaction_id"] = transaction_ids[0]
    else:
        # Keep the widget key initialized while the edit expander is hidden;
        # this avoids a stale selectbox event being replayed on the next run.
        st.session_state["edit_transaction_id"] = None

    def select_ledger_transaction() -> None:
        selected_rows = st.session_state[transaction_ledger_key].selection.rows
        if mode == "Bulk":
            st.session_state[_bulk_selection_key(context.profile_key)] = _selection_ids(
                transaction_ids, selected_rows
            )
        elif selected_rows and selected_rows[0] < len(transaction_ids):
            st.session_state["edit_transaction_id"] = transaction_ids[selected_rows[0]]

    ledger_event = st.dataframe(
        transaction_frame,
        hide_index=True,
        width="stretch",
        key=transaction_ledger_key,
        on_select=("ignore" if copy_source_id else select_ledger_transaction),
        selection_mode=(
            []
            if copy_source_id
            else ("multi-row" if mode == "Bulk" else "single-row")
        ),
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Receipt": st.column_config.TextColumn(
                width="small",
                help="This transaction has linked receipts.",
            ),
        },
    )
    selected_rows = [] if copy_source_id else ledger_event.selection.rows
    selected_for_copy = (
        tuple(
            str(transaction_id)
            for transaction_id in st.session_state.get(
                _bulk_selection_key(context.profile_key), ()
            )
            if str(transaction_id) in transaction_ids_set
        )
        if mode == "Bulk"
        else _selection_ids(transaction_ids, selected_rows)
    )
    selected_protected = any(
        transaction_is_source_driven(transaction_by_id.get(transaction_id, {}))
        for transaction_id in selected_for_copy
    )
    copy_button = st.button(
        "Copy transaction",
        disabled=(
            bool(copy_source_id)
            or len(selected_for_copy) != 1
            or selected_protected
        ),
        key=(
            "transaction_copy_"
            f"{context.profile_key}_{st.session_state.get('transaction_ledger_generation', 0)}"
        ),
        help=(
            "Source-driven entries are managed from Mixed-use expenses or Assets."
            if selected_protected
            else "Select exactly one transaction to open a prefilled copy form."
        ),
    )
    if copy_button and len(selected_for_copy) == 1:
        source_id = selected_for_copy[0]
        st.session_state[_copy_source_key(context.profile_key)] = source_id
        generation_key = _copy_generation_key(context.profile_key)
        st.session_state[generation_key] = int(
            st.session_state.get(generation_key, 0)
        ) + 1
        st.session_state["edit_transaction_id"] = source_id
        st.rerun()
    derived_ids = _mixed_use_transaction_ids(all_transactions)
    filtered_recovery_ids = (
        set(editor_receipt_recovery_transaction_ids(context))
        - set(transaction_ids)
        - derived_ids
    )
    if filtered_recovery_ids:
        with st.expander(
            "Receipt recovery for filtered transactions",
            expanded=True,
        ):
            st.warning(
                "Receipt recovery remains available below even when its "
                "transaction is hidden by the active ledger filters."
            )
            for recovery_id in sorted(filtered_recovery_ids):
                st.caption(f"Transaction recovery: {recovery_id}")
                render_filtered_editor_receipt_recovery(context, recovery_id)
    if mode == "Bulk":
        selected_ids = tuple(
            str(transaction_id)
            for transaction_id in st.session_state.get(
                _bulk_selection_key(context.profile_key), ()
            )
        )
        selected_by_id = {
            str(transaction.get("id", "")): transaction
            for transaction in transactions
        }
        expected_selected = [selected_by_id[item] for item in selected_ids]
        selected_snapshot_key = hashlib.sha256(
            repr(
                tuple(
                    tuple(
                        sorted((str(key), str(value)) for key, value in item.items())
                    )
                    for item in sorted(
                        expected_selected,
                        key=lambda item: str(item.get("id", "")),
                    )
                )
            ).encode("utf-8")
        ).hexdigest()
        render_bulk_actions(
            context,
            categories=categories,
            category_paths=category_paths,
            payees=payees,
            tags=tags,
            transaction_frame=transaction_frame,
            transactions=transactions,
            selected_ids=selected_ids,
            selected_protected=selected_protected,
            expected_selected=expected_selected,
            selected_snapshot_key=selected_snapshot_key,
        )
    elif not transaction_frame.empty:
        if render_transaction_editor(
            context,
            accounts=accounts,
            categories=categories,
            account_paths=account_paths,
            category_paths=category_paths,
            payees=payees,
            tags=tags,
            transaction_frame=transaction_frame,
            transactions=transactions,
            transaction_ids=transaction_ids,
            selected_rows=selected_rows,
            all_transactions=all_transactions,
        ):
            return

__all__ = [
    '_bulk_selection_key',
    '_change_ledger_mode',
    '_clear_bulk_selection',
    '_clear_copy_state',
    '_copy_generation_key',
    '_copy_source_key',
    '_copyable_tag_ids',
    '_editable_account_ids',
    '_finish_copy_save',
    '_make_created_copy_visible',
    '_mixed_use_transaction_ids',
    '_pending_edit_transaction_key',
    '_selection_ids',
    'copied_transaction_description',
    'render_ledger',
    'transaction_has_receipts',
    'transaction_is_mixed_use',
]
