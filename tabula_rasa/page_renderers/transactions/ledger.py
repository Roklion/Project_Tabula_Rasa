"""Ledger filtering, selection, and transaction editing."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
import hashlib
import re

import streamlit as st

from tabula_rasa.hierarchy import ordered_hierarchy
from tabula_rasa.ledger_presentation import ledger_frame, money
from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.receipts import (
    clear_receipt_creation_recovery,
    clear_missing_editor_receipt_recoveries,
    editor_receipt_recovery_active,
    editor_receipt_recovery_transaction_ids,
    editor_receipt_notice_transaction_ids,
    prepare_editor_receipt_uploads,
    process_editor_receipt_uploads,
    render_editor_receipt_notice,
    render_editor_receipt_uploader,
    render_filtered_editor_receipt_recovery,
    render_receipts,
    _receipt_folder,
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
    if not st.session_state.get(_copy_source_key(profile_key)):
        st.session_state.pop("edit_transaction_id", None)


def _selection_ids(transaction_ids: Sequence[str], rows: Sequence[int]) -> tuple[str, ...]:
    return tuple(
        transaction_ids[row_index]
        for row_index in rows
        if 0 <= row_index < len(transaction_ids)
    )


def _copy_source_key(profile_key: str) -> str:
    """Return the profile-scoped source ID for the active copy form."""
    return f"transaction_copy_source_{profile_key}"


def _copy_generation_key(profile_key: str) -> str:
    """Return the profile-scoped generation used to isolate copy widgets."""
    return f"transaction_copy_generation_{profile_key}"


def copied_transaction_description(transaction: Mapping[str, object]) -> str:
    """Build copy provenance while retaining the user's current memo."""
    source_id = str(transaction.get("id") or "").strip()
    description = str(transaction.get("description", "") or "").strip()

    # Copies created by earlier versions put provenance before the memo, while
    # the current format puts it after the memo. Remove either form repeatedly
    # so copying an already-copied transaction does not accumulate stale notes.
    provenance_prefix = re.compile(
        r"^(?:Copy From|Copied from transaction)\s+[^\s:.]+"
        r"(?:\s*:\s*|\.\s+|$)"
    )
    provenance_suffix = re.compile(
        r"(?:^|\.\s+)(?:Copy From|Copied from transaction)\s+"
        r"[^\s:.]+$"
    )
    while description:
        stripped = provenance_prefix.sub("", description, count=1).strip()
        if stripped != description:
            description = stripped
            continue
        match = provenance_suffix.search(description)
        if match is None:
            break
        description = description[: match.start()].rstrip(" .:")

    provenance = f"Copy From {source_id}" if source_id else "Copy From"
    if not description:
        return provenance
    if not description.endswith("."):
        description += "."
    return f"{description} {provenance}"


def _editable_account_ids(
    accounts: Sequence[Mapping[str, object]],
    current_account_ids: Sequence[str],
    *,
    copy_mode: bool,
) -> list[str]:
    """Return accounts that can be selected by this editor mode."""

    current_ids = set(current_account_ids)
    return [
        str(account["id"])
        for account in ordered_hierarchy(accounts)
        if account["active"]
        or (not copy_mode and str(account["id"]) in current_ids)
    ]


def _clear_copy_state(profile_key: str) -> None:
    """Leave the source row in normal edit mode without writing anything."""
    st.session_state.pop(_copy_source_key(profile_key), None)


def _pending_edit_transaction_key(profile_key: str) -> str:
    return f"transaction_pending_edit_{profile_key}"


def _make_created_copy_visible(
    profile_key: str,
    transaction: Mapping[str, object],
) -> None:
    """Adjust ledger filters so the newly created copy stays selectable."""
    transaction_id = str(transaction.get("id") or "").strip()
    transaction_date = transaction.get("txn_date")
    if not transaction_id or not transaction_date:
        return
    try:
        created_date = date.fromisoformat(str(transaction_date))
    except ValueError:
        return
    start = st.session_state.get("ledger_start")
    end = st.session_state.get("ledger_end")
    if isinstance(start, date):
        st.session_state["ledger_start"] = min(start, created_date)
    else:
        st.session_state["ledger_start"] = created_date
    if isinstance(end, date):
        st.session_state["ledger_end"] = max(end, created_date)
    else:
        st.session_state["ledger_end"] = created_date
    st.session_state[f"ledger_filter_type_{profile_key}"] = "All"
    st.session_state[f"ledger_filter_accounts_{profile_key}"] = []
    for key in tuple(st.session_state):
        if key.startswith(f"ledger_search_{profile_key}_"):
            st.session_state[key] = ""
    st.session_state["edit_transaction_id"] = transaction_id


