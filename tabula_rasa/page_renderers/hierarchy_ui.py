"""Shared presentation controls for the two hierarchy-management pages."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import streamlit as st


def hierarchy_option_label(value: str, paths: Mapping[str, str]) -> str:
    """Render a parent selector value without changing its stored ID."""
    return "None (Layer 1)" if not value else paths.get(value, value)


def hierarchy_row_label(name: str, parent_id: str) -> str:
    """Indent a child for display while retaining its raw name elsewhere."""
    return f"↳ {name}" if parent_id else name


def hierarchy_layer_label(parent_id: str) -> str:
    """Return the explicit two-level state label used in hierarchy tables."""
    return "Layer 2" if parent_id else "Layer 1"


def render_hierarchy_table(
    frame: pd.DataFrame,
    *,
    item_ids: list[str],
    table_key: str,
    selection_state_key: str,
    empty_message: str,
    column_config: dict | None = None,
) -> object:
    """Render a selectable hierarchy table with stable ID-backed selection."""

    def select_item() -> None:
        selected_rows = st.session_state[table_key].selection.rows
        if selected_rows:
            st.session_state[selection_state_key] = item_ids[selected_rows[0]]

    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        key=table_key,
        on_select=select_item,
        selection_mode="single-row",
        column_config=column_config,
    )
    if frame.empty:
        st.info(empty_message)
    return event
