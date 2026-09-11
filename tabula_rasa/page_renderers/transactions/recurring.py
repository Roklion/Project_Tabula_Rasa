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
    if not schedules:
        st.info("No recurring expense schedules yet. Create one from an Expense or mixed-use entry.")
        return
    rows = []
    for item in schedules:
        rows.append({
            "Name": item["name"],
            "Type": "Mixed-use" if item.get("expense_type") == "mixed_use" else "Expense",
            "Cadence": f"Every {item['recurrence_interval']} {item['recurrence_unit']}",
            "Next due": item.get("next_due_date") or "—",
            "Status": item["status"].title(),
            "Schedule ID": item["id"],
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)
    choices = {f"{item['name']} · {item['id']}": item for item in schedules}
    selected_label = st.selectbox("Schedule", list(choices), key=f"recurring_selected_{context.profile_key}")
    selected = choices[selected_label]
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
