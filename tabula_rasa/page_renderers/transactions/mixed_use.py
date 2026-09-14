"""Mixed-use source workflow for the Transactions page."""
from __future__ import annotations
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import replace
from datetime import date
from uuid import uuid4
import streamlit as st
from tabula_rasa.hierarchy import ordered_accounts, ordered_categories
from tabula_rasa.mixed_use import MixedUseAllocationError, calculate_allocated_amount
from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    render_tag_selector,
    tag_selector_error,
)
from tabula_rasa.page_renderers.transactions.payee_selector import (
    render_payee_selector,
)
from tabula_rasa.page_renderers.transactions.recurrence_controls import (
    edit_defaults_with_pending_payload,
    render_recurrence_controls,
    restore_recurrence_controls,
)
from tabula_rasa.recurrence_state import (
    mixed_use_create_pending_state,
    mixed_use_edit_pending_state,
)
from tabula_rasa.page_renderers.transactions.transaction_copy import (
    _copyable_tag_ids,
    _editable_account_ids,
    copied_transaction_description,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    clear_receipt_creation_recovery,
    handle_confirmed_transaction_receipts,
    prepare_receipt_uploads,
    prepare_editor_receipt_uploads,
    render_receipt_creation_recovery,
    render_receipt_uploader,
    render_receipts,
    receipt_creation_workflow_key,
    receipt_editor_workflow_key,
)
from tabula_rasa.storage import (
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    StorageValidationError,
    decode_receipt_references,
)
from tabula_rasa.storage.google_sheets import (
    _normalize_tag_ids,
    mixed_use_ledger_description,
)


class _MixedUseReceiptStorage:
    """Narrow receipt-storage capability scoped to one source record."""

    def __init__(
        self,
        storage,
        source_id: str,
        expected_source: Mapping[str, object],
        on_source_changed=None,
    ):
        self._storage = storage
        self._source_id = source_id
        self._expected_source = expected_source
        self._on_source_changed = on_source_changed

    def _refresh_expected_source(self) -> None:
        refreshed_source = self._storage.get_mixed_use_expense(self._source_id)
        self._expected_source = {
            **self._expected_source,
            "receipt_references": refreshed_source.get("receipt_references", ""),
        }
        if self._on_source_changed is not None:
            self._on_source_changed(self._expected_source)

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def link_transaction_receipt(self, transaction_id, *, reference):
        result = self._storage.link_mixed_use_receipt(
            self._source_id, reference=reference, expected_source=self._expected_source
        )
        self._refresh_expected_source()
        return result

    def unlink_transaction_receipt(self, transaction_id, *, file_id):
        result = self._storage.unlink_mixed_use_receipt(
            self._source_id, file_id=file_id, expected_source=self._expected_source
        )
        self._refresh_expected_source()
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


def _pending_create_ids(
    state: MutableMapping[str, object], profile: str
) -> tuple[str, str]:
    """Keep a create pair stable while an uncertain write is retried."""
    source_key = _key(profile, "pending_source_id")
    transaction_key = _key(profile, "pending_transaction_id")
    source_id = str(state.get(source_key) or uuid4())
    transaction_id = str(state.get(transaction_key) or uuid4())
    state[source_key] = source_id
    state[transaction_key] = transaction_id
    return source_id, transaction_id


def _preserve_pending_recurring_state(error: StorageConflictError) -> bool:
    """Keep retry state when a mixed-use projection needs inspection."""
    return "linked projection" in str(error).casefold()

def _mixed_use_copy_keys(profile: str) -> dict[str, str]:
    """Return the profile-local keys used by a mixed-use copy editor."""
    return {
        "source_id": _key(profile, "copy_source_id"),
        "snapshot": _key(profile, "copy_snapshot"),
        "new_source_id": _key(profile, "copy_new_source_id"),
        "new_transaction_id": _key(profile, "copy_new_transaction_id"),
        "generation": _key(profile, "copy_generation"),
    }


def _clear_mixed_use_copy(
    state: MutableMapping[str, object], profile: str
) -> None:
    """Discard a copy snapshot without touching its authoritative source."""
    keys = _mixed_use_copy_keys(profile)
    for name in ("source_id", "snapshot", "new_source_id", "new_transaction_id"):
        state.pop(keys[name], None)


def _fresh_mixed_use_copy_source(storage, source_id: str) -> dict[str, str]:
    """Re-read and validate a complete source/projection pair before copying."""
    source_id = str(source_id or "").strip()
    if not source_id:
        raise StorageError("Select a mixed-use expense before copying it.")
    try:
        return dict(storage.get_mixed_use_expense(source_id, _force_refresh=True))
    except StorageNotFoundError as error:
        raise StorageError("The selected mixed-use expense no longer exists.") from error


