"""Profile-local Payees and Tags management workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from tabula_rasa.storage import GoogleSheetsStorage, StorageError


@dataclass(frozen=True)
class PayeesTagsContext:
    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]


def _name_map(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {str(record["id"]): record for record in records}


def _payee_reference_counts(
    transactions: list[dict[str, str]], mixed_sources: list[dict[str, str]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in (*transactions, *mixed_sources):
        payee_id = str(record.get("payee_id") or "").strip()
        if payee_id:
            counts[payee_id] = counts.get(payee_id, 0) + 1
    return counts


def _tag_reference_counts(
    transactions: list[dict[str, Any]], mileage: list[dict[str, Any]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in (*transactions, *mileage):
        for tag_id in record.get("tag_ids", []):
            counts[tag_id] = counts.get(tag_id, 0) + 1
    return counts


def _write(
    context: PayeesTagsContext,
    action: str,
    payload: dict[str, Any],
    operation: Callable[[], object],
    success: str,
    error: Any,
) -> None:
    context.confirmed_write(
        action,
        payload,
        operation,
        success,
        report_error=error.error,
    )


def _render_payees(
    context: PayeesTagsContext,
    payees: list[dict[str, str]],
    transactions: list[dict[str, str]],
    mixed_sources: list[dict[str, str]],
) -> None:
    counts = _payee_reference_counts(transactions, mixed_sources)
    st.subheader("Payees")
    st.caption(
        "Payees are stored only in the selected business profile. Renaming keeps "
        "the stable ID and all references."
    )
    frame = pd.DataFrame(
        [
            {"Payee": item["name"], "Active": item["active"], "References": counts.get(item["id"], 0)}
            for item in payees
        ],
        columns=["Payee", "Active", "References"],
    )
    if frame.empty:
        st.info("No payees yet. Add one below.")
    else:
        st.dataframe(frame, hide_index=True, width="stretch")

    with st.expander("Add payee", expanded=True):
        add_name = st.text_input("New payee name", key=f"managed_new_payee_{context.profile_key}")
        add_error = st.empty()
        if st.button("Add payee", type="primary", key=f"managed_add_payee_{context.profile_key}"):
            _write(context, "create_payee", {"name": add_name}, lambda: context.storage.create_payee(add_name), "Payee added.", add_error)

    if not payees:
        return
    by_id = _name_map(payees)
    ids = list(by_id)

    def labels(value: str) -> str:
        return by_id[value]["name"]
    with st.expander("Rename payee"):
        rename_id = st.selectbox("Payee to rename", ids, format_func=labels, key=f"managed_rename_payee_id_{context.profile_key}")
        rename_name = st.text_input("Renamed payee name", value=by_id[rename_id]["name"], key=f"managed_rename_payee_name_{context.profile_key}_{rename_id}")
        rename_error = st.empty()
        if st.button("Rename payee", type="primary", key=f"managed_rename_payee_{context.profile_key}"):
            _write(context, "edit_payee", {"id": rename_id, "name": rename_name}, lambda: context.storage.edit_payee(rename_id, name=rename_name, expected_payee=by_id[rename_id]), "Payee renamed.", rename_error)

    with st.expander("Merge payees"):
        target_id = st.selectbox("Target payee", ids, format_func=labels, key=f"managed_merge_payee_target_{context.profile_key}")
        source_ids = st.multiselect("Source payees", [item for item in ids if item != target_id], format_func=labels, key=f"managed_merge_payee_sources_{context.profile_key}")
        st.warning("Merging rewrites every transaction and mixed-use source reference, then permanently removes the selected source payees.")
        acknowledgment_key = (
            f"managed_merge_payee_ack_{context.profile_key}_{target_id}_"
            f"{'_'.join(sorted(source_ids))}"
        )
        acknowledged = st.checkbox(
            "I understand the selected source payees will be permanently removed",
            key=acknowledgment_key,
        )
        merge_error = st.empty()
        if st.button("Merge payees", type="primary", key=f"managed_merge_payees_{context.profile_key}"):
            if not source_ids:
                merge_error.error("Select one or more source payees.")
            elif not acknowledged:
                merge_error.error("Acknowledge the permanent source removal before merging. No data changed.")
            else:
                _write(context, "merge_payees", {"target_id": target_id, "source_ids": source_ids}, lambda: context.storage.merge_payees(target_id, source_ids, expected_payees=payees), "Payees merged.", merge_error)

    with st.expander("Remove payee"):
        remove_id = st.selectbox("Payee to remove", ids, format_func=labels, key=f"managed_remove_payee_id_{context.profile_key}")
        remove_name = by_id[remove_id]["name"]
        is_referenced = bool(counts.get(remove_id, 0))
        if is_referenced:
            st.info(f"This payee has {counts[remove_id]} references. Unassign it from those records or merge it before removal.")
        st.warning(f"Permanently removing payee {remove_name!r} cannot be undone and is available only when it is unreferenced.")
        remove_ack = st.checkbox(
            f"I understand payee {remove_name!r} will be permanently removed and cannot be restored",
            key=f"managed_remove_payee_ack_{context.profile_key}_{remove_id}",
            disabled=is_referenced,
        )
        remove_error = st.empty()
        with st.container(key="destructive_managed_payee_remove"):
            if st.button("Permanently remove payee", icon=":material/delete_forever:", key=f"managed_remove_payee_{context.profile_key}", disabled=is_referenced):
                if not remove_ack:
                    remove_error.error("Acknowledge permanent removal before continuing. No data changed.")
                else:
                    _write(context, "remove_payee", {"id": remove_id}, lambda: context.storage.remove_payee(remove_id, expected_payee=by_id[remove_id]), "Payee removed.", remove_error)


def _render_tags(
    context: PayeesTagsContext,
    tags: list[dict[str, str]],
    transactions: list[dict[str, Any]],
    mileage: list[dict[str, Any]],
) -> None:
    counts = _tag_reference_counts(transactions, mileage)
    st.subheader("Tags")
    st.caption(
        "Tags are profile-local labels shared by Transactions and Mileage. "
        "Renaming keeps the stable ID and existing associations."
    )
    frame = pd.DataFrame(
        [{"Tag": item["name"], "Active": item["active"], "References": counts.get(item["id"], 0)} for item in tags],
        columns=["Tag", "Active", "References"],
    )
    if frame.empty:
        st.info("No tags yet. Add one below.")
    else:
        st.dataframe(frame, hide_index=True, width="stretch")

    with st.expander("Add tag", expanded=True):
        add_name = st.text_input("New tag name", key=f"managed_new_tag_{context.profile_key}")
        add_error = st.empty()
        if st.button("Add tag", type="primary", key=f"managed_add_tag_{context.profile_key}"):
            _write(context, "create_tag", {"name": add_name}, lambda: context.storage.create_tag(add_name), "Tag added.", add_error)

    if not tags:
        return
    by_id = _name_map(tags)
    ids = list(by_id)

    def labels(value: str) -> str:
        return by_id[value]["name"]
    with st.expander("Rename tag"):
        rename_id = st.selectbox("Tag to rename", ids, format_func=labels, key=f"managed_rename_tag_id_{context.profile_key}")
        rename_name = st.text_input("Renamed tag name", value=by_id[rename_id]["name"], key=f"managed_rename_tag_name_{context.profile_key}_{rename_id}")
        rename_error = st.empty()
        if st.button("Rename tag", type="primary", key=f"managed_rename_tag_{context.profile_key}"):
            _write(context, "edit_tag", {"id": rename_id, "name": rename_name}, lambda: context.storage.edit_tag(rename_id, name=rename_name, expected_tag=by_id[rename_id]), "Tag renamed.", rename_error)

    with st.expander("Merge tags"):
        target_id = st.selectbox("Target tag", ids, format_func=labels, key=f"managed_merge_tag_target_{context.profile_key}")
        source_ids = st.multiselect("Source tags", [item for item in ids if item != target_id], format_func=labels, key=f"managed_merge_tag_sources_{context.profile_key}")
        st.warning("Merging rewrites Transactions and Mileage associations, de-duplicates the target association, then permanently removes the selected source tags.")
        acknowledgment_key = (
            f"managed_merge_tag_ack_{context.profile_key}_{target_id}_"
            f"{'_'.join(sorted(source_ids))}"
        )
        acknowledged = st.checkbox(
            "I understand the selected source tags will be permanently removed",
            key=acknowledgment_key,
        )
        merge_error = st.empty()
        if st.button("Merge tags", type="primary", key=f"managed_merge_tags_{context.profile_key}"):
            if not source_ids:
                merge_error.error("Select one or more source tags.")
            elif not acknowledged:
                merge_error.error("Acknowledge the permanent source removal before merging. No data changed.")
            else:
                _write(context, "merge_tags", {"target_id": target_id, "source_ids": source_ids}, lambda: context.storage.merge_tags(target_id, source_ids, expected_tags=tags), "Tags merged.", merge_error)

    with st.expander("Remove tag"):
        remove_id = st.selectbox("Tag to remove", ids, format_func=labels, key=f"managed_remove_tag_id_{context.profile_key}")
        remove_name = by_id[remove_id]["name"]
        is_referenced = bool(counts.get(remove_id, 0))
        if is_referenced:
            st.info(f"This tag has {counts[remove_id]} references. Unassign it from those records or merge it before removal.")
        st.warning(f"Permanently removing tag {remove_name!r} cannot be undone and is available only when it is unreferenced.")
        remove_ack = st.checkbox(
            f"I understand tag {remove_name!r} will be permanently removed and cannot be restored",
            key=f"managed_remove_tag_ack_{context.profile_key}_{remove_id}",
            disabled=is_referenced,
        )
        remove_error = st.empty()
        with st.container(key="destructive_managed_tag_remove"):
            if st.button("Permanently remove tag", icon=":material/delete_forever:", key=f"managed_remove_tag_{context.profile_key}", disabled=is_referenced):
                if not remove_ack:
                    remove_error.error("Acknowledge permanent removal before continuing. No data changed.")
                else:
                    _write(context, "remove_tag", {"id": remove_id}, lambda: context.storage.remove_tag(remove_id, expected_tag=by_id[remove_id]), "Tag removed.", remove_error)


def render_payees_tags(context: PayeesTagsContext) -> None:
    """Render separate Payees and Tags management sections for one profile."""
    st.caption(f"Business profile: {context.profile_key} (all values below are profile-local)")
    try:
        payees = context.storage.list_payees(active_only=False)
        tags = context.storage.list_tags(active_only=False)
        transactions = context.storage.list_transactions()
        mixed_sources = context.storage.list_mixed_use_expense_sources()
        mileage = context.storage.list_mileage_trips()
    except StorageError as error:
        context.report_storage_error(error)
        return
    payees_tab, tags_tab = st.tabs(["Payees", "Tags"])
    with payees_tab:
        _render_payees(context, payees, transactions, mixed_sources)
    with tags_tab:
        _render_tags(context, tags, transactions, mileage)
