"""Shared transaction field composition for Add, Edit, and Copy workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import streamlit as st

from .metadata_fields import (
    render_metadata_reference,
    render_transaction_associations,
    render_transaction_date,
    render_transaction_description,
    selected_reference_id,
    transaction_category_ids,
)

TransactionFormMode = Literal["add", "edit", "copy"]
_TRANSACTION_PAYLOAD_FIELDS = (
    "txn_date",
    "kind",
    "amount",
    "account_id",
    "to_account_id",
    "category_id",
    "payee_id",
    "new_payee_name",
    "tag_ids",
    "new_tag_name",
    "reference",
    "description",
)


def transaction_widget_key(prefix: str, field_name: str, scope: str = "") -> str:
    """Return the deterministic key used by one transaction field."""
    parts = [prefix, field_name]
    if scope:
        parts.append(scope)
    return "_".join(parts)


def render_transaction_type(
    *,
    key: str = "add_transaction_kind",
    default: str = "Expense",
) -> str:
    """Render the Add-only kind selector outside the transaction form."""
    return str(
        st.segmented_control(
            "Transaction type",
            ["Income", "Expense", "Transfer"],
            default=default,
            key=key,
        )
    )


def validate_transaction_draft(draft: Mapping[str, object]) -> str | None:
    """Return validation shared by create, edit, and copy controllers."""
    try:
        amount = float(draft.get("amount", 0.0) or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return "Amount must be greater than zero."
    account_id = str(draft.get("account_id") or "")
    if not account_id:
        return "Choose an account before saving."
    if draft.get("kind") == "Transfer":
        to_account_id = str(draft.get("to_account_id") or "")
        if not to_account_id:
            return "Choose a destination account before saving a transfer."
        if account_id == to_account_id:
            return "Transfer accounts must be different."
    elif not str(draft.get("category_id") or ""):
        return "Choose a category before saving."
    return None


def transaction_payload_from_draft(
    draft: Mapping[str, object],
    *,
    description: object | None = None,
) -> dict[str, object]:
    """Return the canonical storage payload shared by Add, Edit, and Copy."""
    payload = {field: draft[field] for field in _TRANSACTION_PAYLOAD_FIELDS}
    payload["new_tag_name"] = payload["new_tag_name"] or ""
    if description is not None:
        payload["description"] = description
    return payload


def render_transaction_fields(
    *,
    mode: TransactionFormMode,
    defaults: Mapping[str, object],
    account_ids: Sequence[str],
    categories: Sequence[Mapping[str, object]],
    account_paths: Mapping[str, str],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    key_prefix: str,
    key_scope: str = "",
) -> dict[str, object]:
    """Render the shared transaction fields and return a normalized draft.

    The caller owns the surrounding form and all persistence/action controls.
    ``key_scope`` must include the selected record ID for edit/copy workflows;
    changing records therefore creates a fresh widget namespace.
    """
    kind = str(defaults.get("kind") or "Expense")

    def field_key(name: str) -> str:
        return transaction_widget_key(key_prefix, name, key_scope)

    account_id = str(defaults.get("account_id") or "")
    to_account_id = str(defaults.get("to_account_id") or "")
    category_id = str(defaults.get("category_id") or "")

    transaction_date = render_transaction_date(defaults.get("txn_date"), key=field_key("date"))
    category_ids = transaction_category_ids(categories, kind)
    category_field_name = (
        f"category_{kind.casefold()}" if mode == "add" else "category"
    )
    category_widget_key = field_key(category_field_name)
    if kind != "Transfer":
        c1, c2 = st.columns(2)
        category_id = render_metadata_reference(
            "Category", category_ids, category_paths, current_id=category_id,
            key=category_widget_key, normalize_state=True, container=c1,
        )
        amount = c2.number_input(
            "Amount",
            min_value=0.0,
            step=1.0,
            value=float(defaults.get("amount") or 0.0),
            format="%.2f",
            key=field_key("amount"),
        )
    else:
        amount = st.number_input(
            "Amount",
            min_value=0.0,
            step=1.0,
            value=float(defaults.get("amount") or 0.0),
            format="%.2f",
            key=field_key("amount"),
        )
    source_label = (
        "From Account" if kind == "Transfer" or kind == "Expense" else "To Account"
    )
    account_field_name = (
        f"account_{kind.casefold()}" if mode == "add" else "account"
    )
    account_widget_key = field_key(account_field_name)
    source_id = render_metadata_reference(
        source_label, account_ids, account_paths, current_id=account_id,
        key=account_widget_key, require_selection=mode == "copy",
    )
    if kind == "Transfer":
        to_account_ids = [
            account_id for account_id in account_ids if account_id != source_id
        ]
        to_account_widget_key = field_key("to_account")
        invalid_selected_to_account = False
        if to_account_widget_key in st.session_state:
            current_to_account = str(st.session_state[to_account_widget_key])
            resolved_to_account = selected_reference_id(current_to_account, account_paths)
            if resolved_to_account not in to_account_ids:
                st.session_state.pop(to_account_widget_key, None)
                invalid_selected_to_account = True
            elif st.session_state[to_account_widget_key] != resolved_to_account:
                st.session_state[to_account_widget_key] = resolved_to_account
        invalid_default_to_account = bool(to_account_id) and (
            to_account_id not in to_account_ids
        )
        to_index = (
            to_account_ids.index(to_account_id)
            if to_account_id in to_account_ids
            else (
                None
                if (
                    mode == "copy"
                    or invalid_default_to_account
                    or invalid_selected_to_account
                )
                else (0 if to_account_ids else None)
            )
        )
        to_account_id = (
            st.selectbox(
                "To account",
                to_account_ids,
                index=to_index,
                format_func=lambda value: account_paths.get(value, value),
                key=to_account_widget_key,
            )
            if to_account_ids
            else ""
        )
        to_account_id = selected_reference_id(to_account_id, account_paths)

    c1, c2 = st.columns(2)
    associations = render_transaction_associations(
        defaults, payees=payees, tags=tags,
        payee_key=field_key("payee"), reference_key=field_key("reference"),
        tags_key=field_key("tags"), preserve_current=mode != "copy",
        payee_container=c1, reference_container=c2,
    )
    description = render_transaction_description(
        defaults.get("description"), key=field_key("description"),
    )
    if kind == "Transfer":
        # Keep a conditional category widget's state available to Streamlit's
        # testing tree when the selected record changes to a Transfer row.
        st.session_state.setdefault(
            category_widget_key,
            category_paths.get(category_id, category_id),
        )
    return {
        "txn_date": transaction_date,
        "kind": kind,
        "amount": amount,
        "account_id": source_id,
        "to_account_id": to_account_id,
        "category_id": category_id,
        **associations,
        "description": description,
    }
