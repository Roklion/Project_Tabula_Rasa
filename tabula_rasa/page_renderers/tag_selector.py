"""Shared Tag selector controls for transaction-like entry forms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st


def inline_tag_name_error(new_name: str | None) -> str | None:
    """Return the validation message for a typed new Tag name."""
    if new_name is not None:
        stripped = new_name.strip()
        if not stripped:
            return "Enter a Tag name before saving."
    return None


def tag_selector_error(key: str) -> str | None:
    """Return a validation error for the selector's current custom values."""
    return st.session_state.get(f"{key}__error")


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


def schedule_tag_selector_reset(key: str) -> None:
    """Reset one selector on the rerun after its confirmed write."""
    st.session_state[f"{key}__reset"] = True


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

    Existing inactive Tags are offered only when they belong to the selected
    record, so historical associations can be retained while editing. A typed
    new Tag name is submitted alongside the record and created by the storage
    write.
    """
    if st.session_state.pop(f"{key}__reset", False):
        st.session_state.pop(key, None)
    st.session_state.pop(f"{key}__error", None)
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
    options = available_ids
    options_by_id = {
        tag_id: _tag_label(by_id[tag_id], inactive=not _tag_is_active(by_id[tag_id]))
        for tag_id in available_ids
    }
    by_name = {
        _tag_name(tag).casefold(): tag_id
        for tag_id, tag in by_id.items()
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
            options_by_id.get(value, value)
        ),
        placeholder="No Tag",
        disabled=disabled,
        help="Tags are optional and independent of Category.",
        accept_new_options=True,
    )
    chosen_ids: list[str] = []
    typed_names: list[str] = []
    for value in chosen:
        if value in by_id:
            if value not in chosen_ids:
                chosen_ids.append(value)
            continue
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            existing_id = by_name.get(stripped.casefold())
            if existing_id is not None:
                if existing_id not in chosen_ids:
                    chosen_ids.append(existing_id)
            else:
                typed_names.append(stripped)
    new_name: str | None = typed_names[0] if len(typed_names) == 1 else None
    if len(typed_names) > 1:
        st.session_state[f"{key}__error"] = "Enter one new Tag name at a time."
    return chosen_ids, new_name
