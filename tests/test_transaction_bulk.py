from __future__ import annotations

from unittest.mock import patch

from tabula_rasa.page_renderers.transactions.ledger import (
    _change_ledger_mode,
    _selection_ids,
)
from tabula_rasa.page_renderers.transactions.ledger_bulk import (
    MIXED_FIELD_VALUE,
    _bulk_payee_names,
    _shared_bulk_value,
)


def test_bulk_selection_maps_visible_rows_to_stable_ids_only() -> None:
    assert _selection_ids(["newest", "middle", "oldest"], [2, 0, 99]) == (
        "oldest",
        "newest",
    )


def test_mode_change_clears_selection_and_incompatible_edit_state() -> None:
    session_state = {
        "transaction_bulk_selected_ids_north": ("txn-1", "txn-2"),
        "transaction_bulk_selection_generation": 4,
        "edit_transaction_id": "txn-1",
    }
    with patch(
        "tabula_rasa.page_renderers.transactions.ledger.st.session_state",
        session_state,
    ):
        _change_ledger_mode("north")

    assert session_state["transaction_bulk_selected_ids_north"] == ()
    assert session_state["transaction_bulk_selection_generation"] == 5
    assert session_state["transaction_ledger_mode_generation"] == 1
    assert "edit_transaction_id" not in session_state


def test_bulk_editor_common_value_distinguishes_shared_and_mixed_values() -> None:
    assert _shared_bulk_value(["category-a", "category-a"]) == "category-a"
    assert _shared_bulk_value(["category-a", "category-b"]) == MIXED_FIELD_VALUE
    assert _shared_bulk_value([(), ()]) == ()
    assert _shared_bulk_value([(), ("tag-a",)]) == MIXED_FIELD_VALUE


def test_bulk_editor_includes_selected_inactive_payees_after_id_normalization() -> None:
    assert _bulk_payee_names(
        [
            {"id": "  inactive-payee  ", "name": "Inactive", "active": "FALSE"},
            {"id": "active-payee", "name": "Active", "active": "TRUE"},
            {"id": "other-payee", "name": "Other", "active": "FALSE"},
        ],
        [" inactive-payee "],
    ) == {
        "inactive-payee": "Inactive",
        "active-payee": "Active",
    }
