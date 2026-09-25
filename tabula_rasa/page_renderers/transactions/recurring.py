"""Recurring expense management surface."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import streamlit as st
from tabula_rasa.hierarchy import ordered_accounts, ordered_categories
from .metadata_fields import active_or_selected as _active_or_selected, render_metadata_reference
from tabula_rasa.recurrence_state import clear_edit_pending_state_for_schedule
from .table_selection import clear_selected_table_record, selected_table_record


def _mark_workbook_data_changed(context: Any) -> None:
    callback = getattr(context, "mark_workbook_data_changed", None)
    if callable(callback):
        callback()


def _clear_pending_schedule_state(
    state: Any, profile_key: str, schedule_id: str
) -> None:
    """Forget retry IDs that refer to a schedule the user just ended."""
    schedule_id = str(schedule_id or "")
    if not schedule_id:
        return
    clear_edit_pending_state_for_schedule(
        state,
        profile_key=profile_key,
        schedule_id=schedule_id,
    )

    for root in ("recurring_pending", "mixed_use_pending"):
        schedule_key = f"{root}_schedule_id_{profile_key}"
        if str(state.get(schedule_key) or "") != schedule_id:
            continue
        for suffix in (
            "schedule_id",
            "transaction_id",
            "source_id",
            "payload",
            "configuration_revision",
        ):
            state.pop(f"{root}_{suffix}_{profile_key}", None)


def _safe_date(value: Any, fallback: date | None = None) -> date | None:
    """Return a form-safe date while leaving corrupted schedule data visible."""
    if not value:
        return fallback
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback


def _safe_interval(value: Any) -> int:
    """Return a valid editor interval without hiding the stored invalid value."""
    try:
        interval = int(str(value))
    except (TypeError, ValueError):
        return 1
    return interval if interval > 0 else 1


def _recurring_category_options(categories, selected_category: str) -> list[dict[str, Any]]:
    ordered_category_items = ordered_categories(categories)
    return [
        item for item in ordered_category_items
        if (
            item.get("kind") == "Expense"
            and (
                "active" not in item
                or str(item.get("active", "")).upper() == "TRUE"
            )
        )
        or str(item.get("id")) == selected_category
    ]


def _recurring_payee_options(
    payees: list[dict[str, Any]], selected_payee: str
) -> list[dict[str, Any]]:
    """Keep a missing schedule payee visible and selectable for repair."""
    available = _active_or_selected(payees, [selected_payee])
    if selected_payee and selected_payee not in {
        str(item.get("id")) for item in available
    }:
        available.append(
            {"id": selected_payee, "name": f"Missing ({selected_payee})"}
        )
    return available


def _selected_tag_ids(value: Any) -> list[Any]:
    try:
        selected_tags = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return selected_tags if isinstance(selected_tags, list) else []


def _render_generate_due(context: Any, notice_key: str) -> None:
    if st.button("Generate due occurrences", key=f"recurring_reconcile_{context.profile_key}"):
        try:
            result = context.storage.reconcile_recurring_schedules(as_of=date.today())
            if result["attention"]:
                st.session_state[notice_key] = {
                    "level": "warning",
                    "message": "Some schedules need attention; other schedules were processed.",
                }
            else:
                st.session_state[notice_key] = {
                    "level": "success",
                    "message": f"Generated {len(result['generated'])} occurrence(s).",
                }
            _mark_workbook_data_changed(context)
            st.rerun()
        except Exception as error:
            context.report_storage_error(error)


def render_recurring_expenses(context: Any, *, accounts, categories, payees, tags) -> None:
    """Render profile-scoped schedule management and bounded controls."""
    st.subheader("Recurring expenses")
    st.caption("Schedules create Expense occurrences through the active Google Sheets ledger.")
    notice_key = f"recurring_notice_{context.profile_key}"
    if notice := st.session_state.pop(notice_key, None):
        if notice["level"] == "warning":
            st.warning(notice["message"])
        else:
            st.success(notice["message"])
    try:
        schedules = context.storage.list_recurring_schedules()
    except Exception as error:
        context.report_storage_error(error)
        return
    if not schedules:
        clear_selected_table_record(
            profile_key=context.profile_key,
            surface="recurring_schedule",
            clear_on_change=(f"recurring_edit_target_{context.profile_key}",),
        )
        st.info(
            "No recurring expense schedules found. Check 'Repeat this Expense' "
            "when adding a transaction to create one."
        )
        return
    rows = []
    for item in schedules:
        rows.append({
            "Name": item["name"],
            "Type": "Mixed-use" if item.get("source_kind") == "mixed_use" else "Expense",
            "Description": item.get("description", ""),
            "Amount / allocated": item.get("amount", ""),
            "Cadence": f"Every {item['recurrence_interval']} {item['recurrence_unit']}",
            "Start": item.get("start_date", ""),
            "End": item.get("end_date", "") or "—",
            "Latest current": item.get("latest_current_occurrence_date") or "—",
            "Next due": item.get("next_due_date") or "—",
            "Status": item["status"].title(),
            "Attention": (
                f"{item.get('attention_message', '')} ({item.get('attention_at', '')})"
                if item.get("attention_message") else "—"
            ),
            "Schedule ID": item["id"],
        })
    st.caption("Select one schedule row, then choose Edit to change its template.")
    edit_target_key = f"recurring_edit_target_{context.profile_key}"
    selected_id = selected_table_record(
        rows,
        [str(item["id"]) for item in schedules],
        profile_key=context.profile_key,
        surface="recurring_schedule",
        records=schedules,
        clear_on_change=(edit_target_key,),
    )
    if not selected_id:
        _render_generate_due(context, notice_key)
        return
    selected = next(item for item in schedules if str(item["id"]) == selected_id)
    st.caption(f"Selected schedule: {selected['name']}")
    if selected.get("status") not in {"active", "paused", "ended"}:
        st.warning("This schedule has an invalid status. Choose a valid status to repair it.")
        repair_status = st.selectbox(
            "Repair status", ["active", "paused", "ended"],
            key=f"recurring_repair_status_{context.profile_key}_{selected['id']}",
        )
        if st.button("Repair schedule status", key=f"recurring_repair_status_button_{selected['id']}"):
            try:
                context.storage.edit_recurring_schedule(
                    selected["id"], expected_schedule=selected, status=repair_status,
                )
                _mark_workbook_data_changed(context)
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
        return
    if st.button("Edit", key=f"recurring_edit_action_{context.profile_key}"):
        st.session_state[edit_target_key] = selected_id
    left, right = st.columns(2)
    with left:
        if selected["status"] == "active" and st.button("Pause", key=f"recurring_pause_{selected['id']}"):
            try:
                context.storage.pause_recurring_schedule(selected["id"], expected_schedule=selected)
                _mark_workbook_data_changed(context)
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
        elif selected["status"] == "paused" and st.button("Resume", key=f"recurring_resume_{selected['id']}"):
            try:
                context.storage.resume_recurring_schedule(selected["id"], expected_schedule=selected)
                _mark_workbook_data_changed(context)
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    with right:
        if selected["status"] != "ended" and st.button("End schedule", key=f"recurring_end_{selected['id']}"):
            try:
                context.storage.end_recurring_schedule(selected["id"], expected_schedule=selected)
                _clear_pending_schedule_state(
                    st.session_state, context.profile_key, selected["id"]
                )
                _mark_workbook_data_changed(context)
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    _render_generate_due(context, notice_key)
    if st.session_state.get(edit_target_key) != selected_id:
        return
    with st.expander("Edit schedule template"):
        with st.form(f"recurring_edit_{context.profile_key}_{selected['id']}"):
            edit_name = st.text_input("Schedule name", value=selected["name"])
            recurrence_units = ["day", "week", "month", "year"]
            selected_unit = selected.get("recurrence_unit")
            edit_unit = st.selectbox(
                "Repeat every",
                recurrence_units,
                index=recurrence_units.index(selected_unit)
                if selected_unit in recurrence_units
                else 0,
            )
            edit_interval = st.number_input(
                "Interval", min_value=1, value=_safe_interval(selected.get("recurrence_interval")), step=1
            )
            edit_start = st.date_input(
                "Start date", value=_safe_date(selected.get("start_date"), date.today())
            )
            edit_end = st.date_input(
                "End date", value=_safe_date(selected.get("end_date"))
            )
            if selected.get("source_kind") == "mixed_use":
                edit_amount = st.text_input("Total expense", value=selected.get("total_expense", ""))
                edit_percentage = st.text_input("Business use %", value=selected.get("business_use_percentage", ""))
                edit_rationale = st.text_input("Allocation rationale", value=selected.get("allocation_rationale", ""))
            else:
                edit_amount = st.text_input("Amount", value=selected.get("amount", ""))
                edit_percentage = edit_rationale = None
            selected_account = str(selected.get("account_id", ""))
            account_options = _active_or_selected(ordered_accounts(accounts), [selected_account])
            if selected_account and selected_account not in {
                str(item.get("id")) for item in account_options
            }:
                account_options.append({"id": selected_account, "name": f"Missing ({selected_account})"})
            account_ids = [str(item["id"]) for item in account_options]
            account_names = {str(item["id"]): str(item.get("name", "")) for item in account_options}
            edit_account = render_metadata_reference(
                "Account", account_ids, account_names, current_id=selected_account,
            )
            selected_category = str(selected.get("category_id", ""))
            category_options = _recurring_category_options(categories, selected_category)
            if selected_category and selected_category not in {
                str(item.get("id")) for item in category_options
            }:
                category_options.append({"id": selected_category, "name": f"Missing ({selected_category})", "kind": "Expense"})
            category_ids = [str(item["id"]) for item in category_options]
            category_names = {str(item["id"]): str(item.get("name", "")) for item in category_options}
            edit_category = render_metadata_reference(
                "Category", category_ids, category_names, current_id=selected_category,
            )
            selected_payee = str(selected.get("payee_id", ""))
            available_payees = _recurring_payee_options(payees, selected_payee)
            payee_ids = [""] + [str(item["id"]) for item in available_payees]
            payee_names = {str(item["id"]): str(item.get("name", "")) for item in available_payees}
            edit_payee = st.selectbox(
                "Payee", payee_ids,
                index=payee_ids.index(selected_payee) if selected_payee in payee_ids else 0,
                format_func=lambda value: payee_names.get(
                    value, "No payee" if not value else f"Missing ({value})"
                ),
            )
            selected_tags = _selected_tag_ids(selected.get("tag_ids", "[]"))
            available_tags = _active_or_selected(tags, selected_tags)
            tag_ids = [str(item["id"]) for item in available_tags]
            tag_id_set = set(tag_ids)
            tag_names = {str(item["id"]): str(item.get("name", "")) for item in available_tags}
            edit_tags = st.multiselect(
                "Tags",
                tag_ids,
                default=[tag for tag in selected_tags if tag in tag_id_set],
                format_func=lambda value: tag_names.get(value, value),
            )
            edit_description = st.text_input("Description", value=selected.get("description", ""))
            edit_reference = st.text_input("Reference", value=selected.get("reference", ""))
            save_template = st.form_submit_button("Save schedule template")
        if save_template:
            try:
                context.storage.edit_recurring_schedule(
                    selected["id"], expected_schedule=selected, name=edit_name,
                    recurrence_unit=edit_unit, recurrence_interval=edit_interval,
                    start_date=edit_start, anchor_date=edit_start, end_date=edit_end,
                    amount=edit_amount if selected.get("source_kind") != "mixed_use" else selected.get("amount", ""),
                    account_id=edit_account, category_id=edit_category, payee_id=edit_payee, tag_ids=edit_tags,
                    total_expense=edit_amount if selected.get("source_kind") == "mixed_use" else selected.get("total_expense", ""),
                    business_use_percentage=edit_percentage if selected.get("source_kind") == "mixed_use" else selected.get("business_use_percentage", ""),
                    allocation_rationale=edit_rationale if selected.get("source_kind") == "mixed_use" else selected.get("allocation_rationale", ""),
                    description=edit_description, reference=edit_reference,
                )
                _mark_workbook_data_changed(context)
                st.session_state[notice_key] = {
                    "level": "success",
                    "message": "Schedule template updated; existing occurrences were unchanged.",
                }
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
__all__ = ["render_recurring_expenses"]