def render_ledger(
    context: TransactionsContext,
    *,
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
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
        for account in ordered_hierarchy(accounts)
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
        disabled=copy_filters_locked,
        help=(
            "Searches Type, Account, To account, Category, Payee, "
            "Description, Reference, and ID."
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
    except StorageError as error:
        context.report_storage_error(error)
        render_error_footer()
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
    copy_button = st.button(
        "Copy transaction",
        disabled=bool(copy_source_id) or len(selected_for_copy) != 1,
        key=(
            "transaction_copy_"
            f"{context.profile_key}_{st.session_state.get('transaction_ledger_generation', 0)}"
        ),
        help=(
            "Select exactly one transaction to open a prefilled copy form."
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
    filtered_recovery_ids = set(editor_receipt_recovery_transaction_ids(context)) - set(
        transaction_ids
    )
    filtered_notice_ids = set(editor_receipt_notice_transaction_ids(context)) - set(
        transaction_ids
    )
    if filtered_recovery_ids or filtered_notice_ids:
        with st.expander(
            "Receipt recovery for filtered transactions",
            expanded=True,
        ):
            if filtered_recovery_ids:
                st.warning(
                    "Receipt recovery remains available below even when its "
                    "transaction is hidden by the active ledger filters."
                )
                for recovery_id in sorted(filtered_recovery_ids):
                    st.caption(f"Transaction recovery: {recovery_id}")
                    render_filtered_editor_receipt_recovery(context, recovery_id)
            for notice_id in sorted(filtered_notice_ids):
                render_editor_receipt_notice(context, notice_id)
    if mode == "Bulk":
        selected_ids = tuple(
            str(transaction_id)
            for transaction_id in st.session_state.get(
                _bulk_selection_key(context.profile_key), ()
            )
        )
        st.caption(f"{len(selected_ids)} transaction(s) selected")
        if selected_ids:
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
            selected_frame = transaction_frame[
                transaction_frame["ID"].astype(str).isin(selected_ids)
            ]
            st.download_button(
                "Export selected",
                selected_frame.to_csv(index=False).encode("utf-8"),
                file_name=f"tabula-rasa-selected-{date.today()}.csv",
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
                category_map = {}
                for category in categories:
                    if category["kind"] != common_kind:
                        continue
                    category_id = str(category.get("id") or "").strip()
                    if category_id in category_paths:
                        category_map[category_paths[category_id]] = category_id
                if not category_map:
                    st.info(f"No categories of type {common_kind.lower()} are available.")
                else:
                    with st.form(
                        "transaction_bulk_category",
                        clear_on_submit=False,
                    ):
                        selected_category_name = st.selectbox(
                            "New category",
                            list(category_map),
                            key=(
                                "transaction_bulk_category_"
                                f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
                            ),
                        )
                        target_category_id = category_map[selected_category_name]
                        st.caption(
                            f"Review: change category for {len(selected_ids)} {common_kind.lower()} transaction(s)."
                        )
                        category_error = st.empty()
                        category_requested = st.form_submit_button(
                            "Change category",
                            type="primary",
                            width="stretch",
                        )
                    if category_requested:
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
                            report_error=category_error.error,
                        )

            total_amount = sum(abs(float(item["amount"])) for item in expected_selected)
            st.warning(
                f"Review: permanently delete {len(selected_ids)} transaction(s) "
                f"totaling {money(total_amount)}. Linked receipt references will be "
                "removed, but the Google Drive files will remain in Drive as unreferenced files."
            )
            confirm_delete = st.checkbox(
                "I understand these transactions will be permanently deleted and cannot be undone",
                key=(
                    "transaction_bulk_confirm_delete_"
                    f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}_"
                    f"{selected_snapshot_key}"
                ),
            )
            with st.form("transaction_bulk_delete", clear_on_submit=False):
                delete_error = st.empty()
                delete_requested = st.form_submit_button(
                    "Permanently delete selected",
                    type="primary",
                    width="stretch",
                )
            if delete_requested:
                if not confirm_delete:
                    delete_error.error(
                        "Confirm the permanent deletion before continuing."
                    )
                else:
                    def clear_recovery() -> None:
                        for item in selected_ids:
                            clear_receipt_creation_recovery(context, item)

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
                        on_success=clear_recovery,
                        report_error=delete_error.error,
                    )
        else:
            st.info("Select one or more visible transactions to use Bulk actions.")
    elif not transaction_frame.empty:

        def transaction_label(transaction_id: str) -> str:
            row = transaction_frame.loc[
                transaction_frame["ID"] == transaction_id
            ].iloc[0]
            return f"{row['Date']} — {row['Type']} — {money(row['Amount'])} — {transaction_id[:8]}"

        copy_source_id = str(
            st.session_state.get(_copy_source_key(context.profile_key), "") or ""
        )
        st.caption("Select a ledger row (or double-click it) to edit it.")
        with st.expander(
            "Copy transaction" if copy_source_id else "Edit transaction",
            expanded=bool(selected_rows) or bool(copy_source_id),
        ):
            edit_id = st.selectbox(
                "Transaction to edit",
                transaction_ids,
                format_func=transaction_label,
                key="edit_transaction_id",
                disabled=bool(copy_source_id),
            )
            if copy_source_id and copy_source_id != edit_id:
                _clear_copy_state(context.profile_key)
                st.rerun()
            selected = next(
                transaction for transaction in transactions if transaction["id"] == edit_id
            )
            copy_mode = copy_source_id == edit_id
            copy_generation = st.session_state.get(
                _copy_generation_key(context.profile_key),
                0,
            )
            edit_widget_scope = (
                f"{context.profile_key}_{edit_id}_copy_{copy_generation}"
                if copy_mode
                else f"{context.profile_key}_{edit_id}"
            )
            if copy_mode:
                st.info(
                    f"You are editing a new transaction copied from {edit_id}. "
                    "The source transaction will not be changed."
                )
            with st.form(
                "copy_transaction" if copy_mode else "edit_transaction",
                clear_on_submit=False,
            ):
                current_account_ids = [
                    selected["account_id"],
                    selected.get("to_account_id", ""),
                ]
                editable_account_ids = _editable_account_ids(
                    accounts, current_account_ids, copy_mode=copy_mode
                )
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
                payee_by_id = {str(item["id"]): str(item["name"]) for item in payees}
                payee_options = ["+ Add new payee"] + [
                    str(item["id"])
                    for item in payees
                    if item.get("active") == "TRUE" or item.get("id") == selected.get("payee_id")
                ]
                edited_payee_id = st.selectbox(
                    "Edit payee / customer",
                    payee_options,
                    index=(
                        payee_options.index(selected.get("payee_id", ""))
                        if selected.get("payee_id", "") in payee_options
                        else 0
                    ),
                    format_func=lambda value: payee_by_id.get(value, value),
                    key=f"edit_transaction_payee_{edit_widget_scope}",
                )
                edited_new_payee = ""
                if edited_payee_id == "+ Add new payee" or copy_mode:
                    edited_new_payee = st.text_input(
                        "Edit payee / customer",
                        value=selected.get("payee", "") if copy_mode else "",
                        key=f"edit_transaction_new_payee_{edit_widget_scope}",
                    )
                edited_reference = st.text_input(
                    "Edit reference",
                    value=selected.get("reference", ""),
                    key=f"edit_transaction_reference_{edit_widget_scope}",
                )
                edited_description = st.text_input(
                    "Edit description",
                    value=(
                        copied_transaction_description(selected)
                        if copy_mode
                        else selected.get("description", "")
                    ),
                    key=f"edit_transaction_description_{edit_widget_scope}",
                )
                receipt_uploads = None
                receipt_folder = None
                edit_error = st.empty()
                copy_accounts_valid = bool(edited_account_id) and (
                    selected["kind"] != "Transfer" or bool(edited_to_account_id)
                )
                if copy_mode:
                    st.caption(
                        "Receipts are not copied. Save this transaction first, "
                        "then attach receipts from its editor."
                    )
                    save_column, cancel_column = st.columns(2)
                    save_requested = save_column.form_submit_button(
                        "Save copied transaction",
                        type="primary",
                        width="stretch",
                        key=f"edit_transaction_copy_save_{edit_widget_scope}",
                    )
                    cancel_requested = cancel_column.form_submit_button(
                        "Cancel copy",
                        width="stretch",
                        key=f"edit_transaction_copy_cancel_{edit_widget_scope}",
                    )
                    delete_requested = False
                    confirm_delete = False
                else:
                    st.warning(
                        "Deleting this transaction is permanent and cannot be undone.",
                        icon="⚠️",
                    )
                    confirm_delete = st.checkbox(
                        "I understand this transaction will be permanently deleted",
                        key=f"edit_transaction_confirm_delete_{edit_widget_scope}",
                    )
                    receipt_folder = _receipt_folder(context)
                    receipt_uploads = render_editor_receipt_uploader(
                        context,
                        edit_id,
                    )
                    if receipt_uploads:
                        st.caption(
                            "Original filenames are kept safely. If a name "
                            "already exists, a numeric suffix will be added. "
                            "All selected files are validated before any "
                            "upload begins."
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
                    cancel_requested = False
                if copy_mode and not copy_accounts_valid:
                    st.warning(
                        "Choose active account(s) before saving this copied transaction."
                    )
                if save_requested:
                    copy_description = (
                        copied_transaction_description(
                            {"id": edit_id, "description": edited_description}
                        )
                        if copy_mode
                        else edited_description
                    )
                    transaction_data = {
                        "txn_date": edited_date,
                        "kind": selected["kind"],
                        "amount": edited_amount,
                        "account_id": edited_account_id,
                        "to_account_id": edited_to_account_id,
                        "category_id": edited_category_id,
                        "payee_id": (
                            ""
                            if copy_mode or edited_payee_id == "+ Add new payee"
                            else edited_payee_id
                        ),
                        "reference": edited_reference,
                        "description": copy_description,
                    }
                    payload = {
                        **transaction_data,
                        "id": edit_id,
                    }
                    if copy_mode:
                        payload.update(
                            {
                                "source_transaction_id": edit_id,
                                "copy_generation": copy_generation,
                            }
                        )
                    if copy_mode and not copy_accounts_valid:
                        edit_error.error(
                            "Choose active account(s) before saving this copied transaction."
                        )
                    elif (
                        selected["kind"] == "Transfer"
                        and edited_account_id == edited_to_account_id
                    ):
                        edit_error.error("Transfer accounts must be different.")
                    elif copy_mode:
                        context.confirmed_write(
                            "copy_transaction",
                            payload,
                            lambda: context.storage.create_transaction(
                                **transaction_data,
                                payee=edited_new_payee if copy_mode else "",
                            ),
                            "Transaction copied.",
                            on_confirmed=lambda result: st.session_state.__setitem__(
                                _pending_edit_transaction_key(context.profile_key),
                                result,
                            ),
                            on_success=lambda: _clear_copy_state(
                                context.profile_key
                            ),
                            report_error=edit_error.error,
                        )
                    else:
                        prepared_receipts: list[dict[str, object]] = []
                        receipt_preparation_failed = False
                        if receipt_uploads:
                            try:
                                prepared_receipts = prepare_editor_receipt_uploads(
                                    context,
                                    edit_id,
                                    receipt_uploads,
                                )
                            except (ValueError, GoogleDriveAccessError) as error:
                                receipt_preparation_failed = True
                                edit_error.error(
                                    "Receipt validation failed: "
                                    f"{error}"
                                )
                            except StorageError as error:
                                receipt_preparation_failed = True
                                edit_error.error(
                                    "The selected transaction could not be "
                                    f"rechecked before upload. {error}"
                                )
                        if not receipt_preparation_failed:
                            edit_payload = dict(payload)
                            if prepared_receipts:
                                edit_payload["receipt_upload_keys"] = [
                                    receipt["key"]
                                    for receipt in prepared_receipts
                                ]
                            context.confirmed_write(
                                "edit_transaction",
                                edit_payload,
                                lambda: context.storage.edit_transaction(
                                    edit_id,
                                    txn_date=edited_date,
                                    amount=edited_amount,
                                    account_id=edited_account_id,
                                    to_account_id=edited_to_account_id,
                                    category_id=edited_category_id,
                                    payee_id=(
                                        ""
                                        if edited_payee_id == "+ Add new payee"
                                        else edited_payee_id
                                    ),
                                    payee=edited_new_payee,
                                    reference=edited_reference,
                                    description=edited_description,
                                ),
                                "Transaction updated.",
                                on_confirmed=(
                                    lambda _result: process_editor_receipt_uploads(
                                        context,
                                        edit_id,
                                        prepared_receipts,
                                        receipt_folder,
                                    )
                                    if prepared_receipts and receipt_folder
                                    else None
                                ),
                                report_error=edit_error.error,
                            )
                if cancel_requested:
                    _clear_copy_state(context.profile_key)
                    st.rerun()
                if delete_requested:
                    if not confirm_delete:
                        edit_error.error(
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
                            report_error=edit_error.error,
                        )
            if copy_mode:
                st.divider()
                st.subheader("Receipt")
                st.info(
                    "No receipts are attached to this new transaction. "
                    "Save it first to upload or link a receipt."
                )
            else:
                render_receipts(
                    context,
                    selected=selected,
                    all_transactions=all_transactions,
                    edit_id=edit_id,
                )
