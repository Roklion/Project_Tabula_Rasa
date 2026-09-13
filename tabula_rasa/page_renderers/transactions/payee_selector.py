"""Shared Payee selector value handling for transaction forms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st


def render_payee_selector(
    payees: Sequence[Mapping[str, Any]],
    *,
    key: str,
    selected_id: object = "",
    preserve_selected_id: bool = False,
    selected_label: str | None = None,
    container: Any | None = None,
) -> tuple[str, str]:
    """Render the shared managed-Payee selector and return stable values.

    Active Payees are offered by default. ``preserve_selected_id`` keeps an
    inactive association available while editing an existing source; the
    optional ``selected_label`` preserves a source-specific display name for
    that inactive association.
    """
    current_id = str(selected_id or "")
    payee_by_id = {
        str(item.get("id") or ""): str(item.get("name") or "")
        for item in payees
        if str(item.get("id") or "")
    }
    available_payees = [
        item
        for item in payees
        if str(item.get("active", "")).upper() == "TRUE"
        or (preserve_selected_id and str(item.get("id") or "") == current_id)
    ]
    payee_options = [""] + [
        str(item["id"])
        for item in available_payees
        if str(item.get("id") or "")
    ]
    selected_payee = next(
        (
            item
            for item in available_payees
            if str(item.get("id") or "") == current_id
        ),
        None,
    )
    if (
        preserve_selected_id
        and current_id
        and current_id in payee_options
        and selected_payee is not None
        and str(selected_payee.get("active", "")).upper() != "TRUE"
    ):
        payee_by_id[current_id] = (
            f"{selected_label or payee_by_id.get(current_id) or current_id} (inactive)"
        )
    selector = container or st
    payee_value = selector.selectbox(
        "Payee / customer",
        payee_options,
        index=payee_options.index(current_id) if current_id in payee_options else 0,
        format_func=lambda value: payee_by_id.get(
            value, "No payee" if value == "" else value
        ),
        key=key,
        accept_new_options=True,
    )
    return resolve_payee_selection(payee_value, available_payees, payee_options)


def resolve_payee_selection(
    value: object,
    payees: Sequence[Mapping[str, Any]],
    allowed_ids: Sequence[str],
) -> tuple[str, str]:
    """Return the selected managed ID and any new inline Payee name."""
    typed_name = str(value or "").strip()
    allowed = set(allowed_ids)
    payee_id = typed_name if typed_name in allowed else ""
    by_name = {
        str(payee.get("name") or "").strip().casefold(): str(payee["id"])
        for payee in payees
        if str(payee.get("name") or "").strip()
        and str(payee.get("id") or "") in allowed
    }
    if not payee_id and typed_name:
        payee_id = by_name.get(typed_name.casefold(), "")
    return payee_id, "" if payee_id or not typed_name else typed_name
