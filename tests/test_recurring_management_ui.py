from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


def test_schedule_row_selection_controls_edit_target_and_future_template() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    for schedule_id, name in (("schedule-a", "Alpha"), ("schedule-b", "Beta")):
        storage.create_recurring_expense(
            schedule_id=schedule_id,
            name=name,
            txn_date="2026-09-25",
            recurrence_unit="month",
            recurrence_interval=1,
            amount="10",
            account_id=account["id"],
            category_id=category["id"],
        )
    original_occurrences = storage.list_transactions()

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        assert not any(item.label == "Schedule" for item in app.selectbox)
        assert not any(item.label == "Edit schedule template" for item in app.expander)

        app.session_state["recurring_schedule_test_selected_id"] = "schedule-a"
        app.run()
        by_label(app.button, "Edit").click().run()
        editor = next(item for item in app.expander if item.label == "Edit schedule template")
        assert by_label(editor.text_input, "Schedule name").value == "Alpha"

        app.session_state["recurring_schedule_test_selected_id"] = "schedule-b"
        app.run()
        assert not any(item.label == "Edit schedule template" for item in app.expander)
        by_label(app.button, "Edit").click().run()
        editor = next(item for item in app.expander if item.label == "Edit schedule template")
        assert by_label(editor.text_input, "Schedule name").value == "Beta"
        by_label(editor.text_input, "Schedule name").set_value("Beta revised")
        by_label(editor.button, "Save schedule template").click().run()

    schedules = {item["id"]: item for item in storage.list_recurring_schedules()}
    assert schedules["schedule-a"]["name"] == "Alpha"
    assert schedules["schedule-b"]["name"] == "Beta revised"
    assert storage.list_transactions() == original_occurrences
