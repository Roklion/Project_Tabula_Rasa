"""Recurring expense management surface."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import streamlit as st


def render_recurring_expenses(context: Any, *, accounts, categories, payees, tags) -> None:
    """Render profile-scoped schedule management and bounded controls."""
    st.subheader("Recurring expenses")
    st.caption("Schedules create Expense occurrences through the active Google Sheets ledger.")
    try:
        schedules = context.storage.list_recurring_schedules(_force_refresh=True)
    except Exception as error:
        context.report_storage_error(error)
        return
    if not schedules:
        return
    current_transactions = context.storage.list_transactions(_force_refresh=True)
    current_sources = context.storage.list_mixed_use_expenses(_force_refresh=True)
    rows = []
    for item in schedules:
        linked = current_sources if item.get("source_kind") == "mixed_use" else current_transactions
        current_dates = [str(row.get("txn_date") or "") for row in linked if row.get("recurring_schedule_id") == item["id"]]
        rows.append({
            "Name": item["name"],
            "Type": "Mixed-use" if item.get("source_kind") == "mixed_use" else "Expense",
            "Description": item.get("description", ""),
            "Amount / allocated": item.get("amount", ""),
            "Cadence": f"Every {item['recurrence_interval']} {item['recurrence_unit']}",
            "Start": item.get("start_date", ""),
            "End": item.get("end_date", "") or "—",
            "Latest current": max(current_dates) if current_dates else "—",
            "Next due": item.get("next_due_date") or "—",
            "Status": item["status"].title(),
            "Attention": (
                f"{item.get('attention_message', '')} ({item.get('attention_at', '')})"
                if item.get("attention_message") else "—"
            ),
            "Schedule ID": item["id"],
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)
    choices = {f"{item['name']} · {item['id']}": item for item in schedules}
    selected_label = st.selectbox("Schedule", list(choices), key=f"recurring_selected_{context.profile_key}")
    selected = choices[selected_label]
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
            edit_interval = st.number_input("Interval", min_value=1, value=int(selected["recurrence_interval"]), step=1)
            edit_start = st.date_input("Start date", value=date.fromisoformat(selected["start_date"]))
            edit_end = st.date_input("End date", value=date.fromisoformat(selected["end_date"]) if selected.get("end_date") else None)
            if selected.get("source_kind") == "mixed_use":
                edit_amount = st.text_input("Total expense", value=selected.get("total_expense", ""))
                edit_percentage = st.text_input("Business use %", value=selected.get("business_use_percentage", ""))
                edit_rationale = st.text_input("Allocation rationale", value=selected.get("allocation_rationale", ""))
            else:
                edit_amount = st.text_input("Amount", value=selected.get("amount", ""))
                edit_percentage = edit_rationale = None
            account_options = [item for item in accounts if str(item.get("active", "")).upper() == "TRUE" or str(item.get("id")) == selected.get("account_id")]
            account_ids = [str(item["id"]) for item in account_options]
            edit_account = st.selectbox("Account", account_ids, index=account_ids.index(selected["account_id"]) if selected.get("account_id") in account_ids else 0, format_func=lambda value: next((str(item.get("name")) for item in account_options if str(item.get("id")) == value), value))
            category_options = [item for item in categories if item.get("kind") == "Expense"]
            category_ids = [str(item["id"]) for item in category_options]
            edit_category = st.selectbox("Category", category_ids, index=category_ids.index(selected["category_id"]) if selected.get("category_id") in category_ids else 0, format_func=lambda value: next((str(item.get("name")) for item in category_options if str(item.get("id")) == value), value))
            payee_ids = [""] + [str(item["id"]) for item in payees]
            edit_payee = st.selectbox("Payee", payee_ids, index=payee_ids.index(selected.get("payee_id", "")) if selected.get("payee_id", "") in payee_ids else 0, format_func=lambda value: next((str(item.get("name")) for item in payees if str(item.get("id")) == value), "No payee" if not value else value))
            try:
                selected_tags = json.loads(selected.get("tag_ids", "[]"))
            except (TypeError, json.JSONDecodeError):
                selected_tags = []
            edit_tags = st.multiselect("Tags", [str(item["id"]) for item in tags], default=[tag for tag in selected_tags if tag in {str(item["id"]) for item in tags}], format_func=lambda value: next((str(item.get("name")) for item in tags if str(item.get("id")) == value), value))
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
                st.success("Schedule template updated; existing occurrences were unchanged.")
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    left, right = st.columns(2)
    with left:
        if selected["status"] == "active" and st.button("Pause", key=f"recurring_pause_{selected['id']}"):
            try:
                context.storage.pause_recurring_schedule(selected["id"], expected_schedule=selected)
                context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
        elif selected["status"] == "paused" and st.button("Resume", key=f"recurring_resume_{selected['id']}"):
            try:
                context.storage.resume_recurring_schedule(selected["id"], expected_schedule=selected)
                context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    with right:
        if selected["status"] != "ended" and st.button("End schedule", key=f"recurring_end_{selected['id']}"):
            try:
                context.storage.end_recurring_schedule(selected["id"], expected_schedule=selected)
                context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    if st.button("Generate due occurrences", key=f"recurring_reconcile_{context.profile_key}"):
        try:
            result = context.storage.reconcile_recurring_schedules(as_of=date.today())
            if result["attention"]:
                st.warning("Some schedules need attention; other schedules were processed.")
            else:
                st.success(f"Generated {len(result['generated'])} occurrence(s).")
            context.mark_workbook_data_changed and context.mark_workbook_data_changed()
        except Exception as error:
            context.report_storage_error(error)


__all__ = ["render_recurring_expenses"]
