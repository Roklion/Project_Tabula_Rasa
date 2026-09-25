"""Stable-ID selection for profile-local management tables."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import streamlit as st


def _profile_epoch(state: Any, profile_key: str) -> int:
    active_profile_key = "management_table_active_profile"
    profile_epoch_key = "management_table_profile_epoch"
    if state.get(active_profile_key) != profile_key:
        state[active_profile_key] = profile_key
        state[profile_epoch_key] = int(state.get(profile_epoch_key, 0)) + 1
    return int(state[profile_epoch_key])


def clear_selected_table_record(
    *, profile_key: str, surface: str, clear_on_change: Sequence[str] = ()
) -> None:
    """Forget a selection and rotate its widget before records reappear."""
    prefix = f"{surface}_{profile_key}"
    state = st.session_state
    _profile_epoch(state, profile_key)
    should_rotate = bool(state.get(f"{prefix}_selected_id")) or (
        state.get(f"{prefix}_selection_scope") is not None
    )
    state[f"{prefix}_selected_id"] = ""
    for key in clear_on_change:
        state.pop(key, None)
    state[f"{prefix}_selection_scope"] = None
    if should_rotate:
        generation_key = f"{prefix}_table_generation"
        state[generation_key] = int(state.get(generation_key, 0)) + 1


def selected_table_record(
    frame: Any,
    record_ids: Sequence[str],
    *,
    profile_key: str,
    surface: str,
    records: Sequence[dict[str, Any]],
    clear_on_change: Sequence[str] = (),
) -> str:
    """Render a single-select table and return the selected record's stable ID.

    Rotate the widget when its data or workbook revision changes so a stale row
    position cannot silently become a different mutation target.
    """
    state = st.session_state
    profile_epoch = _profile_epoch(state, profile_key)
    prefix = f"{surface}_{profile_key}"
    selected_key = f"{prefix}_selected_id"
    scope_key = f"{prefix}_selection_scope"
    generation_key = f"{prefix}_table_generation"
    scope = (
        tuple(record_ids),
        tuple(repr(record) for record in records),
        int(state.get("workbook_data_revision", 0)),
        profile_epoch,
    )
    if state.get(scope_key) != scope:
        state[selected_key] = ""
        for key in clear_on_change:
            state.pop(key, None)
        state[generation_key] = int(state.get(generation_key, 0)) + 1
        state[scope_key] = scope
    table_key = f"{prefix}_table_{state[generation_key]}"

    def select_record() -> None:
        rows = state[table_key].selection.rows
        row = rows[0] if rows else None
        previous_id = str(state.get(selected_key) or "")
        state[selected_key] = (
            str(record_ids[row])
            if isinstance(row, int) and 0 <= row < len(record_ids)
            else ""
        )
        if state[selected_key] != previous_id:
            for key in clear_on_change:
                state.pop(key, None)
            change_key = f"{prefix}_selection_generation"
            state[change_key] = int(state.get(change_key, 0)) + 1

    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        key=table_key,
        on_select=select_record,
        selection_mode="single-row",
    )
    selected_id = str(state.get(selected_key) or "")
    return selected_id if selected_id in record_ids else ""
