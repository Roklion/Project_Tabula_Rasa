from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from tabula_rasa.page_renderers.transactions.recurring import (
    _active_or_selected,
    _mark_workbook_data_changed,
    _recurring_category_options,
    _safe_date,
    _safe_interval,
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


def test_recurring_editor_filters_inactive_references_but_preserves_selection() -> None:
    items = [
        {"id": "active", "active": "TRUE"},
        {"id": "inactive", "active": "FALSE"},
    ]

    assert [item["id"] for item in _active_or_selected(items, ["inactive"])] == [
        "active", "inactive"
    ]
