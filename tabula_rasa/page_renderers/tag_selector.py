"""Shared Tag selector controls for transaction-like entry forms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st


ADD_NEW_TAG = "+ Add new tag"


def inline_tag_name_error(new_name: str | None) -> str | None:
    """Return the validation message for an explicitly requested new Tag."""
    if new_name is not None and not new_name.strip():
        return "Enter a Tag name before saving."
    return None


def _tag_id(tag: Mapping[str, Any]) -> str:
    return str(tag.get("id") or "").strip()


def _tag_name(tag: Mapping[str, Any]) -> str:
    return str(tag.get("name") or "").strip()


def _tag_is_active(tag: Mapping[str, Any]) -> bool:
    value = tag.get("active", True)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() == "true"


def _tag_label(tag: Mapping[str, Any], *, inactive: bool = False) -> str:
    name = _tag_name(tag) or _tag_id(tag)
    return f"{name} (inactive)" if inactive else name


def render_tag_selector(
    tags: Sequence[Mapping[str, Any]],
    *,
    label: str,
    key: str,
    selected_ids: Sequence[object] = (),
    preserve_inactive_ids: Sequence[object] = (),
    disabled: bool = False,
) -> tuple[list[str], str | None]:
    """Render an optional multi-Tag selector and return stable IDs plus new name.

    The ``+ Add new tag`` sentinel is never returned in ``tag_ids``. Existing
    inactive Tags are offered only when they belong to the selected record, so
    historical associations can be retained while editing. The new Tag name
    is submitted alongside the record and is created by the storage write.
    """
    by_id = {
        tag_id: tag
        for tag in tags
        if (tag_id := _tag_id(tag)) and _tag_name(tag)
    }
    selected = [str(value).strip() for value in selected_ids if str(value).strip()]
    preserved = {
        str(value).strip()
        for value in preserve_inactive_ids
        if str(value).strip()
    }
    available_ids = [
        tag_id
        for tag_id, tag in by_id.items()
        if _tag_is_active(tag) or tag_id in preserved or tag_id in selected
    ]
    # Keep the shared selector's order stable while avoiding duplicate IDs.
    options = [ADD_NEW_TAG, *available_ids]
    options_by_id = {
        tag_id: _tag_label(by_id[tag_id], inactive=not _tag_is_active(by_id[tag_id]))
        for tag_id in available_ids
    }
    if key not in st.session_state:
        initial_ids: list[str] = []
        for tag_id in selected:
            if tag_id in available_ids and tag_id not in initial_ids:
                initial_ids.append(tag_id)
        st.session_state[key] = initial_ids
    chosen = st.multiselect(
        label,
        options,
        key=key,
        format_func=lambda value: (
            options_by_id.get(value, value) if value != ADD_NEW_TAG else value
        ),
        placeholder="No Tag",
        disabled=disabled,
        help="Tags are optional and independent of Category.",
    )
    chosen_ids = [value for value in chosen if value != ADD_NEW_TAG]
    new_name: str | None = None
    if ADD_NEW_TAG in chosen:
        new_name = st.text_input(
            "New tag",
            key=f"{key}__new_name",
            disabled=disabled,
            help="The new Tag is created and selected when the record is saved.",
        )
    return chosen_ids, new_name
