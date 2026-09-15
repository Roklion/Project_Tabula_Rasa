"""Common transaction metadata widgets, independent of amount and allocation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import streamlit as st

from tabula_rasa.hierarchy import ordered_categories
from tabula_rasa.page_renderers.tag_selector import render_tag_selector
from .payee_selector import render_payee_selector


def selected_reference_id(value: object, paths: Mapping[str, str]) -> str:
    """Normalize a widget ID or formatted display label to its stored ID."""
    if value is None:
        return ""
    value = str(value)
    return next(
        (item_id for item_id, label in paths.items() if item_id == value or label == value),
        value,
    )


def transaction_category_ids(
    categories: Sequence[Mapping[str, object]], kind: str,
) -> list[str]:
    return [
        str(item.get("id") or "").strip()
        for item in ordered_categories(categories)
        if item.get("kind") == kind and str(item.get("id") or "").strip()
    ]


def render_transaction_date(value: object, *, key: str) -> date:
    try:
        default = value if isinstance(value, date) else date.fromisoformat(str(value or date.today()))
    except ValueError:
        default = date.today()
    return st.date_input("Date", default, key=key)


def render_metadata_reference(
    label: str,
    ids: Sequence[str],
    paths: Mapping[str, str],
    *,
    current_id: str = "",
    key: str | None = None,
    require_selection: bool = False,
    normalize_state: bool = False,
    container: Any = None,
) -> str:
    """Select an account/category from the caller's eligible reference set.

    Callers retain eligibility rules, including historical-reference repair.
    Copy forms can require an explicit replacement for an unavailable reference.
    """
    ids = list(dict.fromkeys(str(value).strip() for value in ids if str(value).strip()))
    if normalize_state and key is not None and key in st.session_state:
        current = selected_reference_id(st.session_state[key], paths)
        if current not in ids:
            st.session_state.pop(key, None)
        elif st.session_state[key] != current:
            st.session_state[key] = current
    index = ids.index(current_id) if current_id in ids else (
        None if require_selection or not ids else 0
    )
    selected = (container if container is not None else st).selectbox(
        label, ids, index=index,
        format_func=lambda value: paths.get(value, value), key=key,
    )
    return selected_reference_id(selected, paths)


def render_transaction_associations(
    defaults: Mapping[str, object],
    *,
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    payee_key: str,
    reference_key: str,
    tags_key: str,
    preserve_current: bool,
    payee_container: Any = None,
    reference_container: Any = None,
) -> dict[str, object]:
    """Collect managed Payee/Tags and reference text with common selection rules."""
    payee_id, new_payee_name = render_payee_selector(
        payees, key=payee_key,
        selected_id=str(defaults.get("payee_id") or ""),
        selected_label=str(defaults.get("payee") or "") or None,
        preserve_selected_id=preserve_current, container=payee_container,
    )
    reference = (reference_container if reference_container is not None else st).text_input(
        "Reference (optional)", str(defaults.get("reference") or ""), key=reference_key,
    )
    selected_tags = defaults.get("tag_ids") or ()
    tag_ids, new_tag_name = render_tag_selector(
        tags, label="Tags", key=tags_key, selected_ids=selected_tags,
        preserve_inactive_ids=selected_tags if preserve_current else (),
    )
    return {
        "payee_id": payee_id, "new_payee_name": new_payee_name,
        "reference": reference, "tag_ids": tag_ids, "new_tag_name": new_tag_name,
    }


def render_transaction_description(value: object, *, key: str) -> str:
    return st.text_input("Description / memo", str(value or ""), key=key)
