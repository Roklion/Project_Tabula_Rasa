"""Transaction creation controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from uuid import uuid4

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.receipts import (
    RECEIPT_UPLOAD_TYPES,
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    receipt_creation_workflow_key,
    render_receipt_creation_recovery,
)
from tabula_rasa.page_renderers.transactions.payee_selector import (
    resolve_payee_selection,
)
from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    render_tag_selector,
    tag_selector_error,
)
from tabula_rasa.storage import StorageValidationError


def _pending_recurring_ids(
    state: dict[str, object], profile: str
) -> tuple[str, str]:
    """Keep a recurring schedule and initial transaction ID stable on retry."""
    schedule_key = f"recurring_pending_schedule_id_{profile}"
    transaction_key = f"recurring_pending_transaction_id_{profile}"
    schedule_id = str(state.get(schedule_key) or uuid4())
    transaction_id = str(state.get(transaction_key) or uuid4())
    state[schedule_key] = schedule_id
    state[transaction_key] = transaction_id
    return schedule_id, transaction_id


def _pending_recurring_create_exists(state: dict[str, object], profile: str) -> bool:
    """Keep an incomplete recurring create on its convergence path."""
    return bool(
        state.get(f"recurring_pending_schedule_id_{profile}")
        or state.get(f"recurring_pending_transaction_id_{profile}")
    )


def render_add_transaction(
    context: TransactionsContext,
    *,
    account_map: Mapping[str, str],
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
) -> None:
    """Render the existing profile-scoped transaction creation workflow."""
    recovery = st.session_state.get(
        receipt_creation_workflow_key(context.profile_key)
    )
    if isinstance(recovery, Mapping) and recovery.get("mixed_use_source_id"):
        # Mixed-use recovery is rendered by its source-aware tab; rendering it
        # here as well would register the same retry widget twice.
        return
    if render_receipt_creation_recovery(context):
        return
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
        "add_transaction_tags",
        "add_transaction_reference",
        "add_transaction_description",
        "add_transaction_receipts",
        "add_transaction_recurring",
        "add_transaction_recurrence_unit",
        "add_transaction_recurrence_interval",
        "add_transaction_recurrence_name",
        "add_transaction_recurrence_end",
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
        recurring = False
        recurrence_unit = recurrence_interval = recurrence_name = recurrence_end = None
        if kind == "Transfer":
            amount = st.number_input(
                "Amount",
                min_value=0.0,
                step=1.0,
                value=0.0,
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
                min_value=0.0,
                step=1.0,
                value=0.0,
                format="%.2f",
                key="add_transaction_amount",
            )
            if kind == "Expense":
                recurring = st.checkbox(
                    "Repeat this Expense",
                    key="add_transaction_recurring",
                    help="Create a profile-local schedule and this transaction as its initial occurrence.",
                )
                if recurring:
                    r1, r2 = st.columns(2)
                    recurrence_unit = r1.selectbox("Repeat every", ["day", "week", "month", "year"], key="add_transaction_recurrence_unit")
                    recurrence_interval = r2.number_input("Interval", min_value=1, value=1, step=1, key="add_transaction_recurrence_interval")
                    recurrence_name = st.text_input("Schedule name", key="add_transaction_recurrence_name")
                    recurrence_end = st.date_input("End date (optional)", value=None, key="add_transaction_recurrence_end")
        pending_schedule_key = f"recurring_pending_schedule_id_{context.profile_key}"
        pending_transaction_key = f"recurring_pending_transaction_id_{context.profile_key}"
        pending_payload_key = f"recurring_pending_payload_{context.profile_key}"
        pending_schedule_id = str(st.session_state.get(pending_schedule_key) or "")
        pending_transaction_id = str(st.session_state.get(pending_transaction_key) or "")
        source = st.selectbox(
            "To Account" if kind == "Income" else "From Account",
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
        active_payees = [
            payee for payee in payees if payee.get("active") == "TRUE"
        ]
        payee_options = [""] + [str(payee["id"]) for payee in active_payees]
        payee_by_id = {str(payee["id"]): str(payee["name"]) for payee in payees}
        payee_value = c1.selectbox(
            "Payee / customer",
            payee_options,
            format_func=lambda value: payee_by_id.get(
                value, "No payee" if value == "" else value
            ),
            key="add_transaction_payee",
            accept_new_options=True,
        )
        payee_id, new_payee_name = resolve_payee_selection(
            payee_value, active_payees, payee_options
        )
        reference = c2.text_input(
            "Reference (optional)",
            key="add_transaction_reference",
        )
        tag_ids, new_tag_name = render_tag_selector(
            tags,
            label="Tags",
            key="add_transaction_tags",
        )
        description = st.text_input(
            "Description / memo",
            key="add_transaction_description",
        )
        receipt_uploads = st.file_uploader(
            "Receipt (optional)",
            type=RECEIPT_UPLOAD_TYPES,
            accept_multiple_files=True,
            key="add_transaction_receipts",
            help=(
                "Select zero or more PDF, PNG, JPG, JPEG, WEBP, or HEIC "
                "files. Each file must be non-empty and no larger than 20 MB; "
                "the selected batch must not exceed 200 MB total."
            ),
        )
        save_error = st.empty()
        submitted = st.form_submit_button(
            "Save transaction", type="primary", width="stretch"
        )
        if submitted:
            if kind == "Transfer" and not to_account:
                save_error.error(
                    "Create a second active account before recording a transfer."
                )
            elif (tag_error := tag_selector_error("add_transaction_tags")):
                save_error.error(tag_error)
            elif (tag_error := inline_tag_name_error(new_tag_name)):
                save_error.error(tag_error)
            elif (
                kind == "Expense"
                and not recurring
                and _pending_recurring_create_exists(
                    st.session_state, context.profile_key
                )
            ):
                save_error.error(
                    "A previous recurring save is incomplete. Re-enable "
                    "Repeat this Expense to retry it before recording a "
                    "different expense."
                )
            else:
                payload = {
                    "txn_date": transaction_date,
                    "kind": kind,
                    "amount": amount,
                    "account_id": account_map[source],
                    "to_account_id": account_map.get(to_account, ""),
                    "category_id": category_id or "",
                    "payee_id": payee_id,
                    "new_payee_name": new_payee_name,
                    "tag_ids": tag_ids,
                    "new_tag_name": new_tag_name or "",
                    "description": description,
                    "reference": reference,
                }
                try:
                    prepared_receipts = prepare_receipt_uploads(
                        receipt_uploads or []
                    )
                except Exception as error:  # noqa: BLE001 - show safe validation
                    save_error.error(f"Receipt validation failed: {error}")
                else:
                    receipt_folder = None
                    drive_settings = context.profile_secrets.get("google_drive")
                    if isinstance(drive_settings, Mapping):
                        receipt_folder = drive_settings.get("receipt_folder")
                    if prepared_receipts and not (
                        isinstance(receipt_folder, Mapping)
                        and receipt_folder.get("id")
                    ):
                        save_error.error(
                            "Configure a Google Drive receipt folder for this "
                            "profile before saving a transaction with receipts."
                        )
                    else:
                        def clear_pending_recurring_ids() -> None:
                            st.session_state.pop(pending_schedule_key, None)
                            st.session_state.pop(pending_transaction_key, None)
                            st.session_state.pop(pending_payload_key, None)

                        if kind == "Expense" and recurring:
                            pending_schedule_id, pending_transaction_id = _pending_recurring_ids(
                                st.session_state, context.profile_key
                            )
                            payload.update({
                                "schedule_id": pending_schedule_id,
                                "transaction_id": pending_transaction_id,
                                "name": recurrence_name or description or "Recurring expense",
                                "recurrence_unit": recurrence_unit,
                                "recurrence_interval": recurrence_interval,
                                "end_date": recurrence_end,
                            })
                            previous_payload = st.session_state.get(pending_payload_key)
                            if isinstance(previous_payload, Mapping):
                                payload = {
                                    **previous_payload,
                                    "schedule_id": pending_schedule_id,
                                    "transaction_id": pending_transaction_id,
                                }
                            else:
                                st.session_state[pending_payload_key] = dict(payload)

                        def operation():
                            try:
                                return (
                                    context.storage.create_recurring_expense(**payload)["transaction"]
                                    if kind == "Expense" and recurring
                                    else context.storage.create_transaction(**payload)
                                )
                            except StorageValidationError:
                                if kind == "Expense" and recurring:
                                    clear_pending_recurring_ids()
                                raise

                        context.confirmed_write(
                            "create_transaction",
                            payload,
                            operation,
                            lambda _result: st.session_state.get(
                                "write_success_notice"
                            )
                            or (
                                "Transaction saved. Receipt processing needs "
                                "attention; use the recovery controls above."
                                if prepared_receipts
                                and st.session_state.get(
                                    receipt_creation_workflow_key(
                                        context.profile_key
                                    )
                                )
                                else "Transaction saved."
                            ),
                            on_success=(
                                lambda: (
                                    clear_pending_recurring_ids(),
                                    context.schedule_widget_reset("reset_add_transaction_form"),
                                )
                                if not prepared_receipts
                                else None
                            ),
                            on_confirmed=(
                                lambda result: (
                                    clear_pending_recurring_ids(),
                                    handle_confirmed_transaction_receipts(
                                        context,
                                        result,
                                        prepared_receipts,
                                    ),
                                )
                                if prepared_receipts
                                else None
                            ),
                            report_error=save_error.error,
                        )
