"""Ledger filtering, selection, and transaction editing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import streamlit as st

from tabula_rasa.hierarchy import ordered_hierarchy
from tabula_rasa.ledger_presentation import ledger_frame, money
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.receipts import (
    clear_receipt_creation_recovery,
    render_receipts,
)
from tabula_rasa.page_renderers.transactions.search import filter_transaction_rows
from tabula_rasa.storage import StorageError, decode_receipt_references


def transaction_has_receipts(transaction: Mapping[str, object]) -> bool:
    references = transaction.get("receipt_references", "")
    if not references or (
        isinstance(references, str) and references.strip() in {"", "[]"}
    ):
        return False
    try:
        return bool(decode_receipt_references(references))
    except StorageError:
        return False


def _bulk_selection_key(profile_key: str) -> str:
    return f"transaction_bulk_selected_ids_{profile_key}"


def _clear_bulk_selection(profile_key: str) -> None:
    st.session_state[_bulk_selection_key(profile_key)] = ()
    st.session_state["transaction_bulk_selection_generation"] = int(
        st.session_state.get("transaction_bulk_selection_generation", 0)
    ) + 1


def _change_ledger_mode(profile_key: str) -> None:
    _clear_bulk_selection(profile_key)
    st.session_state["transaction_ledger_mode_generation"] = int(
        st.session_state.get("transaction_ledger_mode_generation", 0)
    ) + 1
    st.session_state.pop("edit_transaction_id", None)


def _selection_ids(transaction_ids: Sequence[str], rows: Sequence[int]) -> tuple[str, ...]:
    return tuple(
        transaction_ids[row_index]
        for row_index in rows
        if 0 <= row_index < len(transaction_ids)
    )


def render_ledger(
    context: TransactionsContext,
    *,
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
) -> None:
    """Render structured filters, the ledger, and single-row editing."""
    st.subheader("View & edit ledger")
    st.caption("Filter the ledger, then choose Edit or Bulk mode explicitly.")
    mode = st.segmented_control(
        "Ledger mode",
        ["Edit", "Bulk"],
        default="Edit",
        key=f"transaction_ledger_mode_{context.profile_key}",
        help="Edit manages one row. Bulk enables only the approved multi-row actions.",
        on_change=lambda: _change_ledger_mode(context.profile_key),
    )
    mode = mode or "Edit"
    transaction_ledger_key = "transaction_ledger_" f"{context.profile_key}_" f"{st.session_state.get('transaction_ledger_generation', 0)}"
    if st.session_state.get("transaction_ledger_mode_generation", 0):
        transaction_ledger_key += f"_{st.session_state['transaction_ledger_mode_generation']}"
    if mode == "Bulk":
        transaction_ledger_key += (
            "_bulk_"
            f"{st.session_state.get('transaction_bulk_selection_generation', 0)}"
        )
    c1, c2, c3 = st.columns(3)
    start = c1.date_input(
        "From",
        date(date.today().year, 1, 1),
        key="ledger_start",
        on_change=lambda: _clear_bulk_selection(context.profile_key),
    )
    end = c2.date_input(
        "To",
        date.today(),
        key="ledger_end",
        on_change=lambda: _clear_bulk_selection(context.profile_key),
    )
    filter_type = c3.selectbox(
        "Type",
        ["All", "Income", "Expense", "Transfer"],
        key=f"ledger_filter_type_{context.profile_key}",
        on_change=lambda: _clear_bulk_selection(context.profile_key),
    )
    ledger_account_map = {
        account_paths[account_id]: account_id
        for account in ordered_hierarchy(accounts)
        if (account_id := str(account.get("id") or "").strip())
    }
    selected_account_names = st.multiselect(
        "Accounts",
        list(ledger_account_map),
        key=f"ledger_filter_accounts_{context.profile_key}",
        placeholder="All accounts",
        help=(
            "Includes transactions where a selected account is either side "
            "of a transfer."
        ),
        on_change=lambda: _clear_bulk_selection(context.profile_key),
    )
    selected_account_ids = [
        ledger_account_map[name] for name in selected_account_names
    ]
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
        placeholder="Type, account, payee, description, reference, or ID",
        help=(
            "Searches Type, Account, To account, Category, Payee, "
            "Description, Reference, and ID."
        ),
        on_change=lambda: _clear_bulk_selection(context.profile_key),
    )
    if search_query.strip():
        st.button(
            "Clear search",
            key=f"ledger_search_clear_{context.profile_key}_{table_generation}",
            on_click=clear_search,
        )
    try:
        all_transactions = context.storage.list_transactions()
        structured_transactions = context.storage.list_transactions(
            start=start,
            end=end,
            kind=None if filter_type == "All" else filter_type,
            account_ids=selected_account_ids or None,
        )
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()
    transaction_frame = ledger_frame(
        structured_transactions,
        accounts,
        categories,
    )
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
            "Description",
            "Amount",
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
    selection_scope = (
        context.profile_key,
        st.session_state.get("transaction_ledger_generation", 0),
        start.isoformat(),
        end.isoformat(),
        filter_type,
        tuple(sorted(selected_account_ids)),
        search_query.strip(),
        mode,
    )
    previous_scope = st.session_state.get("transaction_bulk_scope")
    if previous_scope != selection_scope:
        if previous_scope is not None or st.session_state.get(
            _bulk_selection_key(context.profile_key)
        ):
            _clear_bulk_selection(context.profile_key)
        st.session_state["transaction_bulk_scope"] = selection_scope
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
    transaction_ids = transaction_frame["ID"].tolist()

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
        on_select=select_ledger_transaction,
        selection_mode="multi-row" if mode == "Bulk" else "single-row",
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Receipt": st.column_config.TextColumn(
                width="small",
                help="This transaction has linked receipts.",
            ),
        },
    )
    selected_rows = ledger_event.selection.rows
    if mode == "Bulk":
        selected_ids = tuple(
            str(transaction_id)
            for transaction_id in st.session_state.get(
                _bulk_selection_key(context.profile_key), ()
            )
        )
        transaction_ids_set = set(transaction_ids)
        if any(transaction_id not in transaction_ids_set for transaction_id in selected_ids):
            _clear_bulk_selection(context.profile_key)
            selected_ids = ()
        st.caption(f"{len(selected_ids)} transaction(s) selected")
        if selected_ids:
            selected_by_id = {
                str(transaction["id"]): transaction for transaction in transactions
            }
            expected_selected = [selected_by_id[item] for item in selected_ids]
            selected_frame = transaction_frame[
                transaction_frame["ID"].astype(str).isin(selected_ids)
            ]
            st.download_button(
                "Export selected",
                selected_frame.to_csv(index=False).encode("utf-8"),
                file_name=f"tabula-rosa-selected-{date.today()}.csv",
                mime="text/csv",
                width="stretch",
                key=(
                    "transaction_bulk_export_"
                    f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
                ),
            )
            selected_kinds = {item["kind"] for item in expected_selected}
            category_eligible = selected_kinds in ({"Income"}, {"Expense"})
            if not category_eligible:
                st.info(
                    "Change category is disabled because Bulk category changes require "
                    "a homogeneous Income or Expense selection; transfers are not eligible."
                )
            else:
                common_kind = next(iter(selected_kinds))
                category_map = {
                    category_paths[category_id]: category_id
                    for category in categories
                    if category["kind"] == common_kind
                    and (category_id := str(category.get("id") or "").strip())
                    and category_id in category_paths
                }
                with st.form(
                    "transaction_bulk_category",
                    clear_on_submit=False,
                ):
                    target_category_id = category_map[
                        st.selectbox(
                            "New category",
                            list(category_map),
                            key=(
                                "transaction_bulk_category_"
                                f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
                            ),
                        )
                    ]
                    st.caption(
                        f"Review: change category for {len(selected_ids)} {common_kind.lower()} transaction(s)."
                    )
                    category_requested = st.form_submit_button(
                        "Change category",
                        type="primary",
                        width="stretch",
                    )
                if category_requested:
                    _clear_bulk_selection(context.profile_key)
                    context.confirmed_write(
                        "bulk_change_transaction_category",
                        {
                            "ids": list(selected_ids),
                            "expected": expected_selected,
                            "category_id": target_category_id,
                        },
                        lambda: context.storage.bulk_change_transaction_category(
                            selected_ids,
                            expected_transactions=expected_selected,
                            category_id=target_category_id,
                        ),
                        lambda result: f"Category updated for {result['count']} transactions.",
                    )

            total_amount = sum(abs(float(item["amount"])) for item in expected_selected)
            st.warning(
                f"Review: permanently delete {len(selected_ids)} transaction(s) "
                f"totaling {money(total_amount)}. Linked receipt references will be "
                "removed, but the Google Drive files will remain in Drive as unreferenced files."
            )
            with st.form("transaction_bulk_delete", clear_on_submit=False):
                confirm_delete = st.checkbox(
                    "I understand these transactions will be permanently deleted and cannot be undone",
                    key=(
                        "transaction_bulk_confirm_delete_"
                        f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
                    ),
                )
                delete_requested = st.form_submit_button(
                    "Permanently delete selected",
                    type="primary",
                    disabled=not confirm_delete,
                    width="stretch",
                )
            if delete_requested:
                _clear_bulk_selection(context.profile_key)
                context.confirmed_write(
                    "bulk_delete_transactions",
                    {"ids": list(selected_ids), "expected": expected_selected},
                    lambda: context.storage.bulk_delete_transactions(
                        selected_ids,
                        expected_transactions=expected_selected,
                    ),
                    lambda result: (
                        f"Permanently deleted {result['count']} transactions; "
                        "linked Drive files were retained."
                    ),
                    on_success=lambda: [
                        clear_receipt_creation_recovery(context, item)
                        for item in selected_ids
                    ],
                )
        else:
            st.info("Select one or more visible transactions to use Bulk actions.")
    elif not transaction_frame.empty:

        def transaction_label(transaction_id: str) -> str:
            row = transaction_frame.loc[
                transaction_frame["ID"] == transaction_id
            ].iloc[0]
            return f"{row['Date']} — {row['Type']} — {money(row['Amount'])} — {transaction_id[:8]}"

        st.caption("Select a ledger row (or double-click it) to edit it.")
        with st.expander("Edit transaction", expanded=bool(selected_rows)):
            edit_id = st.selectbox(
                "Transaction to edit",
                transaction_ids,
                format_func=transaction_label,
                key="edit_transaction_id",
            )
            selected = next(
                transaction for transaction in transactions if transaction["id"] == edit_id
            )
            edit_widget_scope = f"{context.profile_key}_{edit_id}"
            with st.form("edit_transaction"):
                current_account_ids = [
                    selected["account_id"],
                    selected.get("to_account_id", ""),
                ]
                editable_account_ids = [
                    account["id"]
                    for account in ordered_hierarchy(accounts)
                    if account["active"]
                    or account["id"] in current_account_ids
                ]
                edited_account_id = st.selectbox(
                    (
                        "Edit from account"
                        if selected["kind"] == "Transfer"
                        else "Edit account"
                    ),
                    editable_account_ids,
                    index=(
                        editable_account_ids.index(selected["account_id"])
                        if selected["account_id"] in editable_account_ids
                        else None
                    ),
                    format_func=account_paths.get,
                    key=f"edit_transaction_account_{edit_widget_scope}",
                )
                edited_to_account_id = ""
                edited_category_id = ""
                if selected["kind"] == "Transfer":
                    edited_to_account_id = st.selectbox(
                        "Edit to account",
                        editable_account_ids,
                        index=(
                            editable_account_ids.index(
                                selected["to_account_id"]
                            )
                            if selected.get("to_account_id")
                            in editable_account_ids
                            else None
                        ),
                        format_func=account_paths.get,
                        key=f"edit_transaction_to_account_{edit_widget_scope}",
                    )
                else:
                    category_ids = [
                        category["id"]
                        for category in categories
                        if category["kind"] == selected["kind"]
                    ]
                    edited_category_id = st.selectbox(
                        "Edit category",
                        category_ids,
                        index=(
                            category_ids.index(selected["category_id"])
                            if selected["category_id"] in category_ids
                            else None
                        ),
                        format_func=category_paths.get,
                        key=f"edit_transaction_category_{edit_widget_scope}",
                    )
                c1, c2 = st.columns(2)
                edited_date = c1.date_input(
                    "Edit date",
                    date.fromisoformat(selected["txn_date"]),
                    key=f"edit_transaction_date_{edit_widget_scope}",
                )
                edited_amount = c2.number_input(
                    "Edit amount",
                    min_value=0.01,
                    value=float(selected["amount"]),
                    format="%.2f",
                    key=f"edit_transaction_amount_{edit_widget_scope}",
                )
                edited_payee = st.text_input(
                    "Edit payee / customer",
                    value=selected.get("payee", ""),
                    key=f"edit_transaction_payee_{edit_widget_scope}",
                )
                edited_reference = st.text_input(
                    "Edit reference",
                    value=selected.get("reference", ""),
                    key=f"edit_transaction_reference_{edit_widget_scope}",
                )
                edited_description = st.text_input(
                    "Edit description",
                    value=selected.get("description", ""),
                    key=f"edit_transaction_description_{edit_widget_scope}",
                )
                st.warning(
                    "Deleting this transaction is permanent and cannot be undone.",
                    icon="⚠️",
                )
                confirm_delete = st.checkbox(
                    "I understand this transaction will be permanently deleted",
                    key=f"edit_transaction_confirm_delete_{edit_widget_scope}",
                )
                save_column, delete_column = st.columns(2)
                save_requested = save_column.form_submit_button(
                    "Save changes",
                    type="primary",
                    width="stretch",
                    key=f"edit_transaction_save_{edit_widget_scope}",
                )
                delete_requested = delete_column.form_submit_button(
                    "Permanently delete",
                    icon=":material/delete_forever:",
                    help="Permanently delete this transaction",
                    width="stretch",
                    key=f"edit_transaction_delete_{edit_widget_scope}",
                )
                if save_requested:
                    payload = {
                        "id": edit_id,
                        "txn_date": edited_date,
                        "amount": edited_amount,
                        "account_id": edited_account_id,
                        "to_account_id": edited_to_account_id,
                        "category_id": edited_category_id,
                        "payee": edited_payee,
                        "reference": edited_reference,
                        "description": edited_description,
                    }
                    if (
                        selected["kind"] == "Transfer"
                        and edited_account_id == edited_to_account_id
                    ):
                        st.error("Transfer accounts must be different.")
                    else:
                        context.confirmed_write(
                            "edit_transaction",
                            payload,
                            lambda: context.storage.edit_transaction(
                                edit_id,
                                txn_date=edited_date,
                                amount=edited_amount,
                                account_id=edited_account_id,
                                to_account_id=edited_to_account_id,
                                category_id=edited_category_id,
                                payee=edited_payee,
                                reference=edited_reference,
                                description=edited_description,
                            ),
                            "Transaction updated.",
                        )
                if delete_requested:
                    if not confirm_delete:
                        st.error(
                            "Confirm that you understand deletion is permanent."
                        )
                    else:
                        payload = {"id": edit_id}
                        context.confirmed_write(
                            "delete_transaction",
                            payload,
                            lambda: context.storage.delete_transaction(edit_id),
                            "Transaction deleted.",
                            on_success=lambda: clear_receipt_creation_recovery(
                                context,
                                edit_id,
                            ),
                        )
            render_receipts(
                context,
                selected=selected,
                all_transactions=all_transactions,
                edit_id=edit_id,
            )
