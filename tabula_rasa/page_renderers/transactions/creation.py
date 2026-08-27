"""Transaction creation controls."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.receipts import (
    RECEIPT_UPLOAD_TYPES,
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    receipt_creation_workflow_key,
    render_receipt_creation_recovery,
)


def render_add_transaction(
    context: TransactionsContext,
    *,
    account_map: Mapping[str, str],
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
) -> None:
    """Render the existing profile-scoped transaction creation workflow."""
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
        "add_transaction_reference",
        "add_transaction_description",
        "add_transaction_receipts",
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
        receipt_uploads = st.file_uploader(
            "Receipt (optional)",
            type=RECEIPT_UPLOAD_TYPES,
            accept_multiple_files=True,
            key="add_transaction_receipts",
            help=(
                "Select zero or more PDF, PNG, JPG, JPEG, WEBP, or HEIC "
                "files. Each file must be non-empty and no larger than 20 MB."
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
                        context.confirmed_write(
                            "create_transaction",
                            payload,
                            lambda: context.storage.create_transaction(**payload),
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
                                lambda: context.schedule_widget_reset(
                                    "reset_add_transaction_form"
                                )
                                if not prepared_receipts
                                else None
                            ),
                            on_confirmed=(
                                lambda result: handle_confirmed_transaction_receipts(
                                    context,
                                    result,
                                    prepared_receipts,
                                )
                                if prepared_receipts
                                else None
                            ),
                        )
