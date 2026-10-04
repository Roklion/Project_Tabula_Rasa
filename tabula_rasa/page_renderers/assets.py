"""Fixed-asset register and quarterly depreciation page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
import json

import pandas as pd
import streamlit as st

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.depreciation import STRAIGHT_LINE_METHOD
from tabula_rasa.storage.google_sheets.depreciation_posting import (
    asset_schedule,
    depreciation_entry_id,
)
from tabula_rasa.presentation import render_global_footer, render_page_header
from tabula_rasa.storage import (
    ASSET_TYPES,
    GoogleSheetsStorage,
    StorageError,
    decode_receipt_references,
)


@dataclass(frozen=True)
class AssetsContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]
    services: ApplicationServices | None = None


def _overrides(asset: dict) -> dict[int, dict[str, str]]:
    raw = json.loads(str(asset.get("schedule_overrides") or "{}"))
    return {int(key): dict(value) for key, value in raw.items()}


def _schedule(asset: dict):
    posted_ids = set(asset.get("posted_entry_ids", []))
    return [
        replace(period, posting_status="Posted", journal_entry_id=entry_id)
        if (entry_id := depreciation_entry_id(asset["id"], period.sequence))
        in posted_ids
        else period
        for period in asset_schedule(asset)
    ]


def _display_status(asset: dict, *, today: date) -> str:
    if asset["status"] == "retired":
        return "Retired"
    schedule = _schedule(asset)
    if schedule and all(period.posting_status == "Posted" for period in schedule):
        return "Fully depreciated"
    return "Active"


def _asset_frame(assets: list[dict], *, today: date) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Asset": asset["name"],
                "Type": asset["asset_type"],
                "Status": _display_status(asset, today=today),
                "Acquired": asset["acquisition_date"],
                "Depreciation starts": asset["depreciation_start_date"],
                "Cost basis": float(Decimal(asset["cost_basis"])),
                "Salvage value": float(Decimal(asset["salvage_value"])),
                "Life (quarters)": int(asset["useful_life_quarters"]),
                "Method": asset["depreciation_method"],
                "Vendor / payee": asset.get("payee", ""),
                "Tags": ", ".join(asset.get("tags", [])),
                "ID": asset["id"],
            }
            for asset in assets
        ]
    )


def _transaction_label(transaction: dict) -> str:
    payee = transaction.get("payee") or transaction.get("description") or "Transaction"
    return (
        f"{transaction['txn_date']} · {payee} · ${Decimal(transaction['amount']):,.2f} "
        f"· {transaction['id'][:8]}"
    )


def _show_source_context(transaction: dict | None, source_id: str) -> None:
    if not source_id:
        return
    if transaction is None:
        st.warning(
            "The linked acquisition transaction is no longer available. "
            "The asset record and schedule remain valid."
        )
        return
    receipts = decode_receipt_references(transaction.get("receipt_references", ""))
    if receipts:
        names = ", ".join(str(item.get("name") or item["id"]) for item in receipts)
        st.caption(f"Linked transaction receipts: {names}")
    else:
        st.caption("The linked acquisition transaction has no receipt attached.")


def _asset_fields(
    prefix: str,
    *,
    profile_key: str,
    payees: list[dict],
    tags: list[dict],
    transactions: list[dict],
    accounts: list[dict] | None = None,
    categories: list[dict] | None = None,
    initial: dict | None = None,
    schedule_locked: bool = False,
) -> dict:
    initial = initial or {}
    payee_ids = [""] + [item["id"] for item in payees]
    payee_names = {item["id"]: item["name"] for item in payees}
    transaction_ids = [""] + [item["id"] for item in transactions]
    transaction_by_id = {item["id"]: item for item in transactions}
    selected_tag_ids = [
        tag_id
        for tag_id in initial.get("tag_ids", [])
        if any(item["id"] == tag_id for item in tags)
    ]

    c1, c2 = st.columns(2, gap="small")
    name = c1.text_input(
        "Asset name",
        value=initial.get("name", ""),
        key=f"{prefix}_name_{profile_key}",
    )
    asset_type = c2.selectbox(
        "Asset type",
        list(ASSET_TYPES),
        index=(
            list(ASSET_TYPES).index(initial["asset_type"])
            if initial.get("asset_type") in ASSET_TYPES
            else 0
        ),
        key=f"{prefix}_type_{profile_key}",
    )
    c1, c2, c3 = st.columns(3, gap="small")
    acquisition_date = c1.date_input(
        "Acquisition date",
        value=date.fromisoformat(
            initial.get("acquisition_date", date.today().isoformat())
        ),
        key=f"{prefix}_acquired_{profile_key}",
    )
    start_date = c2.date_input(
        "Depreciation start date",
        value=date.fromisoformat(
            initial.get("depreciation_start_date", acquisition_date.isoformat())
        ),
        key=f"{prefix}_start_{profile_key}",
        disabled=schedule_locked,
        help="This is the first quarterly schedule date; no partial-quarter proration is applied.",
    )
    life_quarters = c3.number_input(
        "Useful life (quarters)",
        min_value=1,
        step=1,
        value=int(initial.get("useful_life_quarters", 20)),
        key=f"{prefix}_life_{profile_key}",
        disabled=schedule_locked,
        help="For example, a five-year life is 20 quarters.",
    )
    c1, c2, c3 = st.columns(3, gap="small")
    cost_basis = c1.number_input(
        "Cost basis",
        min_value=0.0,
        value=float(initial.get("cost_basis", 0) or 0),
        format="%.2f",
        key=f"{prefix}_cost_{profile_key}",
        disabled=schedule_locked,
    )
    salvage_value = c2.number_input(
        "Salvage value",
        min_value=0.0,
        value=float(initial.get("salvage_value", 0) or 0),
        format="%.2f",
        key=f"{prefix}_salvage_{profile_key}",
        disabled=schedule_locked,
    )
    c3.selectbox(
        "Depreciation method",
        [STRAIGHT_LINE_METHOD],
        disabled=True,
        key=f"{prefix}_method_{profile_key}",
    )
    st.caption(
        "Posting accounts: an Expense category is the debit account in Simple Ledger; accumulated depreciation is the non-cash credit account."
    )
    posting_accounts = {}
    c1, c2 = st.columns(2, gap="small")
    for container, field, label, candidates in (
        (
            c1,
            "depreciation_expense_account_id",
            "Depreciation expense account",
            [item for item in (categories or []) if item["kind"] == "Expense"],
        ),
        (
            c2,
            "accumulated_depreciation_account_id",
            "Accumulated depreciation account",
            [
                item
                for item in (accounts or [])
                if item["type"] == "Other" and item["classification"] == "Asset"
            ],
        ),
    ):
        names = {item["id"]: item["name"] for item in candidates}
        ids = [""] + list(names)
        current_id = initial.get(field, "")
        posting_accounts[field] = container.selectbox(
            label,
            ids,
            index=ids.index(current_id) if current_id in ids else 0,
            format_func=lambda value, names=names: names.get(
                value, "Select an account"
            ),
            disabled=bool(initial.get("posted_entry_ids")),
            key=f"{prefix}_{field}_{profile_key}",
        )
    c1, c2 = st.columns(2, gap="small")
    current_payee = initial.get("payee_id", "")
    payee_id = c1.selectbox(
        "Vendor / payee (optional)",
        payee_ids,
        index=payee_ids.index(current_payee) if current_payee in payee_ids else 0,
        format_func=lambda value: payee_names.get(value, "No vendor / payee"),
        key=f"{prefix}_payee_{profile_key}",
    )
    tag_ids = c2.multiselect(
        "Tags (optional)",
        [item["id"] for item in tags],
        default=selected_tag_ids,
        format_func=lambda value: next(
            item["name"] for item in tags if item["id"] == value
        ),
        key=f"{prefix}_tags_{profile_key}",
    )
    current_source = initial.get("source_transaction_id", "")
    if current_source and current_source not in transaction_ids:
        transaction_ids.append(current_source)
    source_transaction_id = st.selectbox(
        "Source acquisition transaction (optional)",
        transaction_ids,
        index=transaction_ids.index(current_source)
        if current_source in transaction_ids
        else 0,
        format_func=lambda value: (
            "No linked transaction"
            if not value
            else _transaction_label(transaction_by_id[value])
            if value in transaction_by_id
            else f"Missing transaction · {value}"
        ),
        key=f"{prefix}_source_{profile_key}",
    )
    _show_source_context(
        transaction_by_id.get(source_transaction_id), source_transaction_id
    )
    reference = st.text_input(
        "Reference (optional)",
        value=initial.get("reference", ""),
        key=f"{prefix}_reference_{profile_key}",
    )
    notes = st.text_area(
        "Description / notes (optional)",
        value=initial.get("notes", ""),
        key=f"{prefix}_notes_{profile_key}",
    )
    values = {
        **posting_accounts,
        "name": name,
        "asset_type": asset_type,
        "notes": notes,
        "acquisition_date": acquisition_date,
        "depreciation_method": STRAIGHT_LINE_METHOD,
        "payee_id": payee_id,
        "reference": reference,
        "tag_ids": tag_ids,
        "source_transaction_id": source_transaction_id,
    }
    if not schedule_locked:
        values.update(
            {
                "depreciation_start_date": start_date,
                "cost_basis": cost_basis,
                "salvage_value": salvage_value,
                "useful_life_quarters": int(life_quarters),
            }
        )
    return values


def _render_schedule(context: AssetsContext, asset: dict) -> None:
    with st.container(border=True):
        through_date = st.date_input(
            "Post depreciation through",
            value=date.today(),
            key=f"asset_post_through_{context.profile_key}_{asset['id']}",
        )
        st.caption(
            "Posts each pending quarter through this date. No cash or bank balance changes."
        )
        posting_error = st.empty()
        if st.button(
            "Post due depreciation",
            type="primary",
            key=f"post_depreciation_{context.profile_key}_{asset['id']}",
        ):
            context.confirmed_write(
                "post_due_depreciation",
                {"asset_id": asset["id"], "through_date": through_date},
                lambda: context.storage.post_due_depreciation(
                    asset["id"],
                    through_date,
                    expected_asset=asset,
                ),
                "Due depreciation posted. Already posted quarters were skipped.",
                report_error=posting_error.error,
            )
    state_key = f"asset_schedule_visible_{context.profile_key}_{asset['id']}"
    if st.button(
        "Calculate quarterly schedule",
        type="primary",
        key=f"calculate_asset_schedule_{context.profile_key}_{asset['id']}",
    ):
        st.session_state[state_key] = True
    if not st.session_state.get(state_key):
        st.caption(
            "Calculation is manual. Select the button to build the current schedule."
        )
        return
    schedule = _schedule(asset)
    frame = pd.DataFrame(
        [
            {
                "Quarter": item.sequence,
                "Scheduled date": item.scheduled_date,
                "Depreciation": float(item.depreciation_amount),
                "Cumulative depreciation": float(item.cumulative_depreciation),
                "Remaining book value": float(item.remaining_book_value),
                "Override": "Yes" if item.is_override else "",
                "Override reason": item.override_reason,
                "Posting status": item.posting_status,
                "Ledger entry ID": item.journal_entry_id,
            }
            for item in schedule
        ]
    )
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Depreciation": st.column_config.NumberColumn(format="$%.2f"),
            "Cumulative depreciation": st.column_config.NumberColumn(format="$%.2f"),
            "Remaining book value": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    if asset["status"] == "retired":
        st.caption(
            "The schedule stops after the retirement date. No disposal gain, loss, "
            "recapture, or remaining-basis write-off is calculated."
        )

    if asset.get("posted_entry_ids"):
        st.info(
            "Posted depreciation history is read-only. Schedule overrides are locked."
        )
        return
    due = [item for item in schedule if item.scheduled_date <= date.today()]
    if not due:
        st.info(
            "No quarterly schedule period is due yet, so nothing can be overridden."
        )
        return
    with st.expander("Override a due or past quarter"):
        by_sequence = {item.sequence: item for item in due}
        sequence = st.selectbox(
            "Quarter to override",
            list(by_sequence),
            format_func=lambda value: (
                f"Quarter {value} · {by_sequence[value].scheduled_date.isoformat()}"
            ),
            key=f"asset_override_period_{context.profile_key}_{asset['id']}",
        )
        selected = by_sequence[sequence]
        amount = st.number_input(
            "Depreciation amount",
            min_value=0.0,
            value=float(selected.depreciation_amount),
            format="%.2f",
            key=f"asset_override_amount_{context.profile_key}_{asset['id']}_{sequence}",
        )
        reason = st.text_input(
            "Reason",
            value=selected.override_reason,
            key=f"asset_override_reason_{context.profile_key}_{asset['id']}_{sequence}",
        )
        override_error = st.empty()
        c1, c2 = st.columns(2)
        if c1.button(
            "Save override",
            type="primary",
            key=f"save_asset_override_{context.profile_key}_{asset['id']}",
        ):
            context.confirmed_write(
                "override_asset_period",
                {
                    "asset_id": asset["id"],
                    "sequence": sequence,
                    "amount": amount,
                    "reason": reason,
                },
                lambda: context.storage.override_asset_period(
                    asset["id"],
                    sequence,
                    amount,
                    reason,
                    as_of_date=date.today(),
                    expected_asset=asset,
                ),
                "Quarterly depreciation override saved; later quarters were rebalanced.",
                report_error=override_error.error,
            )
        if selected.is_override and c2.button(
            "Remove override",
            key=f"remove_asset_override_{context.profile_key}_{asset['id']}",
        ):
            context.confirmed_write(
                "remove_asset_period_override",
                {"asset_id": asset["id"], "sequence": sequence},
                lambda: context.storage.remove_asset_period_override(
                    asset["id"], sequence, expected_asset=asset
                ),
                "Quarterly depreciation override removed; the schedule was recalculated.",
                report_error=override_error.error,
            )


def render_assets(context: AssetsContext) -> None:
    """Render the asset register, schedule and explicit depreciation posting."""
    render_page_header(
        "Assets",
        "Track depreciable business assets and calculate quarterly straight-line schedules.",
    )
    try:
        context.storage.prefetch_worksheets("Assets", "Payees", "Tags", "Transactions")
        assets = context.storage.list_assets()
        payees = context.services.payees.list()
        tags = context.services.tags.list()
        transactions = context.storage.list_transactions()
        accounts = context.services.accounts.list(active_only=False)
        categories = context.storage.list_categories()
        depreciation_by_asset: dict[str, list[str]] = {}
        for transaction in transactions:
            if str(transaction.get("source_type") or "").strip().lower() == "depreciation":
                asset_id = str(transaction.get("source_id") or "").strip()
                if asset_id:
                    depreciation_by_asset.setdefault(asset_id, []).append(transaction["id"])
        for asset in assets:
            asset["posted_entry_ids"] = depreciation_by_asset.get(asset["id"], [])
    except StorageError as error:
        context.report_storage_error(error)
        render_global_footer()
        st.stop()

    with st.expander("Add asset", expanded=not assets):
        values = _asset_fields(
            "add_asset",
            profile_key=context.profile_key,
            payees=payees,
            tags=tags,
            transactions=transactions,
            accounts=accounts,
            categories=categories,
        )
        add_error = st.empty()
        if st.button("Add asset", type="primary", key="save_new_asset"):
            context.confirmed_write(
                "create_asset",
                values,
                lambda: context.storage.create_asset(**values),
                "Asset added.",
                report_error=add_error.error,
            )

    st.subheader("Asset register")
    if not assets:
        st.info("No assets yet. Add the first depreciable asset above.")
        return
    frame = _asset_frame(assets, today=date.today())
    asset_ids = frame["ID"].tolist()
    selected_asset_key = f"selected_asset_id_{context.profile_key}"
    selection_scope_key = f"asset_selection_scope_{context.profile_key}"
    selection_scope = (
        tuple(asset_ids),
        st.session_state.get("workbook_data_revision", 0),
    )
    if st.session_state.get(selection_scope_key) != selection_scope:
        st.session_state[selection_scope_key] = selection_scope
        st.session_state.pop(selected_asset_key, None)
        st.session_state["asset_table_generation"] = (
            st.session_state.get("asset_table_generation", 0) + 1
        )
    table_key = (
        f"asset_register_{context.profile_key}_"
        f"{st.session_state.get('asset_table_generation', 0)}"
    )

    def select_asset() -> None:
        selected_rows = st.session_state[table_key].selection.rows
        if selected_rows and 0 <= selected_rows[0] < len(asset_ids):
            st.session_state[selected_asset_key] = asset_ids[selected_rows[0]]

    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select=select_asset,
        selection_mode="single-row",
        key=table_key,
        column_config={
            "Cost basis": st.column_config.NumberColumn(format="$%.2f"),
            "Salvage value": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    asset_by_id = {asset["id"]: asset for asset in assets}
    selected_id = st.session_state.get(selected_asset_key)
    if selected_id not in asset_by_id:
        selected_id = assets[0]["id"]
        st.session_state[selected_asset_key] = selected_id
    selected = asset_by_id[selected_id]
    st.caption("Select an asset row to manage its record and quarterly schedule.")

    with st.expander("Edit or retire selected asset"):
        locked = bool(_overrides(selected) or selected.get("posted_entry_ids"))
        if locked:
            st.info(
                "Schedule terms are locked because this asset has a historical "
                "override or posted depreciation. Descriptive fields remain editable."
            )
        values = _asset_fields(
            f"edit_asset_{selected_id}",
            profile_key=context.profile_key,
            payees=payees,
            tags=tags,
            transactions=transactions,
            accounts=accounts,
            categories=categories,
            initial=selected,
            schedule_locked=locked,
        )
        edit_error = st.empty()
        if st.button(
            "Save asset changes",
            type="primary",
            key=f"save_asset_{selected_id}",
        ):
            context.confirmed_write(
                "edit_asset",
                {"asset_id": selected_id, **values},
                lambda: context.storage.edit_asset(
                    selected_id, expected_asset=selected, **values
                ),
                "Asset updated.",
                report_error=edit_error.error,
            )
        if selected["status"] == "active":
            retired_date = st.date_input(
                "Retirement date",
                value=date.today(),
                key=f"retire_asset_date_{selected_id}",
            )
            if st.button("Retire asset", key=f"retire_asset_{selected_id}"):
                context.confirmed_write(
                    "retire_asset",
                    {"asset_id": selected_id, "retired_date": retired_date},
                    lambda: context.storage.retire_asset(
                        selected_id,
                        retired_date,
                        expected_asset=selected,
                    ),
                    "Asset retired; future quarterly depreciation was stopped.",
                    report_error=edit_error.error,
                )
        if locked:
            st.info("Assets with saved depreciation history cannot be deleted.")
        else:
            st.warning("Permanent deletion removes this asset record.")
            confirm_delete = st.checkbox(
                "I understand this asset will be permanently deleted",
                key=f"confirm_delete_asset_{selected_id}",
            )
            with st.container(key="destructive_asset_delete"):
                if st.button(
                    "Permanently delete asset",
                    icon=":material/delete_forever:",
                    key=f"delete_asset_{selected_id}",
                ):
                    if not confirm_delete:
                        edit_error.error("Confirm permanent deletion. No data changed.")
                    else:
                        context.confirmed_write(
                            "delete_asset",
                            {"asset_id": selected_id},
                            lambda: context.storage.delete_asset(
                                selected_id, expected_asset=selected
                            ),
                            "Asset deleted.",
                            report_error=edit_error.error,
                        )

    st.subheader(f"Quarterly depreciation schedule · {selected['name']}")
    _show_source_context(
        next(
            (
                transaction
                for transaction in transactions
                if transaction["id"] == selected.get("source_transaction_id")
            ),
            None,
        ),
        selected.get("source_transaction_id", ""),
    )
    _render_schedule(context, selected)


__all__ = ["AssetsContext", "render_assets"]
