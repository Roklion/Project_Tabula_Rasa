"""Approved bulk transaction actions and safeguards."""

from __future__ import annotations

from tabula_rasa.application.financial_csv import frame_csv

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
import hashlib
from typing import Any
import streamlit as st
from tabula_rasa.hierarchy import ordered_categories
from tabula_rasa.ledger_presentation import money
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.errors import StorageError
from .ledger_filters import _bulk_selection_key, transaction_is_source_driven
from .receipt_workflows import clear_receipt_creation_recovery

MIXED_FIELD_VALUE = "__tabula_rasa_mixed__"


def _clean_bulk_tag_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, Sequence):
        values = value
    else:
        values = []
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _shared_bulk_value(values: Sequence[object]) -> object:
    unique = list(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else MIXED_FIELD_VALUE


def _bulk_scope_key(context: TransactionsContext) -> str:
    return (
        f"{context.profile_key}_"
        f"{st.session_state.get('transaction_bulk_selection_generation', 0)}"
    )


def _latest_active_recurring_ids(
    transactions: Sequence[Mapping[str, object]],
    selected_ids: Sequence[str],
    active_schedule_ids: set[str],
) -> tuple[str, ...]:
    latest_dates: dict[str, str] = {}
    for transaction in transactions:
        schedule_id = str(transaction.get("recurring_schedule_id") or "").strip()
        scheduled_date = str(
            transaction.get("recurring_scheduled_date") or ""
        ).strip()
        if schedule_id and scheduled_date:
            latest_dates[schedule_id] = max(
                latest_dates.get(schedule_id, ""), scheduled_date
            )
    selected_by_id = {
        str(transaction.get("id") or ""): transaction
        for transaction in transactions
    }
    return tuple(
        sorted(
            {
                schedule_id
                for transaction_id in selected_ids
                for schedule_id in [
                    str(
                        selected_by_id.get(transaction_id, {}).get(
                            "recurring_schedule_id"
                        )
                        or ""
                    ).strip()
                ]
                if schedule_id in active_schedule_ids
                and str(
                    selected_by_id.get(transaction_id, {}).get(
                        "recurring_scheduled_date"
                    )
                    or ""
                ).strip()
                == latest_dates.get(schedule_id)
            }
        )
    )


def _bulk_widget_keys(scope: str, field: str) -> tuple[str, str, str]:
    return (
        f"transaction_bulk_{field}_{scope}",
        f"transaction_bulk_apply_{field}_{scope}",
        f"transaction_bulk_intent_{field}_{scope}",
    )


def _sync_bulk_field_intent(
    widget_key: str,
    initial_value: object,
    apply_key: str,
    intent_key: str,
) -> None:
    st.session_state[intent_key] = bool(
        st.session_state.get(apply_key, False)
    ) or st.session_state.get(widget_key) != initial_value


def _initialize_bulk_widget(
    widget_key: str,
    initial_value: object,
    intent_key: str,
    *,
    reset: bool = False,
) -> None:
    if reset or widget_key not in st.session_state:
        st.session_state[widget_key] = initial_value
    if reset or intent_key not in st.session_state:
        st.session_state[intent_key] = False


def _bulk_payee_names(
    payees: Sequence[Mapping[str, object]],
    selected_payee_ids: Sequence[str],
) -> dict[str, str]:
    selected_ids = {
        str(payee_id).strip()
        for payee_id in selected_payee_ids
        if str(payee_id).strip()
    }
    payee_names: dict[str, str] = {}
    for payee in payees:
        payee_id = str(payee.get("id") or "").strip()
        if not payee_id:
            continue
        if str(payee.get("active")) != "TRUE" and payee_id not in selected_ids:
            continue
        payee_names[payee_id] = str(payee.get("name") or "").strip()
    return payee_names


def _clear_bulk_editor_intent(scope: str) -> None:
    # Widget state can only be changed before the widget is instantiated on
    # the next run. Schedule the reset and let the renderer perform it at the
    # top of that run, after the confirmed-write rerun starts.
    st.session_state[f"transaction_bulk_editor_reset_{scope}"] = True


def _render_bulk_field_apply_checkbox(
    label: str,
    *,
    widget_key: str,
    initial_value: object,
    apply_key: str,
    intent_key: str,
    disabled: bool,
) -> None:
    st.checkbox(
        f"Apply {label} to all selected",
        key=apply_key,
        disabled=disabled,
        on_change=_sync_bulk_field_intent,
        args=(widget_key, initial_value, apply_key, intent_key),
        help=(
            "Select this to intentionally reapply the displayed shared value "
            "or to confirm an explicit replacement, including clearing it."
        ),
    )


def _render_bulk_editor(
    context: TransactionsContext,
    *,
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    expected_selected: Sequence[Mapping[str, object]],
    selected_ids: Sequence[str],
    selected_protected: bool,
    selected_snapshot_key: str,
) -> None:
    """Render the explicit partial-change editor for the selected rows."""
    scope = _bulk_scope_key(context)
    disabled = selected_protected
    changes: dict[str, Any] = {}
    invalid_fields: list[str] = []

    selected_kinds = {str(item.get("kind", "")) for item in expected_selected}
    editor_snapshot_key = f"transaction_bulk_editor_snapshot_{scope}"
    reset_widgets = (
        st.session_state.get(editor_snapshot_key) != selected_snapshot_key
    )
    reset_widgets = reset_widgets or bool(
        st.session_state.get(f"transaction_bulk_editor_reset_{scope}")
    )
    st.session_state[editor_snapshot_key] = selected_snapshot_key
    st.session_state.pop(f"transaction_bulk_editor_reset_{scope}", None)
    if reset_widgets:
        for field in ("category", "payee", "tags"):
            _, apply_key, intent_key = _bulk_widget_keys(scope, field)
            st.session_state[apply_key] = False
            st.session_state[intent_key] = False
    category_eligible = selected_kinds in ({"Income"}, {"Expense"})
    if selected_protected:
        st.info(
            "Bulk Category, Payee, and Tags changes are disabled because the "
            "selection includes a mixed-use projection or depreciation entry. "
            "Manage it from Mixed-use expenses or Assets."
        )
    if not category_eligible:
        st.info(
            "Category changes are disabled because Bulk category changes require "
            "a homogeneous Income or Expense selection; transfers are not eligible."
        )
    else:
        common_kind = next(iter(selected_kinds))
        category_map = {
            str(category.get("id") or "").strip(): category_paths[str(category.get("id") or "").strip()]
            for category in ordered_categories(categories)
            if category.get("kind") == common_kind
            and str(category.get("id") or "").strip() in category_paths
        }
        if not category_map:
            st.info(f"No categories of type {common_kind.lower()} are available.")
        else:
            category_ids = [str(item.get("category_id") or "") for item in expected_selected]
            common_category = _shared_bulk_value(category_ids)
            category_options = list(category_map)
            if common_category == MIXED_FIELD_VALUE:
                category_options.insert(0, MIXED_FIELD_VALUE)
            category_key, apply_key, intent_key = _bulk_widget_keys(scope, "category")
            initial_category = (
                common_category
                if common_category in category_options
                else MIXED_FIELD_VALUE
            )
            _initialize_bulk_widget(
                category_key,
                initial_category,
                intent_key,
                reset=reset_widgets,
            )
            st.selectbox(
                "Category",
                category_options,
                key=category_key,
                format_func=lambda value: (
                    "Mixed / Multiple values"
                    if value == MIXED_FIELD_VALUE
                    else category_paths.get(value, value)
                ),
                disabled=disabled,
                on_change=_sync_bulk_field_intent,
                args=(category_key, initial_category, apply_key, intent_key),
                help="Current value is informational until you explicitly apply Category.",
            )
            if common_category == MIXED_FIELD_VALUE:
                st.caption("Current Category: Mixed / Multiple values")
            _render_bulk_field_apply_checkbox(
                "Category",
                widget_key=category_key,
                initial_value=initial_category,
                apply_key=apply_key,
                intent_key=intent_key,
                disabled=disabled,
            )
            if st.session_state.get(intent_key):
                requested_category = st.session_state.get(category_key)
                if requested_category == MIXED_FIELD_VALUE:
                    invalid_fields.append("Category")
                else:
                    changes["category_id"] = requested_category

    payee_ids = [str(item.get("payee_id") or "").strip() for item in expected_selected]
    common_payee = _shared_bulk_value(payee_ids)
    payee_names = _bulk_payee_names(payees, payee_ids)
    payee_options = ["", *payee_names]
    if common_payee == MIXED_FIELD_VALUE:
        payee_options.insert(0, MIXED_FIELD_VALUE)
    payee_key, apply_key, intent_key = _bulk_widget_keys(scope, "payee")
    initial_payee = common_payee if common_payee in payee_options else MIXED_FIELD_VALUE
    _initialize_bulk_widget(
        payee_key, initial_payee, intent_key, reset=reset_widgets
    )
    st.selectbox(
        "Payee",
        payee_options,
        key=payee_key,
        format_func=lambda value: (
            "Mixed / Multiple values"
            if value == MIXED_FIELD_VALUE
            else "No Payee / blank" if value == "" else payee_names.get(value, value)
        ),
        disabled=disabled,
        on_change=_sync_bulk_field_intent,
        args=(payee_key, initial_payee, apply_key, intent_key),
        help="Bulk Payee uses existing profile-local Payee records only.",
    )
    if common_payee == MIXED_FIELD_VALUE:
        st.caption("Current Payee: Mixed / Multiple values")
    _render_bulk_field_apply_checkbox(
        "Payee",
        widget_key=payee_key,
        initial_value=initial_payee,
        apply_key=apply_key,
        intent_key=intent_key,
        disabled=disabled,
    )
    if st.session_state.get(intent_key):
        requested_payee = st.session_state.get(payee_key)
        if requested_payee == MIXED_FIELD_VALUE:
            invalid_fields.append("Payee")
        else:
            changes["payee_id"] = requested_payee or ""

    tag_names = {
        str(tag.get("id") or "").strip(): str(tag.get("name") or "").strip()
        for tag in tags
        if str(tag.get("id") or "").strip() and str(tag.get("name") or "").strip()
    }
    tag_active = {
        str(tag.get("id") or "").strip(): str(tag.get("active")) == "TRUE"
        for tag in tags
    }
    current_tag_sets = [
        _clean_bulk_tag_ids(item.get("tag_ids", ())) for item in expected_selected
    ]
    common_tags = _shared_bulk_value(current_tag_sets)
    current_tag_ids = set().union(*current_tag_sets) if current_tag_sets else set()
    tag_options = [
        tag_id
        for tag_id in tag_names
        if tag_active.get(tag_id, True)
        or tag_id in current_tag_ids
    ]
    tag_key, apply_key, intent_key = _bulk_widget_keys(scope, "tags")
    initial_tags = list(common_tags) if common_tags != MIXED_FIELD_VALUE else []
    _initialize_bulk_widget(tag_key, initial_tags, intent_key, reset=reset_widgets)
    st.multiselect(
        "Tags",
        tag_options,
        key=tag_key,
        format_func=lambda value: tag_names.get(value, value),
        disabled=disabled,
        on_change=_sync_bulk_field_intent,
        args=(tag_key, initial_tags, apply_key, intent_key),
        placeholder="No Tag",
        help="Replacement model: applying Tags replaces the complete Tag set.",
    )
    if common_tags == MIXED_FIELD_VALUE:
        st.caption("Current Tags: Mixed / Multiple values")
    _render_bulk_field_apply_checkbox(
        "Tags",
        widget_key=tag_key,
        initial_value=initial_tags,
        apply_key=apply_key,
        intent_key=intent_key,
        disabled=disabled,
    )
    if st.session_state.get(intent_key):
        changes["tag_ids"] = list(
            dict.fromkeys(
                str(tag_id).strip()
                for tag_id in st.session_state.get(tag_key, [])
                if str(tag_id).strip()
            )
        )

    if invalid_fields:
        st.error(
            "Choose a concrete value for "
            + ", ".join(invalid_fields)
            + " before applying changes."
        )
    elif changes:
        labels = {
            "category_id": "Category",
            "payee_id": "Payee",
            "tag_ids": "Tags",
        }
        st.caption(
            "Review: change "
            + ", ".join(labels[field] for field in changes)
            + f" for {len(selected_ids)} selected transaction(s)."
        )
    else:
        st.caption(
            "No fields selected for change. Apply changes will be a no-op until "
            "you change or explicitly apply a field."
        )

    with st.form("transaction_bulk_edit_save", clear_on_submit=False):
        edit_error = st.empty()
        save_requested = st.form_submit_button(
            "Apply changes",
            type="primary",
            width="stretch",
            disabled=disabled,
        )
    if save_requested:
        if invalid_fields:
            edit_error.error(
                "Choose a concrete value for "
                + ", ".join(invalid_fields)
                + " before applying changes."
            )
        elif not changes:
            edit_error.info("No changes selected; no transactions were updated.")
        else:
            context.confirmed_write(
                "bulk_edit_transactions",
                {
                    "ids": list(selected_ids),
                    "expected": expected_selected,
                    "changes": changes,
                },
                lambda: context.services.transactions.bulk_update(
                    selected_ids,
                    expected=expected_selected,
                    changes=changes,
                ),
                lambda result: (
                    f"{', '.join({'category_id': 'Category', 'payee_id': 'Payee', 'tag_ids': 'Tags'}[field] for field in changes)} "
                    f"updated for {result['count']} transactions."
                ),
                on_success=lambda: _clear_bulk_editor_intent(
                    scope
                ),
                report_error=edit_error.error,
            )


def render_bulk_actions(
    context: TransactionsContext,
    *,
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
    transaction_frame,
    transactions: Sequence[Mapping[str, object]],
    selected_ids: Sequence[str],
    selected_protected: bool,
    expected_selected: Sequence[Mapping[str, object]],
    selected_snapshot_key: str,
) -> None:
    selected_ids = tuple(
        str(transaction_id)
        for transaction_id in st.session_state.get(
            _bulk_selection_key(context.profile_key), ()
        )
    )
    st.caption(f"{len(selected_ids)} transaction(s) selected")
    if selected_ids:
        selected_by_id = {
            str(transaction.get("id", "")): transaction
            for transaction in transactions
        }
        expected_selected = [selected_by_id[item] for item in selected_ids]
        if any(transaction_is_source_driven(item) for item in expected_selected):
            st.error(
                "This selection includes a mixed-use projection or depreciation entry. Bulk changes "
                "and deletion are disabled; manage it "
                "from Mixed-use expenses or Assets."
            )
        active_schedule_ids: set[str] = set()
        schedule_status_error: StorageError | None = None
        if any(
            str(transaction.get("recurring_schedule_id") or "").strip()
            for transaction in expected_selected
        ):
            try:
                active_schedule_ids = {
                    str(schedule.get("id") or "").strip()
                    for schedule in context.services.recurring.list(fresh=True)
                    if schedule.get("status") == "active"
                }
            except StorageError as error:
                schedule_status_error = error
        warning_schedule_ids = _latest_active_recurring_ids(
            transactions, selected_ids, active_schedule_ids
        )
        if warning_schedule_ids:
            st.warning(
                "This selection includes the latest current occurrence of "
                f"{len(warning_schedule_ids)} active recurring series. "
                "Deleting it may make reconciliation regenerate the due date."
            )
        if schedule_status_error is not None:
            st.warning(
                "Recurring schedule status could not be refreshed; bulk deletion "
                "is disabled until the ledger can be refreshed."
            )
        selected_snapshot_key = hashlib.sha256(
            repr(
                tuple(
                    tuple(
                        sorted((str(key), str(value)) for key, value in item.items())
                    )
                    for item in sorted(
                        expected_selected,
                        key=lambda item: str(item.get("id", "")),
                    )
                )
            ).encode("utf-8")
        ).hexdigest()
        selected_frame = transaction_frame[
            transaction_frame["ID"].astype(str).isin(selected_ids)
        ]
        st.download_button(
            "Export selected",
            frame_csv(selected_frame),
            file_name=f"tabula-rasa-selected-{date.today()}.csv",
            mime="text/csv",
            width="stretch",
            key=(
                "transaction_bulk_export_"
                f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
            ),
        )
        _render_bulk_editor(
            context,
            categories=categories,
            category_paths=category_paths,
            payees=payees,
            tags=tags,
            expected_selected=expected_selected,
            selected_ids=selected_ids,
            selected_protected=selected_protected,
            selected_snapshot_key=selected_snapshot_key,
        )

        total_amount = sum(abs(float(item["amount"])) for item in expected_selected)
        st.warning(
            f"Review: permanently delete {len(selected_ids)} transaction(s) "
            f"totaling {money(total_amount)}. Linked receipt references will be "
            "removed, but the Google Drive files will remain in Drive as unreferenced files."
        )
        confirm_delete = st.checkbox(
            "I understand these transactions will be permanently deleted and cannot be undone",
            key=(
                "transaction_bulk_confirm_delete_"
                f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}_"
                f"{selected_snapshot_key}"
            ),
        )
        with st.container(key="destructive_transaction_bulk_delete"):
            with st.form("transaction_bulk_delete", clear_on_submit=False):
                delete_error = st.empty()
                delete_requested = st.form_submit_button(
                    "Permanently delete selected",
                    icon=":material/delete_forever:",
                    type="primary",
                    width="stretch",
                )
        if delete_requested and selected_protected:
            delete_error.error(
                "Bulk deletion is disabled because the selection includes "
                "a mixed-use projection or depreciation entry. Manage it from Mixed-use expenses or Assets."
            )
        elif delete_requested and schedule_status_error is not None:
            delete_error.error(
                "Refresh the recurring schedule status before deleting this selection."
            )
        elif delete_requested:
            if not confirm_delete:
                delete_error.error(
                    "Confirm the permanent deletion before continuing."
                )
            else:
                def clear_recovery() -> None:
                    for item in selected_ids:
                        clear_receipt_creation_recovery(context, item)

                context.confirmed_write(
                    "bulk_delete_transactions",
                    {"ids": list(selected_ids), "expected": expected_selected},
                    lambda: context.services.transactions.bulk_delete(
                        selected_ids,
                        expected=expected_selected,
                    ),
                    lambda result: (
                        f"Permanently deleted {result['count']} transactions; "
                        "linked Drive files were retained."
                    ),
                    on_success=clear_recovery,
                    report_error=delete_error.error,
                )
    else:
        st.info("Select one or more visible transactions to use Bulk actions.")
