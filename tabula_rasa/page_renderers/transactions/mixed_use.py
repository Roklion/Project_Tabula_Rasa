"""Mixed-use source workflow for the Transactions page."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
import streamlit as st
from tabula_rasa.mixed_use import MixedUseAllocationError, calculate_allocated_amount
from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    render_tag_selector,
    tag_selector_error,
)
from tabula_rasa.page_renderers.transactions.payee_selector import resolve_payee_selection
from tabula_rasa.page_renderers.transactions.receipts import (
    RECEIPT_UPLOAD_TYPES,
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    render_receipt_creation_recovery,
    render_receipts,
    receipt_creation_workflow_key,
)
from tabula_rasa.storage import StorageError
from tabula_rasa.storage.google_sheets import mixed_use_ledger_description


class _MixedUseReceiptStorage:
    """Narrow receipt-storage capability scoped to one source record."""

    def __init__(self, storage, source_id: str, expected_source: Mapping[str, object]):
        self._storage = storage
        self._source_id = source_id
        self._expected_source = expected_source

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def link_transaction_receipt(self, transaction_id, *, reference):
        result = self._storage.link_mixed_use_receipt(
            self._source_id, reference=reference, expected_source=self._expected_source
        )
        self._expected_source = self._storage.get_mixed_use_expense(self._source_id)
        return result

    def unlink_transaction_receipt(self, transaction_id, *, file_id):
        result = self._storage.unlink_mixed_use_receipt(
            self._source_id, file_id=file_id, expected_source=self._expected_source
        )
        self._expected_source = self._storage.get_mixed_use_expense(self._source_id)
        return result

    def set_transaction_receipt_references(self, transaction_id, references):
        result = self._storage.set_mixed_use_receipt_references(
            self._source_id, references, expected_source=self._expected_source
        )
        self._expected_source = self._storage.get_mixed_use_expense(self._source_id)
        return result

    def remap_transaction_receipt(self, transaction_id, *, old_file_id, reference):
        result = self._storage.remap_mixed_use_receipt(
            self._source_id,
            old_file_id=old_file_id,
            reference=reference,
            expected_source=self._expected_source,
        )
        self._expected_source = self._storage.get_mixed_use_expense(self._source_id)
        return result

def mixed_use_preview(*, txn_date, account, payee, category, description, total_expense, business_use_percentage, allocation_rationale):
    """Build a side-effect-free ledger preview using the canonical calculator."""
    try:
        amount = calculate_allocated_amount(total_expense, business_use_percentage)
        allocated, status = f"{amount:.2f}", "ready"
    except MixedUseAllocationError as error:
        allocated, status = "—", str(error)
    memo, rationale = str(description or "").strip(), str(allocation_rationale or "").strip()
    if not rationale:
        status = "Allocation rationale is required"
    result_description = (
        mixed_use_ledger_description(memo, rationale)
        if rationale
        else memo
    )
    return {"date": txn_date.isoformat() if isinstance(txn_date, date) else str(txn_date or "—"), "account": str(account or "—"), "payee": str(payee or "—"), "category": str(category or "—"), "allocated_amount": allocated, "description": result_description or "—", "status": status}

def _key(profile: str, suffix: str) -> str:
    return f"mixed_use_{suffix}_{profile}"

def _active_ids(items: Sequence[Mapping[str, object]]) -> list[str]:
    return [str(item.get("id") or "") for item in items if str(item.get("id") or "")]

def _payee_options(payees: Sequence[Mapping[str, object]]) -> tuple[list[str], dict[str, str]]:
    by_id = {str(item.get("id") or ""): str(item.get("name") or "") for item in payees}
    options = [""]
    options.extend(str(item["id"]) for item in payees if str(item.get("active", "")).upper() == "TRUE")
    return options, by_id

def _source_label(source: Mapping[str, object], account_paths: Mapping[str, str]) -> str:
    return f"{source.get('txn_date', '')} — {source.get('payee', '') or source.get('description', '') or 'No payee'} — {account_paths.get(str(source.get('account_id')), 'Unknown account')} — {'$'}{source.get('total_expense', '0.00')} — {str(source.get('id', ''))[:8]}"

def _render_preview(preview: Mapping[str, str]) -> None:
    st.markdown("#### Ledger Result (read-only)")
    if preview["status"] != "ready":
        st.warning(f"Enter valid allocation inputs: {preview['status']}")
    else:
        st.success("Ready to post one Expense projection")
    st.write(f"Date: {preview['date']} | Account: {preview['account']} | Payee: {preview['payee']} | Category: {preview['category']}")
    st.metric("Allocated Amount", f"{'$'}{preview['allocated_amount']}")
    st.caption(f"Description: {preview['description']}")
    st.caption("Mixed-use projection • read-only in the regular ledger")

def render_mixed_use_expenses(context, *, accounts, categories, account_paths, category_paths, payees, tags) -> None:
    """Render profile-scoped mixed-use source CRUD and the live preview."""
    profile = context.profile_key
    st.subheader("Mixed-use expenses")
    st.caption("Save the full expense and business-use allocation; only the allocated amount enters the ledger.")
    try:
        sources = context.storage.list_mixed_use_expenses()
    except StorageError as error:
        context.report_storage_error(error)
        return
    source_by_id = {str(item["id"]): item for item in sources}
    recovery = st.session_state.get(receipt_creation_workflow_key(profile))
    if isinstance(recovery, Mapping):
        recovery_transaction_id = str(recovery.get("transaction_id") or "")
        linked = next(
            (
                item
                for item in context.storage.list_transactions(_force_refresh=True)
                if str(item.get("id") or "") == recovery_transaction_id
            ),
            None,
        )
        recovery_source_id = (
            str(linked.get("source_id") or "") if linked else ""
        )
        recovery_source = source_by_id.get(recovery_source_id)
        if recovery_source:
            recovery_context = replace(
                context,
                storage=_MixedUseReceiptStorage(
                    context.storage, recovery_source_id, recovery_source
                ),
            )
            render_receipt_creation_recovery(recovery_context)
            return
    selected_key = _key(profile, "selected_source_id")
    selected_id = str(st.session_state.get(selected_key, "") or "")
    if selected_id not in source_by_id:
        selected_id = ""
        st.session_state.pop(selected_key, None)
    choices = [""] + list(source_by_id)
    if sources:
        selected_id = st.selectbox("Edit an existing mixed-use expense (optional)", choices, index=choices.index(selected_id), format_func=lambda value: "Create new mixed-use expense" if not value else _source_label(source_by_id[value], account_paths), key=selected_key)
    source = source_by_id.get(selected_id)
    defaults = source or {}
    scope = f"{profile}_{selected_id or 'new'}"
    context.reset_widget_state_if_requested(
        _key(profile, "form_reset"),
        keys=[
            f"mixed_date_{scope}", f"mixed_account_{scope}",
            f"mixed_category_{scope}", f"mixed_payee_{scope}",
            f"mixed_reference_{scope}",
            f"mixed_description_{scope}", f"mixed_tags_{scope}",
            f"mixed_tags_{scope}__new_name", f"mixed_total_{scope}",
            f"mixed_percentage_{scope}", f"mixed_rationale_{scope}",
            f"mixed_receipts_{scope}",
        ],
    )
    account_ids = _active_ids(accounts)
    category_ids = [str(item["id"]) for item in categories if item.get("kind") == "Expense"]
    active_account_ids = [
        str(item["id"]) for item in accounts if str(item.get("active", "")).upper() == "TRUE"
    ]
    active_category_ids = [
        str(item["id"])
        for item in categories
        if item.get("kind") == "Expense"
        and str(item.get("active", "TRUE")).upper() == "TRUE"
    ]
    if not source:
        account_ids, category_ids = active_account_ids, active_category_ids
    else:
        current_account = str(defaults.get("account_id") or "")
        current_category = str(defaults.get("category_id") or "")
        account_ids = list(active_account_ids)
        category_ids = list(active_category_ids)
        if current_account and current_account not in account_ids:
            account_ids.append(current_account)
        if current_category and current_category not in category_ids:
            category_ids.append(current_category)
    if not account_ids or not category_ids:
        st.warning("Create an active account and an Expense category before recording a mixed-use expense.")
        return
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Add / edit source")
        if not source and render_receipt_creation_recovery(context):
            return
        txn_date = st.date_input("Date", date.fromisoformat(str(defaults.get("txn_date", date.today().isoformat()))), key=f"mixed_date_{scope}")
        c1, c2 = st.columns(2)
        account_id = c1.selectbox("Account", account_ids, index=account_ids.index(str(defaults.get("account_id", account_ids[0]))) if str(defaults.get("account_id", account_ids[0])) in account_ids else 0, format_func=account_paths.get, key=f"mixed_account_{scope}")
        category_id = c2.selectbox("Category", category_ids, index=category_ids.index(str(defaults.get("category_id", category_ids[0]))) if str(defaults.get("category_id", category_ids[0])) in category_ids else 0, format_func=category_paths.get, key=f"mixed_category_{scope}")
        options, payee_by_id = _payee_options(payees)
        current_payee = str(defaults.get("payee_id", ""))
        if source and current_payee and current_payee not in options:
            options.append(current_payee)
            payee_by_id[current_payee] = str(defaults.get("payee", "")) or (
                f"{current_payee} (inactive)"
            )
        payee_value = st.selectbox("Payee / customer", options, index=options.index(current_payee) if current_payee in options else 0, format_func=lambda value: payee_by_id.get(value, "No payee" if value == "" else value), key=f"mixed_payee_{scope}", accept_new_options=True)
        payee_id, new_payee_name = resolve_payee_selection(
            payee_value, payees, options
        )
        c1, c2 = st.columns(2)
        reference = c1.text_input("Reference (optional)", value=str(defaults.get("reference", "")), key=f"mixed_reference_{scope}")
        description = c2.text_input("Description / memo", value=str(defaults.get("description", "")), key=f"mixed_description_{scope}")
        tag_ids, new_tag_name = render_tag_selector(
            tags,
            label="Tags",
            key=f"mixed_tags_{scope}",
            selected_ids=defaults.get("tag_ids", ()),
            preserve_inactive_ids=defaults.get("tag_ids", ()) if source else (),
        )
        c1, c2 = st.columns(2)
        total_expense = c1.text_input("Total Expense", value=str(defaults.get("total_expense", "0.00") or "0.00"), key=f"mixed_total_{scope}", help="Enter a positive currency amount.")
        business_use_percentage = c2.text_input("Business Use %", value=str(defaults.get("business_use_percentage", "0") or "0"), key=f"mixed_percentage_{scope}", help="Greater than 0 and no more than 100; up to five decimal places.")
        rationale = st.text_area("Allocation Rationale (required)", value=str(defaults.get("allocation_rationale", "")), key=f"mixed_rationale_{scope}")
        receipt_uploads = st.file_uploader(
            "Receipt (optional)",
            type=RECEIPT_UPLOAD_TYPES,
            accept_multiple_files=True,
            key=f"mixed_receipts_{scope}",
        )
        save_error = st.empty()
        if st.button("Save changes" if source else "Save mixed-use expense", type="primary", key=f"mixed_save_{scope}"):
            tag_error = inline_tag_name_error(new_tag_name)
            if (selector_error := tag_selector_error(f"mixed_tags_{scope}")):
                save_error.error(selector_error)
            elif tag_error:
                save_error.error(tag_error)
            elif not rationale.strip():
                save_error.error("Allocation rationale is required.")
            else:
                try:
                    prepared_receipts = prepare_receipt_uploads(receipt_uploads or [])
                except Exception as error:  # noqa: BLE001 - safe validation message
                    save_error.error(f"Receipt validation failed: {error}")
                    prepared_receipts = None
                receipt_folder = None
                drive_settings = context.profile_secrets.get("google_drive")
                if isinstance(drive_settings, Mapping):
                    receipt_folder = drive_settings.get("receipt_folder")
                if prepared_receipts and not (
                    isinstance(receipt_folder, Mapping) and receipt_folder.get("id")
                ):
                    save_error.error(
                        "Configure a Google Drive receipt folder for this profile "
                        "before saving a transaction with receipts."
                    )
                    prepared_receipts = None
                if prepared_receipts is None:
                    # Keep the log and source actions visible after a receipt
                    # validation error; the write is skipped below.
                    pass
                payload = {"txn_date": txn_date, "account_id": account_id, "category_id": category_id, "payee_id": payee_id, "new_payee_name": new_payee_name, "tag_ids": tag_ids, "new_tag_name": new_tag_name or "", "reference": reference, "description": description, "total_expense": total_expense, "business_use_percentage": business_use_percentage, "allocation_rationale": rationale}
                if source:
                    payload["expected_source"] = source
                    def operation():
                        return context.storage.edit_mixed_use_expense(
                            source["id"], **payload
                        )
                    action, success = "edit_mixed_use_expense", "Mixed-use expense updated."
                else:
                    def operation():
                        return context.storage.create_mixed_use_expense(**payload)
                    action, success = "create_mixed_use_expense", "Mixed-use expense saved."
                def process_mixed_receipts(result):
                    if not prepared_receipts:
                        return
                    receipt_result = {
                        **result,
                        "id": result["linked_transaction_id"],
                    }
                    receipt_context = replace(
                        context,
                        storage=_MixedUseReceiptStorage(
                            context.storage,
                            result["id"],
                            result,
                        ),
                    )
                    handle_confirmed_transaction_receipts(
                        receipt_context, receipt_result, prepared_receipts
                    )

                if prepared_receipts is not None:
                    context.confirmed_write(action, payload, operation, success, on_success=lambda: context.schedule_widget_reset(_key(profile, "form_reset")), on_confirmed=process_mixed_receipts, report_error=save_error.error)
    with right:
        _render_preview(mixed_use_preview(txn_date=txn_date, account=account_paths.get(account_id, account_id), payee=payee_by_id.get(payee_id, new_payee_name), category=category_paths.get(category_id, category_id), description=description, total_expense=total_expense, business_use_percentage=business_use_percentage, allocation_rationale=rationale))
    st.markdown("#### Mixed-use Expense Log")
    if not sources:
        st.info("No mixed-use expenses exist for this business profile.")
    else:
        rows = [{"Date": item["txn_date"], "Payee / description": item.get("payee") or item.get("description", ""), "Account": account_paths.get(item.get("account_id", ""), "Unknown"), "Category": category_paths.get(item.get("category_id", ""), "Unknown"), "Total": f"{'$'}{item['total_expense']}", "Business %": item["business_use_percentage"], "Allocated": f"{'$'}{item['allocated_amount']}", "Rationale": item["allocation_rationale"], "Status": item.get("ledger_status", "linked")} for item in sources]
        st.dataframe(rows, hide_index=True, width="stretch")
    if source:
        linked_transactions = context.storage.list_transactions()
        linked = next(
            (
                item for item in linked_transactions
                if item.get("id") == source.get("linked_transaction_id")
            ),
            None,
        )
        if linked is not None:
            st.divider()
            st.markdown("#### Receipts")
            st.caption("Manage receipts here; the linked ledger projection is read-only.")
            render_receipts(
                replace(
                    context,
                    storage=_MixedUseReceiptStorage(
                        context.storage, source["id"], source
                    ),
                ),
                selected=linked,
                all_transactions=linked_transactions,
                edit_id=str(linked["id"]),
            )
        st.divider()
        st.warning("Deleting this source permanently removes its linked ledger projection. Receipt files remain in Drive as unreferenced files.")
        confirmed = st.checkbox("I understand this deletion is permanent", key=f"mixed_confirm_delete_{scope}")
        delete_error = st.empty()
        if st.button("Permanently delete", type="primary", key=f"mixed_delete_{scope}"):
            if not confirmed:
                delete_error.error("Confirm the permanent deletion before continuing.")
            else:
                context.confirmed_write("delete_mixed_use_expense", {"id": source["id"], "expected_source": source}, lambda: context.storage.delete_mixed_use_expense(source["id"], expected_source=source), "Mixed-use expense deleted.", on_success=lambda: st.session_state.pop(selected_key, None), report_error=delete_error.error)
