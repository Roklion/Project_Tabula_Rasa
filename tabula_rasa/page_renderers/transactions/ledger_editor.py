"""Single-transaction edit, delete, and receipt hooks."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
import streamlit as st
from tabula_rasa.ledger_presentation import money
from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.payee_selector import resolve_payee_selection
from tabula_rasa.page_renderers.tag_selector import inline_tag_name_error
from tabula_rasa.page_renderers.tag_selector import render_tag_selector
from tabula_rasa.page_renderers.tag_selector import schedule_tag_selector_reset
from tabula_rasa.page_renderers.tag_selector import tag_selector_error
from tabula_rasa.storage import StorageError
from .receipt_workflows import _receipt_folder
from .receipt_workflows import clear_receipt_creation_recovery
from .receipt_editor import (
    prepare_editor_receipt_uploads,
    process_editor_receipt_uploads,
    render_editor_receipt_uploader,
)
from .receipt_display import render_receipts
from .transaction_copy import (
    _clear_copy_state,
    _copy_generation_key,
    _copy_source_key,
    _copyable_tag_ids,
    _editable_account_ids,
    _finish_copy_save,
    _pending_edit_transaction_key,
    copied_transaction_description,
)
from .ledger_filters import (
    transaction_is_mixed_use,
)

def render_transaction_editor(
    context: TransactionsContext,
    *,
    accounts: Sequence[Mapping[str, object]],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    transaction_frame,
    transactions: Sequence[Mapping[str, object]],
    transaction_ids: Sequence[str],
    selected_rows: Sequence[int],
    all_transactions: Sequence[Mapping[str, object]],
) -> bool:
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
        if transaction_is_mixed_use(selected):
            st.info(
                "This transaction is generated from a mixed-use expense "
                "and is managed from the Mixed-use expenses tab. Switch "
                "to that tab to edit, delete, or manage receipts."
            )
            return True
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
            available_payees = [
                item
                for item in payees
                if item.get("active") == "TRUE"
                or (
                    not copy_mode
                    and item.get("id") == selected.get("payee_id")
                )
            ]
            payee_options = [""] + [
                str(item["id"]) for item in available_payees
            ]
            payee_value = st.selectbox(
                "Edit payee / customer",
                payee_options,
                index=(
                    payee_options.index(selected.get("payee_id", ""))
                    if selected.get("payee_id", "") in payee_options
                    else 0
                ),
                format_func=lambda value: payee_by_id.get(
                    value, "No payee" if value == "" else value
                ),
                key=f"edit_transaction_payee_{edit_widget_scope}",
                accept_new_options=True,
            )
            edited_payee_id, edited_new_payee = resolve_payee_selection(
                payee_value, available_payees, payee_options
            )
            edited_reference = st.text_input(
                "Edit reference",
                value=selected.get("reference", ""),
                key=f"edit_transaction_reference_{edit_widget_scope}",
            )
            source_tag_ids = [
                str(tag_id).strip()
                for tag_id in selected.get("tag_ids", [])
                if str(tag_id).strip()
            ]
            if copy_mode:
                source_tag_ids = _copyable_tag_ids(tags, source_tag_ids)
            edited_tag_ids, edited_new_tag_name = render_tag_selector(
                tags,
                label="Edit tags",
                key=f"edit_transaction_tags_{edit_widget_scope}",
                selected_ids=source_tag_ids,
                preserve_inactive_ids=(
                    source_tag_ids if not copy_mode else ()
                ),
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
                recurring_id = str(selected.get("recurring_schedule_id") or "")
                if recurring_id:
                    linked_dates = [
                        str(item.get("txn_date") or "")
                        for item in all_transactions
                        if str(item.get("recurring_schedule_id") or "") == recurring_id
                    ]
                    if linked_dates and str(selected.get("txn_date") or "") == max(linked_dates):
                        st.warning(
                            "This is the latest current occurrence in an active recurring series. "
                            "Deleting it may make the next reconciliation regenerate the due date."
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
                with delete_column:
                    with st.container(key="destructive_transaction_edit_delete"):
                        delete_requested = st.form_submit_button(
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
                    "payee_id": edited_payee_id,
                    "new_payee_name": edited_new_payee,
                    "tag_ids": edited_tag_ids,
                    "new_tag_name": edited_new_tag_name or "",
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
                elif (
                    tag_error := tag_selector_error(
                        f"edit_transaction_tags_{edit_widget_scope}"
                    )
                ):
                    edit_error.error(tag_error)
                elif (tag_error := inline_tag_name_error(edited_new_tag_name)):
                    edit_error.error(tag_error)
                elif copy_mode:
                    context.confirmed_write(
                        "copy_transaction",
                        payload,
                        lambda: context.storage.create_transaction(
                            **transaction_data,
                        ),
                        "Transaction copied.",
                        on_confirmed=lambda result: st.session_state.__setitem__(
                            _pending_edit_transaction_key(context.profile_key),
                            result,
                        ),
                        on_success=lambda: _finish_copy_save(
                            context.profile_key,
                            f"edit_transaction_tags_{edit_widget_scope}",
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
                                payee_id=edited_payee_id,
                                new_payee_name=edited_new_payee,
                                tag_ids=edited_tag_ids,
                                new_tag_name=edited_new_tag_name or "",
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
                            on_success=lambda: schedule_tag_selector_reset(
                                f"edit_transaction_tags_{edit_widget_scope}"
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
    return False
