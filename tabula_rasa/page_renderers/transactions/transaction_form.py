"""Shared transaction field composition for Add, Edit, and Copy workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal

import streamlit as st

from tabula_rasa.hierarchy import ordered_categories
from tabula_rasa.page_renderers.tag_selector import render_tag_selector
from tabula_rasa.page_renderers.transactions.payee_selector import (
    render_payee_selector,
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

    def selected_id(value: object, paths: Mapping[str, str]) -> str:
        """Normalize a widget ID or its formatted display value to an ID."""
        if value is None:
            return ""
        value = str(value)
        return next(
            (item_id for item_id, label in paths.items() if item_id == value or label == value),
            value,
        )

    raw_date = defaults.get("txn_date")
    try:
        transaction_date = (
            raw_date
            if isinstance(raw_date, date)
            else date.fromisoformat(str(raw_date or date.today()))
        )
    except ValueError:
        transaction_date = date.today()
    account_id = str(defaults.get("account_id") or "")
    to_account_id = str(defaults.get("to_account_id") or "")
    category_id = str(defaults.get("category_id") or "")
    payee_id = str(defaults.get("payee_id") or "")
    tag_ids = defaults.get("tag_ids") or ()

    transaction_date = st.date_input("Date", transaction_date, key=field_key("date"))
    categories_for_kind = [
        category
        for category in ordered_categories(categories)
        if category.get("kind") == kind
    ]
    category_ids = [
        str(category.get("id") or "").strip()
        for category in categories_for_kind
        if str(category.get("id") or "").strip()
    ]
    category_field_name = (
        f"category_{kind.casefold()}" if mode == "add" else "category"
    )
    category_widget_key = field_key(category_field_name)
    if kind != "Transfer" and category_widget_key in st.session_state:
        category_ids_by_label = {
            str(label): str(cat_id)
            for cat_id, label in category_paths.items()
        }
        current_category = str(st.session_state[category_widget_key])
        resolved_category = category_ids_by_label.get(
            current_category, current_category
        )
        if resolved_category not in category_ids:
            st.session_state.pop(category_widget_key, None)
        elif st.session_state[category_widget_key] != resolved_category:
            st.session_state[category_widget_key] = resolved_category
    if kind != "Transfer":
        c1, c2 = st.columns(2)
        category_value = c1.selectbox(
            "Category",
            category_ids,
            index=(
                category_ids.index(category_id)
                if category_id in category_ids
                else (0 if category_ids else None)
            ),
            format_func=lambda value: category_paths.get(value, value),
            key=category_widget_key,
        )
        category_id = selected_id(category_value, category_paths)
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
    account_ids = list(
        dict.fromkeys(
            str(acc_id).strip()
            for acc_id in account_ids
            if str(acc_id).strip()
        )
    )
    account_index = (
        account_ids.index(account_id)
        if account_id in account_ids
        else (None if mode == "copy" else (0 if account_ids else None))
    )
    source_label = (
        "From Account" if kind == "Transfer" or kind == "Expense" else "To Account"
    )
    account_field_name = (
        f"account_{kind.casefold()}" if mode == "add" else "account"
    )
    account_widget_key = field_key(account_field_name)
    source = st.selectbox(
        source_label,
        account_ids,
        index=account_index,
        format_func=lambda value: account_paths.get(value, value),
        key=account_widget_key,
    )
    source_id = selected_id(source, account_paths)
    if kind == "Transfer":
        to_account_ids = [
            account_id for account_id in account_ids if account_id != source_id
        ]
        to_account_widget_key = field_key("to_account")
        invalid_selected_to_account = False
        if to_account_widget_key in st.session_state:
            current_to_account = str(st.session_state[to_account_widget_key])
            resolved_to_account = selected_id(current_to_account, account_paths)
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
        to_account_id = selected_id(to_account_id, account_paths)

    c1, c2 = st.columns(2)
    payee_id, new_payee_name = render_payee_selector(
        payees,
        key=field_key("payee"),
        selected_id=payee_id,
        preserve_selected_id=mode != "copy",
        container=c1,
    )
    reference = c2.text_input(
        "Reference (optional)",
        str(defaults.get("reference") or ""),
        key=field_key("reference"),
    )
    tag_ids, new_tag_name = render_tag_selector(
        tags,
        label="Tags",
        key=field_key("tags"),
        selected_ids=tag_ids,
        preserve_inactive_ids=(tag_ids if mode != "copy" else ()),
    )
    description = st.text_input(
        "Description / memo",
        str(defaults.get("description") or ""),
        key=field_key("description"),
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
        "payee_id": payee_id,
        "new_payee_name": new_payee_name,
        "tag_ids": tag_ids,
        "new_tag_name": new_tag_name,
        "reference": reference,
        "description": description,
    }
