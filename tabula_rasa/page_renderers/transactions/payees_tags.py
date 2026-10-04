"""Profile-local Payees and Tags management workflows."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.reference_data import normalize_tag_ids as _normalize_tag_ids
from tabula_rasa.errors import StorageError
from .table_selection import clear_selected_table_record, selected_table_record


@dataclass(frozen=True)
class PayeesTagsContext:
    profile_key: str
    services: ApplicationServices
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]


def _name_map(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {str(record["id"]): record for record in records}


def _payee_reference_counts(
    transactions: list[dict[str, str]],
    mixed_sources: list[dict[str, str]],
    schedules: list[dict[str, str]],
    journals: list[dict[str, Any]] = (),
    assets: list[dict[str, str]] = (),
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in (*transactions, *mixed_sources, *schedules, *assets):
        payee_id = str(record.get("payee_id") or "").strip()
        if payee_id:
            counts[payee_id] = counts.get(payee_id, 0) + 1
    for entry in journals:
        payee_ids = {
            str(posting.get("payee_id") or "").strip()
            for posting in entry.get("postings", ())
            if isinstance(posting, Mapping)
            and str(posting.get("payee_id") or "").strip()
        }
        for payee_id in payee_ids:
            counts[payee_id] = counts.get(payee_id, 0) + 1
    return counts


def _tag_reference_counts(
    transactions: list[dict[str, Any]],
    mileage: list[dict[str, Any]],
    mixed_sources: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in (*transactions, *mileage, *mixed_sources, *schedules):
        for tag_id in _normalize_tag_ids(record.get("tag_ids", [])):
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


@dataclass(frozen=True)
class _ManagementSpec:
    """The domain details needed by the two sibling management sections."""

    singular: str
    plural: str
    caption: str
    merge_warning: str
    create: Callable[[str], object]
    rename: Callable[[str, str, dict[str, str]], object]
    merge: Callable[[str, list[str], list[dict[str, str]]], object]
    remove: Callable[[str, dict[str, str]], object]


def _render_management(
    context: PayeesTagsContext,
    spec: _ManagementSpec,
    records: list[dict[str, str]],
    counts: dict[str, int],
) -> None:
    """Share layout and confirmations; confirmed_write owns feedback and reruns."""
    singular = spec.singular
    plural = spec.plural
    title = singular.capitalize()
    st.subheader(plural.capitalize())
    st.caption(spec.caption)
    frame = pd.DataFrame(
        [
            {
                title: item["name"],
                "Active": str(item["active"]).upper() == "TRUE",
                "References": counts.get(item["id"], 0),
            }
            for item in records
        ],
        columns=[title, "Active", "References"],
    )
    if frame.empty:
        clear_selected_table_record(
            profile_key=context.profile_key, surface=f"managed_{singular}"
        )
        st.info(f"No {plural} yet. Add one below.")
    else:
        st.caption(f"Select one {singular} row to rename or remove it.")
        selected_id = selected_table_record(
            frame,
            [str(item["id"]) for item in records],
            profile_key=context.profile_key,
            surface=f"managed_{singular}",
            records=records,
        )

    with st.expander(f"Add {singular}", expanded=True):
        add_name = st.text_input(
            f"New {singular} name", key=f"managed_new_{singular}_{context.profile_key}"
        )
        add_error = st.empty()
        if st.button(
            f"Add {singular}",
            type="primary",
            key=f"managed_add_{singular}_{context.profile_key}",
        ):
            _write(
                context,
                f"create_{singular}",
                {"name": add_name},
                lambda: spec.create(add_name),
                f"{title} added.",
                add_error,
            )

    if not records:
        return
    by_id = _name_map(records)
    ids = list(by_id)

    def labels(value: str) -> str:
        return by_id[value]["name"]

    if selected_id:
        st.caption(f"Selected {singular}: {by_id[selected_id]['name']}")
    with st.expander(f"Rename {singular}"):
        if not selected_id:
            st.info(f"Select a {singular} row above to rename it.")
        else:
            rename_id = selected_id
            _render_rename(
                context, spec, by_id[rename_id], rename_id, title, singular
            )

    with st.expander(f"Merge {plural}"):
        target_id = st.selectbox(
            f"Target {singular}",
            ids,
            format_func=labels,
            key=f"managed_merge_{singular}_target_{context.profile_key}",
        )
        source_ids = st.multiselect(
            f"Source {plural}",
            [item for item in ids if item != target_id],
            format_func=labels,
            key=f"managed_merge_{singular}_sources_{context.profile_key}",
        )
        st.warning(spec.merge_warning)
        source_ids_key = hashlib.sha256(
            "_".join(sorted(source_ids)).encode()
        ).hexdigest()
        acknowledgment_key = (
            f"managed_merge_{singular}_ack_{context.profile_key}_{target_id}_"
            f"{source_ids_key}"
        )
        acknowledged = st.checkbox(
            f"I understand the selected source {plural} will be permanently removed",
            key=acknowledgment_key,
        )
        merge_error = st.empty()
        if st.button(
            f"Merge {plural}",
            type="primary",
            key=f"managed_merge_{plural}_{context.profile_key}",
        ):
            if not source_ids:
                merge_error.error(f"Select one or more source {plural}.")
            elif not acknowledged:
                merge_error.error(
                    "Acknowledge the permanent source removal before merging. No data changed."
                )
            else:
                _write(
                    context,
                    f"merge_{plural}",
                    {"target_id": target_id, "source_ids": source_ids},
                    lambda: spec.merge(target_id, source_ids, records),
                    f"{plural.capitalize()} merged.",
                    merge_error,
                )

    with st.expander(f"Remove {singular}"):
        if not selected_id:
            st.info(f"Select a {singular} row above to remove it.")
        else:
            _render_remove(
                context, spec, by_id[selected_id], selected_id, counts, title, singular
            )


def _render_rename(
    context: PayeesTagsContext,
    spec: _ManagementSpec,
    record: dict[str, str],
    rename_id: str,
    title: str,
    singular: str,
) -> None:
    rename_name = st.text_input(
        f"Renamed {singular} name",
        value=record["name"],
        key=f"managed_rename_{singular}_name_{context.profile_key}_{rename_id}",
    )
    rename_error = st.empty()
    if st.button(
        f"Rename {singular}",
        type="primary",
        key=f"managed_rename_{singular}_{context.profile_key}",
    ):
        _write(
            context,
            f"edit_{singular}",
            {"id": rename_id, "name": rename_name},
            lambda: spec.rename(rename_id, rename_name, record),
            f"{title} renamed.",
            rename_error,
        )


def _render_remove(
    context: PayeesTagsContext,
    spec: _ManagementSpec,
    record: dict[str, str],
    remove_id: str,
    counts: dict[str, int],
    title: str,
    singular: str,
) -> None:
    remove_name = record["name"]
    is_referenced = bool(counts.get(remove_id, 0))
    if is_referenced:
        st.info(
            f"This {singular} has {counts[remove_id]} references. Unassign it from those records or merge it before removal."
        )
    st.warning(
        f"Permanently removing {singular} {remove_name!r} cannot be undone and is available only when it is unreferenced."
    )
    selection_generation = st.session_state.get(
        f"managed_{singular}_{context.profile_key}_selection_generation", 0
    )
    remove_ack = st.checkbox(
        f"I understand {singular} {remove_name!r} will be permanently removed and cannot be restored",
        key=(
            f"managed_remove_{singular}_ack_{context.profile_key}_"
            f"{remove_id}_{selection_generation}"
        ),
        disabled=is_referenced,
    )
    remove_error = st.empty()
    with st.container(key=f"destructive_managed_{singular}_remove"):
        if st.button(
            f"Permanently remove {singular}",
            icon=":material/delete_forever:",
            key=f"managed_remove_{singular}_{context.profile_key}",
            disabled=is_referenced,
        ):
            if not remove_ack:
                remove_error.error(
                    "Acknowledge permanent removal before continuing. No data changed."
                )
            else:
                _write(
                    context,
                    f"remove_{singular}",
                    {"id": remove_id},
                    lambda: spec.remove(remove_id, record),
                    f"{title} removed.",
                    remove_error,
                )


def _render_payees(
    context: PayeesTagsContext,
    payees: list[dict[str, str]],
    transactions: list[dict[str, str]],
    mixed_sources: list[dict[str, str]],
    schedules: list[dict[str, str]],
    journals: list[dict[str, Any]],
    assets: list[dict[str, str]],
) -> None:
    _render_management(
        context,
        _ManagementSpec(
            singular="payee",
            plural="payees",
            caption=(
                "Payees are stored only in the selected business profile. Renaming keeps "
                "the stable ID and all references."
            ),
            merge_warning=(
                "Merging rewrites every transaction and mixed-use source reference, "
                "then permanently removes the selected source payees."
            ),
            create=context.services.payees.create,
            rename=lambda record_id, name, expected: context.services.payees.rename(
                record_id, name, expected=expected
            ),
            merge=lambda target_id, source_ids, expected: context.services.payees.merge(
                target_id, source_ids, expected=expected
            ),
            remove=lambda record_id, expected: context.services.payees.remove(
                record_id, expected=expected
            ),
        ),
        payees,
        _payee_reference_counts(
            transactions, mixed_sources, schedules, journals, assets
        ),
    )


def _render_tags(
    context: PayeesTagsContext,
    tags: list[dict[str, str]],
    transactions: list[dict[str, Any]],
    mileage: list[dict[str, Any]],
    mixed_sources: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
) -> None:
    _render_management(
        context,
        _ManagementSpec(
            singular="tag",
            plural="tags",
            caption=(
                "Tags are profile-local labels shared by Transactions and Mileage. "
                "Renaming keeps the stable ID and existing associations."
            ),
            merge_warning=(
                "Merging rewrites Transactions and Mileage associations, de-duplicates "
                "the target association, then permanently removes the selected source tags."
            ),
            create=context.services.tags.create,
            rename=lambda record_id, name, expected: context.services.tags.rename(
                record_id, name, expected=expected
            ),
            merge=lambda target_id, source_ids, expected: context.services.tags.merge(
                target_id, source_ids, expected=expected
            ),
            remove=lambda record_id, expected: context.services.tags.remove(
                record_id, expected=expected
            ),
        ),
        tags,
        _tag_reference_counts(transactions, mileage, mixed_sources, schedules),
    )


def render_payees_tags(context: PayeesTagsContext) -> None:
    """Render separate Payees and Tags management sections for one profile."""
    st.caption(
        f"Business profile: {context.profile_key} (all values below are profile-local)"
    )
    try:
        payees = context.services.payees.list(active_only=False)
        tags = context.services.tags.list(active_only=False)
        transactions = context.services.transactions.list()
        mixed_sources = context.services.mixed_use.sources()
        schedules = context.services.recurring.list()
        journals = context.services.journals.list()
        assets = context.services.assets.list()
        mileage = [trip.as_record() for trip in context.services.mileage.list_trips()]
    except StorageError as error:
        context.report_storage_error(error)
        return
    payees_tab, tags_tab = st.tabs(["Payees", "Tags"])
    with payees_tab:
        _render_payees(
            context,
            payees,
            transactions,
            mixed_sources,
            schedules,
            journals,
            assets,
        )
    with tags_tab:
        _render_tags(context, tags, transactions, mileage, mixed_sources, schedules)
