"""Approved bulk transaction actions and safeguards."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
import hashlib
import streamlit as st
from tabula_rasa.ledger_presentation import money
from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from .ledger_filters import _bulk_selection_key, transaction_is_mixed_use
from .receipt_workflows import clear_receipt_creation_recovery

def render_bulk_actions(
    context: TransactionsContext,
    *,
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
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
        if any(transaction_is_mixed_use(item) for item in expected_selected):
            st.error(
                "This selection includes a mixed-use projection. Bulk "
                "category changes and deletion are disabled; manage it "
                "from the Mixed-use expenses tab."
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
            selected_frame.to_csv(index=False).encode("utf-8"),
            file_name=f"tabula-rasa-selected-{date.today()}.csv",
            mime="text/csv",
            width="stretch",
            key=(
                "transaction_bulk_export_"
                f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
            ),
        )
        selected_kinds = {item["kind"] for item in expected_selected}
        category_eligible = selected_kinds in ({"Income"}, {"Expense"})
        if selected_protected:
            st.info(
                "Change category is disabled for selections containing a "
                "mixed-use projection."
            )
        elif not category_eligible:
            st.info(
                "Change category is disabled because Bulk category changes require "
                "a homogeneous Income or Expense selection; transfers are not eligible."
            )
        else:
            common_kind = next(iter(selected_kinds))
            category_map = {}
            for category in categories:
                if category["kind"] != common_kind:
                    continue
                category_id = str(category.get("id") or "").strip()
                if category_id in category_paths:
                    category_map[category_paths[category_id]] = category_id
            if not category_map:
                st.info(f"No categories of type {common_kind.lower()} are available.")
            else:
                with st.form(
                    "transaction_bulk_category",
                    clear_on_submit=False,
                ):
                    selected_category_name = st.selectbox(
                        "New category",
                        list(category_map),
                        key=(
                            "transaction_bulk_category_"
                            f"{context.profile_key}_{st.session_state.get('transaction_bulk_selection_generation', 0)}"
                        ),
                    )
                    target_category_id = category_map[selected_category_name]
                    st.caption(
                        f"Review: change category for {len(selected_ids)} {common_kind.lower()} transaction(s)."
                    )
                    category_error = st.empty()
                    category_requested = st.form_submit_button(
                        "Change category",
                        type="primary",
                        width="stretch",
                    )
                if category_requested:
                    context.confirmed_write(
                        "bulk_change_transaction_category",
                        {
                            "ids": list(selected_ids),
                            "expected": expected_selected,
                            "category_id": target_category_id,
                        },
                        lambda: context.storage.bulk_change_transaction_category(
                            selected_ids,
                            expected_transactions=expected_selected,
                            category_id=target_category_id,
                        ),
                        lambda result: f"Category updated for {result['count']} transactions.",
                        report_error=category_error.error,
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
                "a mixed-use projection. Manage it from the Mixed-use expenses tab."
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
                    lambda: context.storage.bulk_delete_transactions(
                        selected_ids,
                        expected_transactions=expected_selected,
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
