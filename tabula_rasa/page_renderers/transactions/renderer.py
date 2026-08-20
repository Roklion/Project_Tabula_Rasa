"""Transactions page rendering and receipt management."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import streamlit as st

from tabula_rasa.hierarchy import hierarchy_paths, ordered_hierarchy
from tabula_rasa.ledger_presentation import ledger_frame, money
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.creation import render_add_transaction
from tabula_rasa.presentation import render_page_header
from tabula_rasa.receipt_manifest import ReceiptManifestError, receipt_reference_from_drive_file
from tabula_rasa.storage import StorageError, decode_receipt_references
from tabula_rasa.google_drive import GoogleDriveError


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
        st.subheader("View & edit ledger")
        st.caption("Filter the ledger, select one row, and manage its details or receipts.")
        transaction_ledger_key = (
            "transaction_ledger_"
            f"{context.profile_key}_"
            f"{st.session_state.get('transaction_ledger_generation', 0)}"
        )
        c1, c2, c3 = st.columns(3)
        start = c1.date_input(
            "From", date(date.today().year, 1, 1), key="ledger_start"
        )
        end = c2.date_input("To", date.today(), key="ledger_end")
        filter_type = c3.selectbox(
            "Type",
            ["All", "Income", "Expense", "Transfer"],
            key=f"ledger_filter_type_{context.profile_key}",
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
        )
        selected_account_ids = [
            ledger_account_map[name] for name in selected_account_names
        ]
        try:
            all_transactions = context.storage.list_transactions()
            transactions = context.storage.list_transactions(
                start=start,
                end=end,
                kind=None if filter_type == "All" else filter_type,
                account_ids=selected_account_ids or None,
            )
        except StorageError as error:
            context.report_storage_error(error)
            st.stop()
        transaction_frame = ledger_frame(transactions, accounts, categories)
        transaction_frame["Receipt"] = [
            "\U0001f4ce" if transaction_has_receipts(transaction) else ""
            for transaction in transactions
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
        transaction_ids = transaction_frame["ID"].tolist()

        def select_ledger_transaction() -> None:
            selected_rows = st.session_state[
                transaction_ledger_key
            ].selection.rows
            if selected_rows:
                st.session_state["edit_transaction_id"] = transaction_ids[
                    selected_rows[0]
                ]

        ledger_event = st.dataframe(
            transaction_frame,
            hide_index=True,
            width="stretch",
            key=transaction_ledger_key,
            on_select=select_ledger_transaction,
            selection_mode="single-row",
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Receipt": st.column_config.TextColumn(
                    width="small",
                    help="This transaction has linked receipts.",
                ),
            },
        )
        if not transaction_frame.empty:
            selected_rows = ledger_event.selection.rows
            if st.session_state.get("edit_transaction_id") not in transaction_ids:
                st.session_state["edit_transaction_id"] = transaction_ids[0]

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
                            )
                st.divider()
                st.subheader("Receipt")
                selected_profile = context.profile_secrets
                drive_settings = selected_profile.get("google_drive")
                receipt_folder = (
                    drive_settings.get("receipt_folder")
                    if isinstance(drive_settings, Mapping)
                    else None
                )
                if not isinstance(receipt_folder, Mapping):
                    st.info(
                        "Connect Google Drive and select a receipt folder from "
                        "the local Business profiles page. Until then, store the "
                        f"receipt manually as `{edit_id}-original-file-name`."
                    )
                else:
                    try:
                        receipt_drive = context.get_drive_client(
                            context.profile_key,
                            context.configuration_revision,
                        )
                    except GoogleDriveError as error:
                        st.error(str(error))
                    else:
                        receipt_action_scope = (
                            f"{context.profile_key}-{edit_id}"
                        )
                        receipt_candidate_key = (
                            f"receipt-unlink-candidate-{receipt_action_scope}"
                        )
                        receipt_notice_key = (
                            f"receipt-unlink-notice-{receipt_action_scope}"
                        )
                        receipt_notice = st.session_state.pop(
                            receipt_notice_key,
                            None,
                        )
                        if receipt_notice:
                            st.success(str(receipt_notice))

                        raw_receipt_references = selected.get(
                            "receipt_references",
                            "",
                        )
                        references_ready = True
                        try:
                            receipt_references = decode_receipt_references(
                                raw_receipt_references
                            )
                        except StorageError as error:
                            references_ready = False
                            receipt_references = []
                            st.error(str(error))
                        if references_ready and raw_receipt_references == "":
                            try:
                                legacy_receipts = receipt_drive.list_receipts(
                                    profile_key=context.profile_key,
                                    transaction_id=edit_id,
                                    folder_id=str(receipt_folder["id"]),
                                )
                                receipt_references = [
                                    receipt_reference_from_drive_file(receipt)
                                    for receipt in legacy_receipts
                                    if receipt.get("id")
                                ]
                                context.storage.set_transaction_receipt_references(
                                    edit_id,
                                    receipt_references,
                                )
                            except (
                                GoogleDriveError,
                                ReceiptManifestError,
                                StorageError,
                            ) as error:
                                references_ready = False
                                st.error(
                                    "Existing receipt references could not be "
                                    f"initialized. {error}"
                                )

                        receipt_ids = {
                            reference["id"]
                            for reference in receipt_references
                        }
                        if (
                            st.session_state.get(receipt_candidate_key)
                            not in receipt_ids
                        ):
                            st.session_state.pop(receipt_candidate_key, None)
                        if references_ready and receipt_references:
                            for reference in receipt_references:
                                receipt_id = reference["id"]
                                name = reference["name"]
                                link = (
                                    "https://drive.google.com/open?id="
                                    f"{receipt_id}"
                                )
                                receipt_column, delete_column = st.columns(
                                    [4, 1]
                                )
                                with receipt_column:
                                    if link:
                                        st.link_button(name, link)
                                    else:
                                        st.caption(name)
                                with delete_column:
                                    if receipt_id and st.button(
                                        "Remove receipt",
                                        key=(
                                            "receipt-unlink-request-"
                                            f"{receipt_action_scope}-{receipt_id}"
                                        ),
                                        width="stretch",
                                    ):
                                        st.session_state[
                                            receipt_candidate_key
                                        ] = receipt_id
                                        st.rerun()
                                if (
                                    receipt_id
                                    and st.session_state.get(
                                        receipt_candidate_key
                                    )
                                    == receipt_id
                                ):
                                    st.warning(
                                        f"Remove `{name}` from this transaction? "
                                        "The file will remain in Google Drive."
                                    )
                                    cancel_column, confirm_column = st.columns(2)
                                    if cancel_column.button(
                                        "Cancel",
                                        key=(
                                            "receipt-unlink-cancel-"
                                            f"{receipt_action_scope}-{receipt_id}"
                                        ),
                                        width="stretch",
                                    ):
                                        st.session_state.pop(
                                            receipt_candidate_key,
                                            None,
                                        )
                                        st.rerun()
                                    if confirm_column.button(
                                        "Remove reference",
                                        type="primary",
                                        key=(
                                            "receipt-unlink-confirm-"
                                            f"{receipt_action_scope}-{receipt_id}"
                                        ),
                                        width="stretch",
                                    ):
                                        try:
                                            context.storage.unlink_transaction_receipt(
                                                edit_id,
                                                file_id=receipt_id,
                                            )
                                        except StorageError as error:
                                            st.error(
                                                "Receipt reference was not "
                                                "removed. "
                                                f"{error}"
                                            )
                                        else:
                                            st.session_state.pop(
                                                receipt_candidate_key,
                                                None,
                                            )
                                            st.session_state[
                                                receipt_notice_key
                                            ] = (
                                                f"Receipt removed: {name}. "
                                                "The file remains in Google "
                                                "Drive."
                                            )
                                            st.rerun()
                        if references_ready:
                            referenced_receipt_ids: set[str] = set()
                            uninitialized_transaction_ids: set[str] = set()
                            for transaction in all_transactions:
                                if transaction["id"] == edit_id:
                                    referenced_receipt_ids.update(
                                        receipt_ids
                                    )
                                    continue
                                raw_references = transaction.get(
                                    "receipt_references",
                                    "",
                                )
                                if raw_references == "":
                                    uninitialized_transaction_ids.add(
                                        transaction["id"]
                                    )
                                    continue
                                if raw_references == "[]":
                                    continue
                                try:
                                    referenced_receipt_ids.update(
                                        reference["id"]
                                        for reference in (
                                            decode_receipt_references(
                                                raw_references
                                            )
                                        )
                                    )
                                except StorageError:
                                    uninitialized_transaction_ids.add(
                                        transaction["id"]
                                    )
                            try:
                                profile_receipts = (
                                    receipt_drive.list_profile_receipts(
                                        profile_key=context.profile_key,
                                        folder_id=str(receipt_folder["id"]),
                                    )
                                )
                            except GoogleDriveError as error:
                                st.error(
                                    "Unreferenced Google Drive receipts could "
                                    f"not be listed. {error}"
                                )
                            else:
                                unreferenced_receipts = []
                                receipts_needing_backfill = 0
                                for receipt in profile_receipts:
                                    receipt_id = str(
                                        receipt.get("id", "")
                                    )
                                    properties = receipt.get(
                                        "appProperties"
                                    )
                                    legacy_transaction_id = (
                                        str(
                                            properties.get(
                                                "tabulaRasaTransaction",
                                                "",
                                            )
                                        )
                                        if isinstance(properties, Mapping)
                                        else ""
                                    )
                                    if (
                                        receipt_id
                                        and receipt_id
                                        not in referenced_receipt_ids
                                        and legacy_transaction_id
                                        not in (
                                            uninitialized_transaction_ids
                                        )
                                    ):
                                        try:
                                            unreferenced_receipts.append(
                                                receipt_reference_from_drive_file(
                                                    receipt
                                                )
                                            )
                                        except ReceiptManifestError:
                                            receipts_needing_backfill += 1
                                if receipts_needing_backfill:
                                    st.warning(
                                        f"{receipts_needing_backfill} receipt(s) "
                                        "need integrity metadata before they can be linked."
                                    )
                                if unreferenced_receipts:
                                    unreferenced_by_id = {
                                        receipt["id"]: receipt
                                        for receipt in unreferenced_receipts
                                    }
                                    existing_receipt_id = st.selectbox(
                                        "Unreferenced receipt",
                                        list(unreferenced_by_id),
                                        format_func=lambda file_id: (
                                            unreferenced_by_id[file_id][
                                                "name"
                                            ]
                                        ),
                                        key=(
                                            "receipt-existing-select-"
                                            f"{receipt_action_scope}"
                                        ),
                                        help=(
                                            "App-managed files in this "
                                            "profile's receipt folder that are "
                                            "not linked to another transaction."
                                        ),
                                    )
                                    if st.button(
                                        "Link selected receipt",
                                        key=(
                                            "receipt-existing-link-"
                                            f"{receipt_action_scope}"
                                        ),
                                    ):
                                        existing_receipt = (
                                            unreferenced_by_id[
                                                existing_receipt_id
                                            ]
                                        )
                                        try:
                                            context.storage.link_transaction_receipt(
                                                edit_id,
                                                reference=existing_receipt,
                                            )
                                        except StorageError as error:
                                            st.error(
                                                "The receipt could not be "
                                                f"linked. {error}"
                                            )
                                        else:
                                            st.session_state[
                                                receipt_notice_key
                                            ] = (
                                                "Receipt linked: "
                                                f"{existing_receipt['name']}"
                                            )
                                            st.rerun()
                                else:
                                    st.caption(
                                        "No unreferenced receipts are "
                                        "available in Google Drive."
                                    )
                            receipt_upload = st.file_uploader(
                                "Upload receipt",
                                type=[
                                    "pdf",
                                    "png",
                                    "jpg",
                                    "jpeg",
                                    "webp",
                                    "heic",
                                ],
                                accept_multiple_files=False,
                                key=f"receipt-upload-{edit_id}",
                            )
                            if receipt_upload is not None:
                                receipt_bytes = receipt_upload.getvalue()
                                st.caption(
                                    "The original filename will be kept. If "
                                    "that name already exists, a numeric "
                                    "suffix will be added."
                                )
                                if st.button(
                                    "Upload receipt to Google Drive",
                                    type="primary",
                                    key=f"receipt-upload-button-{edit_id}",
                                ):
                                    try:
                                        uploaded_receipt = (
                                            receipt_drive.upload_receipt(
                                                profile_key=(
                                                    context.profile_key
                                                ),
                                                transaction_id=edit_id,
                                                folder_id=str(
                                                    receipt_folder["id"]
                                                ),
                                                original_name=(
                                                    receipt_upload.name
                                                ),
                                                content=receipt_bytes,
                                                mime_type=(
                                                    receipt_upload.type
                                                    or "application/octet-stream"
                                                ),
                                            )
                                        )
                                    except GoogleDriveError as error:
                                        st.error(str(error))
                                    else:
                                        try:
                                            context.storage.link_transaction_receipt(
                                                edit_id,
                                                reference=(
                                                    receipt_reference_from_drive_file(
                                                        uploaded_receipt
                                                    )
                                                ),
                                            )
                                        except (
                                            KeyError,
                                            ReceiptManifestError,
                                            StorageError,
                                        ) as error:
                                            st.error(
                                                "The receipt was uploaded to "
                                                "Google Drive but could not be "
                                                "linked to this transaction. "
                                                f"Retry the upload. {error}"
                                            )
                                        else:
                                            st.success(
                                                "Receipt uploaded and linked: "
                                                f"{uploaded_receipt.get('name', receipt_upload.name)}"
                                            )
                                            st.rerun()