def _start_mixed_use_copy(
    state: MutableMapping[str, object],
    profile: str,
    source: Mapping[str, object],
) -> tuple[str, str]:
    """Store an independent copy snapshot and stable IDs for a new source."""
    keys = _mixed_use_copy_keys(profile)
    source_id = str(source.get("id") or "").strip()
    if not source_id:
        raise ValueError("Mixed-use copy source must have an ID")
    new_source_id = str(uuid4())
    new_transaction_id = str(uuid4())
    snapshot = dict(source)
    # Receipt links belong only to the authoritative source. Keep the copy
    # snapshot explicit so they cannot leak into a later create payload.
    snapshot["receipt_references"] = "[]"
    snapshot["description"] = copied_transaction_description(
        {"id": source_id, "description": snapshot.get("description", "")}
    )
    state[keys["source_id"]] = source_id
    state[keys["snapshot"]] = snapshot
    state[keys["new_source_id"]] = new_source_id
    state[keys["new_transaction_id"]] = new_transaction_id
    state[keys["generation"]] = int(state.get(keys["generation"], 0)) + 1
    state[_key(profile, "table_generation")] = int(
        state.get(_key(profile, "table_generation"), 0)
    ) + 1
    return new_source_id, new_transaction_id

def _active_ids(items: Sequence[Mapping[str, object]]) -> list[str]:
    return [
        str(item.get("id") or "")
        for item in ordered_accounts(items)
        if str(item.get("id") or "")
    ]


def _editable_mixed_use_account_ids(
    ordered_items: Sequence[Mapping[str, object]], current_account: str
) -> list[str]:
    """Keep a saved inactive account in its existing hierarchy position."""
    return [
        str(item["id"])
        for item in ordered_items
        if str(item.get("active", "")).upper() == "TRUE"
        or str(item.get("id") or "") == current_account
    ]


def _editable_mixed_use_category_ids(
    ordered_items: Sequence[Mapping[str, object]], current_category: str
) -> list[str]:
    """Keep a saved inactive Expense category in hierarchy order."""
    return [
        str(item["id"])
        for item in ordered_items
        if item.get("kind") == "Expense"
        and (
            str(item.get("active", "TRUE")).upper() == "TRUE"
            or str(item.get("id") or "") == current_category
        )
    ]

def _mixed_use_receipt_recovery_active(
    state: Mapping[str, object], profile: str, transaction_id: str
) -> bool:
    """Prevent a second mixed-use upload while the linked editor recovers."""
    if not transaction_id:
        return False
    return isinstance(
        state.get(receipt_editor_workflow_key(profile, transaction_id)),
        Mapping,
    )

def _mixed_use_selection_ids(
    source_ids: Sequence[str], selected_rows: Sequence[int]
) -> tuple[str, ...]:
    """Map dataframe row positions to stable mixed-use source IDs."""
    return tuple(
        str(source_ids[row])
        for row in selected_rows
        if isinstance(row, int) and 0 <= row < len(source_ids)
    )


def _clear_mixed_use_selection(
    state: MutableMapping[str, object],
    profile: str,
    *,
    clear_baseline: bool = True,
) -> None:
    """Clear the selected source and rotate the dataframe widget identity."""
    state[_key(profile, "selected_source_id")] = ""
    if clear_baseline:
        state.pop(_key(profile, "edit_baseline"), None)
        state.pop(_key(profile, "edit_baseline_source_id"), None)
    generation_key = _key(profile, "table_generation")
    state[generation_key] = int(state.get(generation_key, 0)) + 1


def _mixed_use_log_rows(
    sources: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
) -> list[dict[str, str]]:
    """Build display-only rows while keeping source IDs out of the table."""

    def receipt_indicator(item: Mapping[str, object]) -> str:
        try:
            return (
                "\U0001f4ce"
                if decode_receipt_references(item.get("receipt_references", ""))
                else ""
            )
        except StorageValidationError:
            # Keep incomplete source rows inspectable even when their receipt
            # metadata is malformed; receipt repair remains unavailable.
            return ""

    return [
        {
            "Date": str(item.get("txn_date", "")),
            "Payee": str(item.get("payee", "")),
            "Account": account_paths.get(str(item.get("account_id", "")), "Unknown"),
            "Category": category_paths.get(
                str(item.get("category_id", "")), "Unknown"
            ),
            "Total": f"${item.get('total_expense', '0.00')}",
            "Business %": str(item.get("business_use_percentage", "")),
            "Allocated": f"${item.get('allocated_amount', '0.00')}",
            "Rationale": str(item.get("allocation_rationale", "")),
            "Description": str(item.get("description", "")),
            "Receipt": receipt_indicator(item),
            "Recurring": "Recurring" if item.get("recurring_schedule_id") else "",
        }
        for item in sources
    ]


