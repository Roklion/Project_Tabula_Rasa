"""Single-transaction edit, delete, and receipt hooks."""

from __future__ import annotations

from tabula_rasa.page_renderers.workflow_services import recurring_service
from collections.abc import Mapping
from collections.abc import Sequence
import streamlit as st
from tabula_rasa.ledger_presentation import money
from tabula_rasa.application.documents import DocumentError
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.recurrence_controls import (
    edit_defaults_with_pending_payload,
    render_recurrence_controls,
    restore_recurrence_controls,
)
from tabula_rasa.recurrence_state import transaction_edit_pending_state
from tabula_rasa.page_renderers.tag_selector import inline_tag_name_error
from tabula_rasa.page_renderers.tag_selector import schedule_tag_selector_reset
from tabula_rasa.page_renderers.tag_selector import tag_selector_error
from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
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
from .transaction_form import (
    render_transaction_fields,
    transaction_payload_from_draft,
    validate_transaction_draft,
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
        row = transaction_frame.loc[transaction_frame["ID"] == transaction_id].iloc[0]
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
        if "_journal" in selected:
            from .journal_editor import render_journal_entry_editor
            return render_journal_entry_editor(
                context, entry=selected["_journal"], accounts=accounts,
                categories=categories, account_paths=account_paths,
                category_paths=category_paths, payees=payees,
            )
        if str(selected.get("source_type") or "").strip().lower() == "depreciation":
            st.info("This depreciation entry is managed from Assets. Open Assets to view its schedule and posting history.")
            return True
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
        pending_recurrence = transaction_edit_pending_state(
            context.profile_key, edit_id
        )
        pending_configuration_revision = str(
            context.profile_secrets.get("spreadsheet_id")
            or context.configuration_revision
        )
        pending_recurrence.discard_if_configuration_changed(
            st.session_state,
            pending_configuration_revision,
        )
        pending_payload = pending_recurrence.payload(st.session_state)
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
            source_tag_ids = (
                _copyable_tag_ids(
                    tags,
                    [
                        str(tag_id).strip()
                        for tag_id in selected.get("tag_ids", [])
                        if str(tag_id).strip()
                    ],
                )
                if copy_mode
                else tuple(
                    str(tag_id).strip()
                    for tag_id in selected.get("tag_ids", [])
                    if str(tag_id).strip()
                )
            )
            draft = render_transaction_fields(
                mode="copy" if copy_mode else "edit",
                defaults=edit_defaults_with_pending_payload(
                    {
                        **selected,
                        "description": (
                            copied_transaction_description(selected)
                            if copy_mode
                            else selected.get("description", "")
                        ),
                        "tag_ids": source_tag_ids,
                    },
                    pending_payload if not copy_mode else None,
                ),
                account_ids=editable_account_ids,
                categories=categories,
                account_paths=account_paths,
                category_paths=category_paths,
                payees=payees,
                tags=tags,
                key_prefix="edit_transaction",
                key_scope=edit_widget_scope,
            )
            recurrence = None
            recurrence_slot = st.empty()
            if (
                not copy_mode
                and selected["kind"] == "Expense"
                and not selected.get("recurring_schedule_id")
            ):
                with recurrence_slot.container():
                    restore_recurrence_controls(
                        st.session_state,
                        pending_payload,
                        key_prefix=f"edit_transaction_{edit_widget_scope}",
                    )
                    recurrence = render_recurrence_controls(
                        label="Repeat this Expense",
                        key_prefix=f"edit_transaction_{edit_widget_scope}",
                        help_text=(
                            "Create a profile-local schedule and use this existing "
                            "transaction as its initial occurrence."
                        ),
                    )
            make_recurring = bool(recurrence and recurrence.enabled)
            receipt_uploads = None
            receipt_folder = None
            edit_error = st.empty()
            copy_accounts_valid = bool(draft["account_id"]) and (
                selected["kind"] != "Transfer" or bool(draft["to_account_id"])
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
                recurring_active = False
                recurring_status_error = False
                if recurring_id:
                    try:
                        recurring_active = (
                            recurring_service(context).get(
                                recurring_id, fresh=True
                            ).get("status")
                            == "active"
                        )
                    except StorageError:
                        recurring_status_error = True
                        st.warning(
                            "Recurring schedule status could not be refreshed; "
                            "deletion is disabled until the ledger can be refreshed."
                        )
                if recurring_active:
                    linked_dates = [
                        str(item.get("recurring_scheduled_date") or "")
                        for item in all_transactions
                        if str(item.get("recurring_schedule_id") or "") == recurring_id
                        and item.get("recurring_scheduled_date")
                    ]
                    if linked_dates and str(
                        selected.get("recurring_scheduled_date") or ""
                    ) == max(linked_dates):
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
                        {"id": edit_id, "description": draft["description"]}
                    )
                    if copy_mode
                    else draft["description"]
                )
                transaction_data = transaction_payload_from_draft(
                    draft,
                    description=copy_description,
                )
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
                elif draft_error := validate_transaction_draft(draft):
                    edit_error.error(draft_error)
                elif tag_error := tag_selector_error(
                    f"edit_transaction_tags_{edit_widget_scope}"
                ):
                    edit_error.error(tag_error)
                elif tag_error := inline_tag_name_error(draft["new_tag_name"]):
                    edit_error.error(tag_error)
                elif copy_mode:
                    context.confirmed_write(
                        "copy_transaction",
                        payload,
                        lambda: context.services.transactions.create(
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
                    # Kind is fixed by the existing row; Edit only changes its fields.
                    transaction_changes = dict(transaction_data)
                    transaction_changes.pop("kind")
                    prepared_receipts: list[dict[str, object]] = []
                    receipt_preparation_failed = False
                    if receipt_uploads:
                        try:
                            prepared_receipts = prepare_editor_receipt_uploads(
                                context,
                                edit_id,
                                receipt_uploads,
                            )
                        except (ValueError, DocumentError) as error:
                            receipt_preparation_failed = True
                            edit_error.error(f"Receipt validation failed: {error}")
                        except StorageError as error:
                            receipt_preparation_failed = True
                            edit_error.error(
                                "The selected transaction could not be "
                                f"rechecked before upload. {error}"
                            )
                    if not receipt_preparation_failed:
                        edit_payload = dict(payload)
                        if make_recurring:
                            pending_ids = pending_recurrence.ensure_ids(
                                st.session_state,
                                configuration_revision=(
                                    pending_configuration_revision
                                ),
                            )
                            edit_payload.update(
                                recurrence.schedule_fields(
                                    description=draft["description"],
                                    fallback_name="Recurring expense",
                                )
                            )
                            edit_payload = pending_recurrence.remember_payload(
                                st.session_state,
                                {**edit_payload, **pending_ids},
                            )
                        if prepared_receipts:
                            edit_payload["receipt_upload_keys"] = [
                                receipt["key"] for receipt in prepared_receipts
                            ]

                        def operation():
                            try:
                                return (
                                    recurring_service(context).from_transaction(
                                        edit_id,
                                        expected_transaction=selected,
                                        **edit_payload,
                                    )["transaction"]
                                    if make_recurring
                                    else context.services.transactions.update(
                                        edit_id,
                                        expected=selected,
                                        **transaction_changes,
                                    )
                                )
                            except (StorageConflictError, StorageValidationError):
                                if make_recurring:
                                    pending_recurrence.clear(st.session_state)
                                raise

                        context.confirmed_write(
                            (
                                "make_transaction_recurring"
                                if make_recurring
                                else "edit_transaction"
                            ),
                            edit_payload,
                            operation,
                            (
                                "Transaction updated and recurring schedule created."
                                if make_recurring
                                else "Transaction updated."
                            ),
                            on_confirmed=(
                                lambda _result: (
                                    process_editor_receipt_uploads(
                                        context,
                                        edit_id,
                                        prepared_receipts,
                                        receipt_folder,
                                    )
                                    if prepared_receipts and receipt_folder
                                    else None
                                )
                            ),
                            on_success=lambda: (
                                pending_recurrence.clear(st.session_state),
                                recurrence_slot.empty() if make_recurring else None,
                                schedule_tag_selector_reset(
                                    f"edit_transaction_tags_{edit_widget_scope}"
                                ),
                            ),
                            report_error=edit_error.error,
                        )
            if cancel_requested:
                _clear_copy_state(context.profile_key)
                st.rerun()
            if delete_requested:
                if recurring_status_error:
                    edit_error.error(
                        "Refresh the recurring schedule status before deleting this transaction."
                    )
                elif not confirm_delete:
                    edit_error.error(
                        "Confirm that you understand deletion is permanent."
                    )
                else:
                    payload = {"id": edit_id}
                    context.confirmed_write(
                        "delete_transaction",
                        payload,
                        lambda: context.services.transactions.delete(edit_id, expected=selected),
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
