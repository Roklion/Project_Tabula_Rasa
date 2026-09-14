from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import Mock

from tabula_rasa.page_renderers.transactions.recurring import (
    _active_or_selected,
    _clear_pending_schedule_state,
    _mark_workbook_data_changed,
    _recurring_category_options,
    _recurring_payee_options,
    _safe_date,
    _safe_interval,
    _selected_tag_ids,
)
from tabula_rasa.page_renderers.transactions.recurrence_controls import (
    restore_recurrence_controls,
)


def test_recurring_editor_uses_safe_defaults_for_corrupt_schedule_fields() -> None:
    assert _safe_interval("not-a-number") == 1
    assert _safe_interval("0") == 1
    assert _safe_date("not-a-date", date(2026, 9, 11)) == date(2026, 9, 11)
    assert _safe_date("") is None


def test_recurring_change_marker_is_optional() -> None:
    context = object()
    _mark_workbook_data_changed(context)

    callback = Mock()
    _mark_workbook_data_changed(SimpleNamespace(mark_workbook_data_changed=callback))

    callback.assert_called_once_with()


def test_restore_recurrence_controls_preserves_pending_edit_payload() -> None:
    state: dict[str, object] = {}

    restore_recurrence_controls(
        state,
        {
            "name": "Monthly rent",
            "recurrence_unit": "month",
            "recurrence_interval": 1,
            "end_date": None,
        },
        key_prefix="mixed",
        key_suffix="north_source",
    )

    assert state == {
        "mixed_recurring_north_source": True,
        "mixed_recurrence_unit_north_source": "month",
        "mixed_recurrence_interval_north_source": 1,
        "mixed_recurrence_name_north_source": "Monthly rent",
        "mixed_recurrence_end_north_source": None,
    }


def test_ending_schedule_clears_only_matching_pending_retry_state() -> None:
    state = {
        "recurring_edit_pending_schedule_id_expense_profile_shop": "ended",
        "mixed_use_edit_pending_schedule_id_source_profile_shop": "ended",
        "mixed_use_edit_pending_payload_source_profile_shop": {"schedule_id": "ended"},
        "recurring_edit_pending_schedule_id_shop_expense_profile_north_shop": "ended",
        "mixed_use_edit_pending_schedule_id_shop_source_profile_north_shop": "ended",
        "mixed_use_edit_pending_schedule_id_source_profile_north_profile_shop": "other",
        "mixed_use_edit_pending_payload_source_profile_north_profile_shop": {
            "schedule_id": "ended"
        },
        "recurring_pending_schedule_id_shop": "ended",
        "recurring_pending_transaction_id_shop": "transaction",
        "recurring_pending_payload_shop": {"amount": "10"},
        "recurring_pending_schedule_id_north_shop": "other-ended",
        "recurring_pending_transaction_id_north_shop": "other-transaction",
        "recurring_pending_payload_north_shop": {"amount": "20"},
        "mixed_use_pending_schedule_id_shop": "ended",
        "mixed_use_pending_source_id_shop": "other-source",
        "mixed_use_pending_payload_shop": {"total_expense": "30"},
        "mixed_use_pending_schedule_id_north_shop": "other-ended",
        "mixed_use_pending_source_id_north_shop": "other-source",
        "mixed_use_pending_payload_north_shop": {"total_expense": "40"},
        "recurring_edit_pending_schedule_id_other_profile_shop": "keep",
        "unrelated": "ended",
    }

    _clear_pending_schedule_state(state, "shop", "ended")

    assert "recurring_edit_pending_schedule_id_expense_profile_shop" not in state
    assert "mixed_use_edit_pending_schedule_id_source_profile_shop" not in state
    assert "mixed_use_edit_pending_payload_source_profile_shop" not in state
    assert state["recurring_edit_pending_schedule_id_shop_expense_profile_north_shop"] == "ended"
    assert state["mixed_use_edit_pending_schedule_id_shop_source_profile_north_shop"] == "ended"
    assert state["mixed_use_edit_pending_schedule_id_source_profile_north_profile_shop"] == "other"
    assert state["mixed_use_edit_pending_payload_source_profile_north_profile_shop"]["schedule_id"] == "ended"
    assert "recurring_pending_schedule_id_shop" not in state
    assert "recurring_pending_transaction_id_shop" not in state
    assert "recurring_pending_payload_shop" not in state
    assert state["recurring_pending_schedule_id_north_shop"] == "other-ended"
    assert state["recurring_pending_transaction_id_north_shop"] == "other-transaction"
    assert state["recurring_pending_payload_north_shop"] == {"amount": "20"}
    assert "mixed_use_pending_schedule_id_shop" not in state
    assert "mixed_use_pending_source_id_shop" not in state
    assert "mixed_use_pending_payload_shop" not in state
    assert state["mixed_use_pending_schedule_id_north_shop"] == "other-ended"
    assert "mixed_use_pending_source_id_north_shop" in state
    assert "mixed_use_pending_payload_north_shop" in state
    assert state["recurring_edit_pending_schedule_id_other_profile_shop"] == "keep"
    assert state["unrelated"] == "ended"


def test_recurring_editor_filters_inactive_categories_but_preserves_selection() -> None:
    categories = [
        {"id": "active", "kind": "Expense", "active": "TRUE"},
        {"id": "inactive", "kind": "Expense", "active": "FALSE"},
        {"id": "income", "kind": "Income", "active": "TRUE"},
    ]

    assert [item["id"] for item in _recurring_category_options(categories, "active")] == ["active"]
    assert [item["id"] for item in _recurring_category_options(categories, "inactive")] == [
        "active", "inactive"
    ]

    categories_without_active_state = [
        {"id": "office", "kind": "Expense"},
        {"id": "sales", "kind": "Income"},
    ]
    assert [
        item["id"]
        for item in _recurring_category_options(categories_without_active_state, "")
    ] == ["office"]


def test_recurring_category_options_follow_category_hierarchy_order() -> None:
    categories = [
        {"id": "child", "name": "Child", "kind": "Expense", "parent_id": "parent"},
        {"id": "other", "name": "Other", "kind": "Expense", "parent_id": ""},
        {"id": "parent", "name": "Parent", "kind": "Expense", "parent_id": ""},
    ]

    assert [item["id"] for item in _recurring_category_options(categories, "")] == [
        "other",
        "parent",
        "child",
    ]


def test_recurring_editor_filters_inactive_references_but_preserves_selection() -> None:
    items = [
        {"id": "active", "active": "TRUE"},
        {"id": "inactive", "active": "FALSE"},
    ]

    assert [item["id"] for item in _active_or_selected(items, ["inactive"])] == [
        "active", "inactive"
    ]


def test_recurring_editor_keeps_missing_payee_visible_for_repair() -> None:
    options = _recurring_payee_options(
        [{"id": "active", "name": "Active", "active": "TRUE"}],
        "deleted-payee",
    )

    assert options[-1] == {
        "id": "deleted-payee",
        "name": "Missing (deleted-payee)",
    }


def test_recurring_editor_treats_nonlist_tag_ids_as_empty() -> None:
    assert _selected_tag_ids(json.dumps({"unexpected": "shape"})) == []