def _incomplete_source_ids(
    sources: Sequence[Mapping[str, object]],
    transactions: Sequence[Mapping[str, object]],
) -> set[str]:
    """Identify persisted sources whose projection still needs recovery."""
    transaction_ids = {
        str(item.get("id") or "")
        for item in transactions
        if str(item.get("id") or "")
    }
    projected_source_ids = {
        str(item.get("source_id") or "")
        for item in transactions
        if str(item.get("source_type") or "") == "mixed_use_expense"
        and str(item.get("source_id") or "")
    }
    return {
        str(source.get("id") or "")
        for source in sources
        if str(source.get("id") or "")
        and str(source.get("linked_transaction_id") or "") not in transaction_ids
        and str(source.get("id") or "") not in projected_source_ids
    }


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
    incomplete_source_ids: set[str] = set()
    try:
        sources = context.storage.list_mixed_use_expenses()
    except StorageError as error:
        try:
            raw_sources = context.storage.list_mixed_use_expense_sources(
                _force_refresh=True
            )
            transactions = context.storage.list_transactions(_force_refresh=True)
        except StorageError:
            context.report_storage_error(error)
            return
        incomplete_source_ids = _incomplete_source_ids(raw_sources, transactions)
        if not incomplete_source_ids:
            context.report_storage_error(error)
            return
        sources = [dict(item) for item in raw_sources]
        st.warning(
            "A mixed-use expense was saved without its ledger projection. "
            "The source is shown for inspection only; saving and automatic "
            "repair are disabled. Inspect Mixed-use expenses and the ledger "
            "before taking corrective action."
        )
        transaction_by_id = {
            str(item.get("id") or ""): item for item in transactions
        }
        for item in sources:
            linked = transaction_by_id.get(
                str(item.get("linked_transaction_id") or "")
            )
            source_has_tag_metadata = "tag_ids" in item
            item["tag_ids"] = _normalize_tag_ids(item.get("tag_ids", ""))
            if not source_has_tag_metadata and linked:
                # Keep source rows created before durable source tag metadata
                # recoverable from their linked projection.
                item["tag_ids"] = _normalize_tag_ids(linked.get("tag_ids", ""))
            item["ledger_status"] = (
                "incomplete"
                if str(item.get("id") or "") in incomplete_source_ids
                else "linked"
            )
            item["payee"] = next(
                (
                    str(payee.get("name") or "")
                    for payee in payees
                    if str(payee.get("id") or "") == str(item.get("payee_id") or "")
                ),
                "",
            )
    source_by_id = {str(item["id"]): item for item in sources}
    copy_keys = _mixed_use_copy_keys(profile)
    copy_snapshot = st.session_state.get(copy_keys["snapshot"])
    copy_source_id = str(st.session_state.get(copy_keys["source_id"]) or "")
    copy_mode = isinstance(copy_snapshot, Mapping) and bool(copy_source_id)
    if not copy_mode:
        # Partial state can be left behind by a profile switch or an
        # interrupted rerun. Never allow it to turn into a mutable editor.
        if any(
            st.session_state.get(copy_keys[name])
            for name in ("source_id", "snapshot", "new_source_id", "new_transaction_id")
        ):
            _clear_mixed_use_copy(st.session_state, profile)
        copy_snapshot = None
    recovery = st.session_state.get(receipt_creation_workflow_key(profile))
    if isinstance(recovery, Mapping):
        recovery_transaction_id = str(recovery.get("transaction_id") or "")
        recovery_source_id = str(recovery.get("mixed_use_source_id") or "")
        if not recovery_source_id:
            linked = next(
                (
                    item
                    for item in context.storage.list_transactions(_force_refresh=True)
                    if str(item.get("id") or "") == recovery_transaction_id
                ),
                None,
            )
            recovery_source_id = str(linked.get("source_id") or "") if linked else ""
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
        if recovery.get("mixed_use_source_id"):
            clear_receipt_creation_recovery(context, recovery_transaction_id)
            st.warning(
                "The mixed-use source and projection no longer exist. "
                "Receipt recovery was cleared; any uploaded files remain in "
                "Drive as unreferenced files."
            )
    selected_key = _key(profile, "selected_source_id")
    baseline_key = _key(profile, "edit_baseline")
    baseline_id_key = _key(profile, "edit_baseline_source_id")
    pending_source_key = _key(profile, "pending_source_id")
    pending_transaction_key = _key(profile, "pending_transaction_id")
    create_pending_recurrence = mixed_use_create_pending_state(profile)
    source_ids = [str(item["id"]) for item in sources]
    selection_scope_key = _key(profile, "selection_scope")
    selection_scope = (
        profile,
        tuple(source_ids),
        int(st.session_state.get("workbook_data_revision", 0)),
    )
    if st.session_state.get(selection_scope_key) != selection_scope:
        _clear_mixed_use_selection(st.session_state, profile)
        st.session_state[selection_scope_key] = selection_scope
    st.session_state.setdefault(selected_key, "")
    selected_id = str(st.session_state.get(selected_key, "") or "")
    if selected_id and selected_id not in source_by_id:
        _clear_mixed_use_selection(st.session_state, profile)
        selected_id = ""

    st.markdown("#### Mixed-use Expense Log")
    if sources:
        st.caption(
            "Select one row to edit it. The table is the source of truth for "
            "the edit target."
        )
        table_key = (
            f"mixed_use_log_{profile}_"
            f"{st.session_state.get(_key(profile, 'table_generation'), 0)}"
        )

        def select_mixed_use_source() -> None:
            selected_rows = st.session_state[table_key].selection.rows
            selected = _mixed_use_selection_ids(source_ids, selected_rows)
            if selected:
                st.session_state[selected_key] = selected[0]
            else:
                _clear_mixed_use_selection(st.session_state, profile)

        st.dataframe(
            _mixed_use_log_rows(sources, account_paths, category_paths),
            hide_index=True,
            width="stretch",
            key=table_key,
            on_select=("ignore" if copy_mode else select_mixed_use_source),
            selection_mode=[] if copy_mode else "single-row",
        )
        selected_id = str(st.session_state.get(selected_key, "") or "")
        copy_button = st.button(
            "Copy mixed-use expense",
            key=_key(profile, "copy_button"),
            disabled=(
                copy_mode
                or not selected_id
                or selected_id in incomplete_source_ids
            ),
            help=(
                "Select a complete mixed-use expense to create an independent copy."
                if not selected_id or selected_id not in incomplete_source_ids
                else "Incomplete mixed-use sources are available for inspection only."
            ),
        )
        if copy_button and selected_id:
            try:
                fresh_source = _fresh_mixed_use_copy_source(
                    context.storage, selected_id
                )
                _start_mixed_use_copy(st.session_state, profile, fresh_source)
            except StorageError as error:
                st.error(str(error))
            else:
                st.rerun()
        if selected_id:
            if st.button(
                "Add new mixed-use expense",
                key=_key(profile, "clear_selection"),
                disabled=copy_mode,
            ):
                _clear_mixed_use_selection(st.session_state, profile)
                st.session_state[selection_scope_key] = selection_scope
                st.rerun()
    else:
        st.info("No mixed-use expenses exist for this business profile.")
    source = source_by_id.get(selected_id)
    # A copy is based on its immutable initialization snapshot. The original
    # source may be edited or removed while this form is open.
    if copy_mode:
        source = None
    mixed_use_receipt_recovery = _mixed_use_receipt_recovery_active(
        st.session_state,
        profile,
        str(source.get("linked_transaction_id") or "") if source else "",
    )
    source_incomplete = bool(
        source and str(source.get("id") or "") in incomplete_source_ids
    )
    if source:
        if st.session_state.get(baseline_id_key) != selected_id:
            st.session_state[baseline_key] = dict(source)
            st.session_state[baseline_id_key] = selected_id
        expected_source = st.session_state.get(baseline_key, source)
    else:
        st.session_state.pop(baseline_key, None)
        st.session_state.pop(baseline_id_key, None)
        expected_source = None
        pending_source_id, pending_transaction_id = _pending_create_ids(
            st.session_state, profile
        )

    def update_receipt_baseline(updated_source):
        if st.session_state.get(baseline_id_key) == selected_id:
            st.session_state[baseline_key] = dict(updated_source)

    defaults = copy_snapshot if copy_mode else (source or {})
    copy_generation = int(st.session_state.get(copy_keys["generation"], 0))
    scope = (
        f"{profile}_{copy_source_id}_copy_{copy_generation}"
        if copy_mode
        else f"{profile}_{selected_id or 'new'}"
    )
    edit_pending_recurrence = (
        mixed_use_edit_pending_state(profile, str(source["id"]))
        if source and not source_incomplete
        else None
    )
    pending_configuration_revision = str(
        context.profile_secrets.get("spreadsheet_id")
        or context.configuration_revision
    )
    if edit_pending_recurrence is not None:
        edit_pending_recurrence.discard_if_configuration_changed(
            st.session_state,
            pending_configuration_revision,
        )
    pending_edit_payload = (
        edit_pending_recurrence.payload(st.session_state)
        if edit_pending_recurrence is not None
        else None
    )
    if source and not source_incomplete:
        defaults = edit_defaults_with_pending_payload(
            defaults, pending_edit_payload
        )
    elif not copy_mode:
        defaults = edit_defaults_with_pending_payload(
            defaults,
            create_pending_recurrence.payload(st.session_state),
        )
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
            f"mixed_recurring_{scope}",
            f"mixed_recurrence_unit_{scope}",
            f"mixed_recurrence_interval_{scope}",
            f"mixed_recurrence_name_{scope}",
            f"mixed_recurrence_end_{scope}",
        ],
    )
    ordered_category_items = ordered_categories(categories)
    category_ids = [
        str(item["id"])
        for item in ordered_category_items
        if item.get("kind") == "Expense"
    ]
    ordered_account_items = ordered_accounts(accounts)
    account_ids = _active_ids(ordered_account_items)
    active_account_ids = [
        str(item["id"])
        for item in ordered_account_items
        if str(item.get("active", "")).upper() == "TRUE"
    ]
    active_category_ids = [
        str(item["id"])
        for item in ordered_category_items
        if item.get("kind") == "Expense"
        and str(item.get("active", "TRUE")).upper() == "TRUE"
    ]
    if copy_mode:
        account_ids = _editable_account_ids(
            accounts,
            [str(defaults.get("account_id") or "")],
            copy_mode=True,
        )
        category_ids = list(active_category_ids)
    elif not source:
        account_ids, category_ids = active_account_ids, active_category_ids
    else:
        current_account = str(defaults.get("account_id") or "")
        current_category = str(defaults.get("category_id") or "")
        account_ids = _editable_mixed_use_account_ids(
            ordered_account_items, current_account
        )
        category_ids = _editable_mixed_use_category_ids(
            ordered_category_items, current_category
        )
    if not account_ids or not category_ids:
        st.warning("Create an active account and an Expense category before recording a mixed-use expense.")
        if copy_mode and st.button(
            "Cancel copy",
            key=f"mixed_cancel_copy_{scope}",
        ):
            _clear_mixed_use_copy(st.session_state, profile)
            st.rerun()
        return
    left, right = st.columns([3, 2])
    with left:
        if copy_mode:
            st.markdown("#### Copy mixed-use expense")
            st.caption(
                f"Create a new mixed-use source copied from {copy_source_id}. "
                "The original source and projection will not be changed."
            )
        elif source:
            st.markdown("#### Edit mixed-use expense")
            st.caption(
                "Editing the selected source updates its existing ledger "
                "projection."
            )
        else:
            st.markdown("#### Add mixed-use expense")
            st.caption(
                "Add mode creates a new source and one linked ledger "
                "projection."
            )
        txn_date = st.date_input("Date", date.fromisoformat(str(defaults.get("txn_date", date.today().isoformat()))), key=f"mixed_date_{scope}")
        c1, c2 = st.columns(2)
        current_account_id = str(defaults.get("account_id") or "")
        account_index = (
            account_ids.index(current_account_id)
            if current_account_id in account_ids
            else (None if copy_mode else 0)
        )
        account_id = c1.selectbox(
            "Account",
            account_ids,
            index=account_index,
            format_func=account_paths.get,
            key=f"mixed_account_{scope}",
        )
        current_category_id = str(defaults.get("category_id") or "")
        category_index = (
            category_ids.index(current_category_id)
            if current_category_id in category_ids
            else (None if copy_mode else 0)
        )
        category_id = c2.selectbox(
            "Category",
            category_ids,
            index=category_index,
            format_func=category_paths.get,
            key=f"mixed_category_{scope}",
        )
        current_payee = str(defaults.get("payee_id") or "")
        payee_id, new_payee_name = render_payee_selector(
            payees,
            key=f"mixed_payee_{scope}",
            selected_id=current_payee,
            preserve_selected_id=bool(source),
            selected_label=str(defaults.get("payee") or "") or None,
        )
        reference = st.text_input(
            "Reference (optional)",
            value=str(defaults.get("reference", "")),
            key=f"mixed_reference_{scope}",
        )
        source_tag_ids = _copyable_tag_ids(tags, defaults.get("tag_ids", ())) if copy_mode else defaults.get("tag_ids", ())
        tag_ids, new_tag_name = render_tag_selector(
            tags,
            label="Tags",
            key=f"mixed_tags_{scope}",
            selected_ids=source_tag_ids,
            preserve_inactive_ids=defaults.get("tag_ids", ()) if source else (),
        )
        c1, c2 = st.columns(2)
        total_expense = c1.text_input(
            "Total Expense",
            value=str(defaults.get("total_expense", "0.00") or "0.00"),
            key=f"mixed_total_{scope}",
            help="Enter a positive currency amount.",
        )
        business_use_percentage = c2.text_input(
            "Business Use %",
            value=str(defaults.get("business_use_percentage", "0") or "0"),
            key=f"mixed_percentage_{scope}",
            help="Greater than 0 and no more than 100; up to five decimal places.",
        )
        description = st.text_input(
            "Description / memo",
            value=str(defaults.get("description", "")),
            key=f"mixed_description_{scope}",
        )
        rationale = st.text_area("Allocation Rationale (required)", value=str(defaults.get("allocation_rationale", "")), key=f"mixed_rationale_{scope}")
        recurrence = None
        if (
            not copy_mode
            and not source_incomplete
            and (not source or not source.get("recurring_schedule_id"))
        ):
            restore_recurrence_controls(
                st.session_state,
                (
                    pending_edit_payload
                    if source
                    else create_pending_recurrence.payload(st.session_state)
                ),
                key_prefix="mixed",
                key_suffix=scope,
            )
            recurrence = render_recurrence_controls(
                label="Repeat this mixed-use Expense",
                key_prefix="mixed",
                key_suffix=scope,
                help_text=(
                    "Create a profile-local schedule and use this mixed-use "
                    "expense as its initial occurrence."
                ),
            )
        recurring = bool(recurrence and recurrence.enabled)
        if copy_mode:
            receipt_uploads = None
            st.info(
                "Receipts are not copied. Save this source first, then attach "
                "receipts from its editor."
            )
        else:
            receipt_uploads = render_receipt_uploader(
                key=f"mixed_receipts_{scope}",
                disabled=bool(
                    isinstance(recovery, Mapping)
                    and not recovery_source
                    or mixed_use_receipt_recovery
                ),
                help_text=(
                    "Resolve the pending receipt recovery in the transaction editor "
                    "before uploading receipts here."
                    if mixed_use_receipt_recovery
                    else "Resolve the pending receipt recovery in Add transaction "
                    "before uploading receipts here."
                    if isinstance(recovery, Mapping) and not recovery_source
                    else None
                ),
            )
        save_error = st.empty()
        save_label = (
            "Save copied mixed-use expense"
            if copy_mode
            else "Save changes"
            if source
            else "Save mixed-use expense"
        )
        if source_incomplete:
            st.info(
                "Inspection only: saving and repair are unavailable. Inspect "
                "this source in Mixed-use expenses and compare its ledger "
                "projection before taking corrective action."
            )
        if copy_mode and not account_id:
            st.warning(
                "Choose an active account before saving this copied mixed-use expense."
            )
        if copy_mode and not category_id:
            st.warning(
                "Choose an active Expense category before saving this copied mixed-use expense."
            )
        cancel_copy_requested = False
        if copy_mode:
            save_column, cancel_column = st.columns(2)
            save_button = save_column.button(
                save_label,
                type="primary",
                key=f"mixed_save_{scope}",
            )
            cancel_copy_requested = cancel_column.button(
                "Cancel copy",
                key=f"mixed_cancel_copy_{scope}",
            )
        else:
            save_button = st.button(
                save_label,
                type="primary",
                key=f"mixed_save_{scope}",
                disabled=source_incomplete,
            )
        if save_button:
            tag_error = inline_tag_name_error(new_tag_name)
            if (selector_error := tag_selector_error(f"mixed_tags_{scope}")):
                save_error.error(selector_error)
            elif tag_error:
                save_error.error(tag_error)
            elif copy_mode and not account_id:
                save_error.error(
                    "Choose an active account before saving this copied mixed-use expense."
                )
            elif copy_mode and not category_id:
                save_error.error(
                    "Choose an active Expense category before saving this copied mixed-use expense."
                )
            elif not rationale.strip():
                save_error.error("Allocation rationale is required.")
            elif isinstance(recovery, Mapping) and not recovery_source and receipt_uploads:
                save_error.error(
                    "Resolve the pending receipt recovery in Add transaction "
                    "before saving mixed-use receipts."
                )
            elif mixed_use_receipt_recovery and receipt_uploads:
                save_error.error(
                    "Resolve the pending receipt recovery in the transaction "
                    "editor before saving mixed-use receipts."
                )
            elif (
                not recurring
                and not source
                and not source_incomplete
                and not copy_mode
                and create_pending_recurrence.has_schedule(st.session_state)
            ):
                save_error.error(
                    "A previous recurring save is incomplete. Re-enable "
                    "Repeat this mixed-use Expense to retry it before "
                    "recording a different expense."
                )
            else:
                try:
                    if copy_mode:
                        prepared_receipts = []
                    elif source and not source_incomplete:
                        prepared_receipts = prepare_editor_receipt_uploads(
                            context,
                            str(source["linked_transaction_id"]),
                            receipt_uploads or [],
                        )
                    else:
                        prepared_receipts = prepare_receipt_uploads(
                            receipt_uploads or [],
                            existing_reference_count=(
                                len(
                                    decode_receipt_references(
                                        source.get("receipt_references", "")
                                    )
                                )
                                if source_incomplete and source
                                else 0
                            ),
                        )
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
                saved_description = (
                    copied_transaction_description(
                        {"id": copy_source_id, "description": description}
                    )
                    if copy_mode
                    else description
                )
                payload = {"txn_date": txn_date, "account_id": account_id, "category_id": category_id, "payee_id": payee_id, "new_payee_name": new_payee_name, "tag_ids": tag_ids, "new_tag_name": new_tag_name or "", "reference": reference, "description": saved_description, "total_expense": total_expense, "business_use_percentage": business_use_percentage, "allocation_rationale": rationale}

                if not (source and not source_incomplete):
                    payload["source_id"] = (
                        str(source["id"])
                        if source_incomplete
                        else (
                            str(st.session_state[copy_keys["new_source_id"]])
                            if copy_mode
                            else pending_source_id
                        )
                    )
                    payload["linked_transaction_id"] = (
                        str(source["linked_transaction_id"])
                        if source_incomplete
                        else (
                            str(st.session_state[copy_keys["new_transaction_id"]])
                            if copy_mode
                            else pending_transaction_id
                        )
                    )
                    if source_incomplete:
                        payload["expected_source"] = expected_source
                        payload["receipt_references"] = source.get(
                            "receipt_references", ""
                        )

                if recurring:
                    active_pending_recurrence = (
                        edit_pending_recurrence
                        if source and not source_incomplete
                        else create_pending_recurrence
                    )
                    pending_ids = active_pending_recurrence.ensure_ids(
                        st.session_state,
                        configuration_revision=(
                            pending_configuration_revision
                        ),
                    )
                    payload.update(
                        recurrence.schedule_fields(
                            description=description,
                            fallback_name="Recurring mixed-use expense",
                        )
                    )
                    payload = active_pending_recurrence.remember_payload(
                        st.session_state,
                        {**payload, **pending_ids},
                    )

                if source and not source_incomplete:
                    def operation():
                        return (
                            context.storage.create_recurring_expense_from_mixed_use(
                                source["id"],
                                expected_source=expected_source,
                                **payload,
                            )["source"]
                            if recurring
                            else context.storage.edit_mixed_use_expense(
                                source["id"],
                                expected_source=expected_source,
                                **payload,
                            )
                        )
                    action, success = (
                        (
                            "make_mixed_use_expense_recurring",
                            "Mixed-use expense updated and recurring schedule created.",
                        )
                        if recurring
                        else (
                            "edit_mixed_use_expense",
                            "Mixed-use expense updated.",
                        )
                    )
                else:

                    def operation():
                        try:
                            if recurring:
                                return context.storage.create_recurring_mixed_use_expense(**payload)["source"]
                            return context.storage.create_mixed_use_expense(**payload)
                        except StorageValidationError:
                            if recurring:
                                create_pending_recurrence.clear(st.session_state)
                            raise
                        except StorageConflictError as error:
                            if (
                                recurring
                                and not _preserve_pending_recurring_state(error)
                            ):
                                create_pending_recurrence.clear(st.session_state)
                            raise
                    action, success = (
                        ("copy_mixed_use_expense", "Mixed-use expense copied.")
                        if copy_mode
                        else ("create_mixed_use_expense", "Mixed-use expense saved.")
                    )

                pending_recurring_before_save = (
                    create_pending_recurrence.has_schedule(st.session_state)
                )
                recurring_create = (
                    recurring and not source and not source_incomplete and not copy_mode
                )

                def reset_after_success() -> None:
                    st.session_state.pop(baseline_key, None)
                    st.session_state.pop(baseline_id_key, None)
                    if recurring_create or not pending_recurring_before_save:
                        st.session_state.pop(pending_source_key, None)
                        st.session_state.pop(pending_transaction_key, None)
                    if recurring_create:
                        create_pending_recurrence.clear(st.session_state)
                    if edit_pending_recurrence is not None:
                        edit_pending_recurrence.clear(st.session_state)
                    if copy_mode:
                        _clear_mixed_use_copy(st.session_state, profile)
                        _clear_mixed_use_selection(st.session_state, profile)
                    context.schedule_widget_reset(_key(profile, "form_reset"))
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
                            on_source_changed=update_receipt_baseline,
                        ),
                    )
                    handle_confirmed_transaction_receipts(
                        receipt_context,
                        receipt_result,
                        prepared_receipts,
                        mixed_use_source_id=str(result["id"]),
                    )

                if prepared_receipts is not None:
                    context.confirmed_write(action, payload, operation, success, on_success=reset_after_success, on_confirmed=process_mixed_receipts, report_error=save_error.error)
        if cancel_copy_requested:
            _clear_mixed_use_copy(st.session_state, profile)
            st.rerun()
    with right:
        preview_description = (
            copied_transaction_description(
                {"id": copy_source_id, "description": description}
            )
            if copy_mode
            else description
        )
        payee_name = next(
            (
                str(item.get("name") or "")
                for item in payees
                if payee_id and str(item.get("id") or "") == payee_id
            ),
            new_payee_name,
        )
        _render_preview(mixed_use_preview(txn_date=txn_date, account=account_paths.get(account_id, account_id), payee=payee_name, category=category_paths.get(category_id, category_id), description=preview_description, total_expense=total_expense, business_use_percentage=business_use_percentage, allocation_rationale=rationale))
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
            render_receipts(
                replace(
                    context,
                    storage=_MixedUseReceiptStorage(
                        context.storage,
                        source["id"],
                        expected_source,
                        on_source_changed=update_receipt_baseline,
                    ),
                ),
                selected=linked,
                all_transactions=linked_transactions,
                edit_id=str(linked["id"]),
                section_title="Receipts",
                section_caption=(
                    "Manage receipts here; the linked ledger projection is read-only."
                ),
            )
        st.divider()
        if source_incomplete:
            st.info(
                "Inspection only: deletion is unavailable until the source and "
                "ledger relationship has been reviewed."
            )
        else:
            st.warning("Deleting this source permanently removes its linked ledger projection. Receipt files remain in Drive as unreferenced files.")
            recurring_id = str(source.get("recurring_schedule_id") or "")
            schedule_status_error = False
            if recurring_id:
                try:
                    schedule = context.storage.get_recurring_schedule(recurring_id, _force_refresh=True)
                    current_sources = context.storage.list_mixed_use_expenses()
                    latest = max(
                        (str(item.get("recurring_scheduled_date") or "") for item in current_sources
                         if item.get("recurring_schedule_id") == recurring_id
                         and item.get("recurring_scheduled_date")),
                        default="",
                    )
                    if schedule.get("status") == "active" and str(source.get("recurring_scheduled_date") or "") == latest:
                        st.warning(
                            "This is the latest current occurrence in an active recurring series. "
                            "Deleting it may make reconciliation regenerate the due date."
                        )
                except StorageError:
                    schedule_status_error = True
                    st.warning(
                        "Recurring schedule status could not be refreshed; "
                        "deletion is disabled until the ledger can be refreshed."
                    )
            confirmed = st.checkbox("I understand this deletion is permanent", key=f"mixed_confirm_delete_{scope}")
            delete_error = st.empty()
            if st.button("Permanently delete", type="primary", key=f"mixed_delete_{scope}"):
                if schedule_status_error:
                    delete_error.error(
                        "Refresh the recurring schedule status before deleting this expense."
                    )
                elif not confirmed:
                    delete_error.error("Confirm the permanent deletion before continuing.")
                else:
                    context.confirmed_write("delete_mixed_use_expense", {"id": source["id"], "expected_source": expected_source}, lambda: context.storage.delete_mixed_use_expense(source["id"], expected_source=expected_source), "Mixed-use expense deleted.", on_success=lambda: st.session_state.pop(selected_key, None), report_error=delete_error.error)
