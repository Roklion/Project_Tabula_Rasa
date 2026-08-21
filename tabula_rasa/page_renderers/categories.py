"""Categories hierarchy page rendering and its explicit page context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from tabula_rasa.hierarchy import (
    eligible_parent_ids,
    has_hierarchy_children,
    hierarchy_paths,
    ordered_hierarchy,
)
from tabula_rasa.page_renderers.hierarchy_ui import (
    hierarchy_layer_label,
    hierarchy_option_label,
    hierarchy_row_label,
    render_hierarchy_table,
    render_hierarchy_responsive_css,
)
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


CATEGORY_KINDS = ["Expense", "Income"]


@dataclass(frozen=True)
class CategoriesContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]


def _category_frame(
    categories: list[dict],
    transactions: list[dict],
) -> tuple[pd.DataFrame, list[str], dict[str, dict]]:
    category_by_id = {
        str(category.get("id") or "").strip(): category
        for category in categories
        if str(category.get("id") or "").strip()
    }
    transaction_count_by_id: dict[str, int] = {}
    for transaction in transactions:
        category_id = str(transaction.get("category_id") or "").strip()
        if category_id:
            transaction_count_by_id[category_id] = (
                transaction_count_by_id.get(category_id, 0) + 1
            )
    rows = []
    item_ids = []
    for category in ordered_hierarchy(categories):
        category_id = str(category.get("id") or "").strip()
        parent_id = str(category.get("parent_id") or "").strip()
        parent = category_by_id.get(parent_id)
        item_ids.append(category_id)
        rows.append(
            {
                "Category": hierarchy_row_label(category["name"], parent_id),
                "Layer": hierarchy_layer_label(parent_id),
                "Parent": parent.get("name") or "" if parent else "",
                "Type": category["kind"],
                "Transaction count": transaction_count_by_id.get(category_id, 0),
            }
        )
    return (
        pd.DataFrame(
            rows,
            columns=[
                "Category",
                "Layer",
                "Parent",
                "Type",
                "Transaction count",
            ],
        ),
        item_ids,
        category_by_id,
    )


def render_categories(context: CategoriesContext) -> None:
    """Render category creation, hierarchy management, and deletion safety."""
    render_hierarchy_responsive_css()
    render_page_header(
        "Categories",
        "Organize income and expense activity with compatible two-level paths.",
    )
    try:
        context.storage.prefetch_worksheets("Categories", "Transactions")
        categories = context.storage.list_categories()
        transactions = context.storage.list_transactions()
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()

    category_frame, category_ids, category_by_id = _category_frame(
        categories, transactions
    )
    category_paths = hierarchy_paths(categories)
    category_table_key = (
        f"category_table_{context.profile_key}_"
        f"{st.session_state.get('category_table_generation', 0)}"
    )
    st.subheader("Category hierarchy")
    st.caption(
        "Layer 2 categories must share the Income or Expense kind of their "
        "Layer 1 parent."
    )
    category_event = render_hierarchy_table(
        category_frame,
        item_ids=category_ids,
        table_key=category_table_key,
        selection_state_key="edit_category_id",
        empty_message="No categories yet. Add an Income or Expense category below.",
        column_config={
            "Transaction count": st.column_config.NumberColumn(format="%d")
        },
    )
    context.reset_widget_state_if_requested(
        "reset_add_category_form",
        keys=(
            f"new_category_name_{context.profile_key}",
            f"new_category_kind_{context.profile_key}",
        ),
        prefixes=(f"new_category_parent_{context.profile_key}_",),
    )
    with st.expander("Add category", expanded=True):
        with st.container(border=True, key="categories_add_form"):
            c1, c2, c3 = st.columns(3, gap="small")
            name = c1.text_input(
                "Category name", key=f"new_category_name_{context.profile_key}"
            )
            kind = c2.selectbox(
                "Type", CATEGORY_KINDS, key=f"new_category_kind_{context.profile_key}"
            )
            parent_options = [""] + eligible_parent_ids(
                categories,
                compatibility_field="kind",
                compatibility_value=kind,
            )
            parent_id = c3.selectbox(
                "Parent category (optional)",
                parent_options,
                key=f"new_category_parent_{context.profile_key}_{kind}",
                format_func=lambda value: hierarchy_option_label(value, category_paths),
            )
            if st.button("Add category", type="primary"):
                payload = {"name": name, "kind": kind, "parent_id": parent_id}
                context.confirmed_write(
                    "create_category",
                    payload,
                    lambda: context.storage.create_category(
                        name, kind, parent_id=parent_id
                    ),
                    "Category added.",
                    on_success=lambda: context.schedule_widget_reset(
                        "reset_add_category_form"
                    ),
                )
    if categories:
        selected_rows = category_event.selection.rows
        if st.session_state.get("edit_category_id") not in category_by_id:
            st.session_state["edit_category_id"] = category_ids[0]
        st.caption("Select a category row (or double-click it) to edit it.")
        with st.expander("Edit category", expanded=bool(selected_rows)):
            category_id = st.selectbox(
                "Category to edit",
                category_ids,
                format_func=lambda value: (
                    f"{category_paths[value]} ({category_by_id[value]['kind']})"
                ),
                key="edit_category_id",
            )
            selected = category_by_id[category_id]
            with st.container(border=True):
                st.caption(
                    "Renaming, promotion, or reparenting keeps this category's "
                    "stable ID and existing transaction references."
                )
                edited_name = st.text_input(
                    "Edit category name",
                    value=selected["name"],
                    key=f"edit_category_name_{category_id}",
                )
                edited_kind = st.selectbox(
                    "Edit category type",
                    CATEGORY_KINDS,
                    index=CATEGORY_KINDS.index(selected["kind"]),
                    key=f"edit_category_kind_{category_id}",
                )
                has_children = has_hierarchy_children(categories, category_id)
                edited_parent_options = [""] + eligible_parent_ids(
                    categories,
                    compatibility_field="kind",
                    compatibility_value=edited_kind,
                    item_id=category_id,
                )
                current_parent_id = str(selected.get("parent_id") or "").strip()
                edited_parent_id = st.selectbox(
                    "Edit parent category",
                    edited_parent_options,
                    index=(
                        edited_parent_options.index(current_parent_id)
                        if current_parent_id in edited_parent_options
                        else 0
                    ),
                    key=(
                        f"edit_category_parent_{context.profile_key}_{category_id}_"
                        f"{edited_kind}"
                    ),
                    format_func=lambda value: hierarchy_option_label(
                        value, category_paths
                    ),
                    disabled=has_children,
                )
                if has_children:
                    st.info(
                        "This Layer 1 category has children. Promote or reparent "
                        "those children before moving this category under a parent."
                    )
                if st.button(
                    "Save category changes",
                    type="primary",
                    key=f"save_category_{category_id}",
                ):
                    payload = {
                        "id": category_id,
                        "name": edited_name,
                        "kind": edited_kind,
                        "parent_id": edited_parent_id,
                    }
                    context.confirmed_write(
                        "edit_category",
                        payload,
                        lambda: context.storage.edit_category(
                            category_id,
                            name=edited_name,
                            kind=edited_kind,
                            parent_id=edited_parent_id,
                        ),
                        "Category updated.",
                    )
                st.warning(
                    "Permanent deletion removes this category record only. "
                    "Categories with transactions or child categories are blocked."
                )
                confirm_delete = st.checkbox(
                    "I understand this category will be permanently deleted",
                    key=f"confirm_delete_category_{category_id}",
                )
                if st.button(
                    "Permanently delete category",
                    icon=":material/delete_forever:",
                    key=f"delete_category_{category_id}",
                ):
                    if not confirm_delete:
                        st.error(
                            "Confirm that you understand deletion is permanent. "
                            "No data changed."
                        )
                    else:
                        context.confirmed_write(
                            "delete_category",
                            {"id": category_id},
                            lambda: context.storage.delete_category(category_id),
                            "Category deleted.",
                        )
