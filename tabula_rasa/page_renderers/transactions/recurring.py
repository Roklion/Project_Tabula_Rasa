"""Recurring expense management surface."""

from __future__ import annotations

from datetime import date
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
    with st.expander("Create recurring expense", expanded=not schedules):
        active_accounts = [item for item in accounts if item.get("active")]
        expense_categories = [item for item in categories if item.get("kind") == "Expense"]
        if not active_accounts or not expense_categories:
            st.warning("Create an active account and an Expense category before adding a schedule.")
        else:
            with st.form(f"recurring_create_{context.profile_key}"):
                expense_type = st.segmented_control("Schedule type", ["Expense", "Mixed-use"], default="Expense")
                name = st.text_input("Schedule name")
                start = st.date_input("First occurrence", date.today())
                unit = st.selectbox("Cadence", ["day", "week", "month", "year"])
                interval = st.number_input("Every", min_value=1, value=1, step=1)
                amount = st.number_input("Amount", min_value=0.01, value=1.0, step=0.01, format="%.2f")
                percentage = st.number_input("Business use %", min_value=0.01, max_value=100.0, value=50.0, step=0.01, format="%.2f")
                rationale = st.text_input("Allocation rationale")
                account = st.selectbox("Account", active_accounts, format_func=lambda item: item["name"])
                category = st.selectbox("Category", expense_categories, format_func=lambda item: item["name"])
                description = st.text_input("Description")
                submitted = st.form_submit_button("Create schedule")
            if submitted:
                payload = {
                    "name": name,
                    "txn_date": start,
                    "recurrence_unit": unit,
                    "recurrence_interval": interval,
                    "account_id": account["id"],
                    "category_id": category["id"],
                    "description": description,
                }
                try:
                    if expense_type == "Mixed-use":
                        payload.update({
                            "total_expense": amount,
                            "business_use_percentage": percentage,
                            "allocation_rationale": rationale,
                        })
                        context.storage.create_recurring_mixed_use_expense(**payload)
                    else:
                        payload["amount"] = amount
                        context.storage.create_recurring_expense(**payload)
                    context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                    st.success("Recurring schedule created.")
                    st.rerun()
                except Exception as error:
                    context.report_storage_error(error)
    if not schedules:
        return
    current_transactions = context.storage.list_transactions(_force_refresh=True)
    current_sources = context.storage.list_mixed_use_expenses(_force_refresh=True)
    rows = []
    for item in schedules:
        linked = current_sources if item.get("expense_type") == "mixed_use" else current_transactions
        current_dates = [str(row.get("txn_date") or "") for row in linked if row.get("recurring_schedule_id") == item["id"]]
        rows.append({
            "Name": item["name"],
            "Type": "Mixed-use" if item.get("expense_type") == "mixed_use" else "Expense",
            "Description": item.get("description", ""),
            "Amount / allocated": item.get("amount", "") if item.get("expense_type") != "mixed_use" else item.get("total_expense", ""),
            "Cadence": f"Every {item['recurrence_interval']} {item['recurrence_unit']}",
            "Start": item.get("start_date", ""),
            "End": item.get("end_date", "") or "—",
            "Latest current": max(current_dates) if current_dates else "—",
            "Next due": item.get("next_due_date") or "—",
            "Status": item["status"].title(),
            "Attention": item.get("attention_code", "") or "—",
            "Schedule ID": item["id"],
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)
    choices = {f"{item['name']} · {item['id']}": item for item in schedules}
    selected_label = st.selectbox("Schedule", list(choices), key=f"recurring_selected_{context.profile_key}")
    selected = choices[selected_label]
    with st.expander("Edit schedule template"):
        with st.form(f"recurring_edit_{context.profile_key}_{selected['id']}"):
            edit_name = st.text_input("Schedule name", value=selected["name"])
            edit_unit = st.selectbox("Repeat every", ["day", "week", "month", "year"], index=["day", "week", "month", "year"].index(selected["recurrence_unit"]))
            edit_interval = st.number_input("Interval", min_value=1, value=int(selected["recurrence_interval"]), step=1)
            edit_start = st.date_input("Start date", value=date.fromisoformat(selected["start_date"]))
            edit_end = st.date_input("End date", value=date.fromisoformat(selected["end_date"]) if selected.get("end_date") else None)
            edit_amount = st.text_input("Amount", value=selected.get("amount", ""))
            edit_description = st.text_input("Description", value=selected.get("description", ""))
            edit_reference = st.text_input("Reference", value=selected.get("reference", ""))
            save_template = st.form_submit_button("Save schedule template")
        if save_template:
            try:
                context.storage.edit_recurring_schedule(
                    selected["id"], expected_schedule=selected, name=edit_name,
                    recurrence_unit=edit_unit, recurrence_interval=edit_interval,
                    start_date=edit_start, anchor_date=edit_start, end_date=edit_end,
                    amount=edit_amount, description=edit_description, reference=edit_reference,
                )
                st.success("Schedule template updated; existing occurrences were unchanged.")
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    left, right = st.columns(2)
    with left:
        if selected["status"] == "active" and st.button("Pause", key=f"recurring_pause_{selected['id']}"):
            try:
                context.storage.pause_recurring_schedule(selected["id"])
                context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
        elif selected["status"] == "paused" and st.button("Resume", key=f"recurring_resume_{selected['id']}"):
            try:
                context.storage.resume_recurring_schedule(selected["id"])
                context.mark_workbook_data_changed and context.mark_workbook_data_changed()
                st.rerun()
            except Exception as error:
                context.report_storage_error(error)
    with right:
        if selected["status"] != "ended" and st.button("End schedule", key=f"recurring_end_{selected['id']}"):
            try:
                context.storage.end_recurring_schedule(selected["id"])
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
