from __future__ import annotations

from unittest.mock import patch

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.app_support import profile_config
from tests.fakes import FakeWorkbook
from tabula_rasa.page_renderers.transactions.transaction_form import (
    transaction_payload_from_draft,
)
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError


def test_add_transaction_can_create_inline_payee() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.number_input, "Amount").set_value(25).run()
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "Category").set_value("Office").run()
        payee_selector = by_label(app.selectbox, "Payee / customer")
        # AppTest cannot type into Streamlit's accepted custom selectbox value;
        # append the submitted display value to its test representation.
        payee_selector.options.append("New vendor")
        payee_selector.set_value("New vendor").run()
        by_label(app.selectbox, "Payee / customer").options.append("New vendor")
        by_label(app.button, "Save transaction").click().run()

    transaction = storage.list_transactions()[0]
    assert transaction["payee"] == "New vendor"
    assert transaction["payee_id"] == storage.list_payees()[0]["id"]


def test_recurring_control_is_expense_only() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Services", "Income")
    expense_category = storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        assert any(item.label == "Repeat this Expense" for item in app.checkbox)

        by_label(app.segmented_control, "Transaction type").set_value("Income").run()
        assert not any(item.label == "Repeat this Expense" for item in app.checkbox)

        by_label(app.segmented_control, "Transaction type").set_value("Transfer").run()
        assert not any(item.label == "Repeat this Expense" for item in app.checkbox)

        app.session_state["add_transaction_category_expense"] = "Office"
        by_label(app.segmented_control, "Transaction type").set_value("Expense").run()
        assert by_label(app.selectbox, "Category").value == expense_category["id"]


def test_pending_expense_retry_does_not_block_income_submission() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Salary", "Income")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["recurring_pending_schedule_id_test"] = "pending"
        by_label(app.segmented_control, "Transaction type").set_value("Income").run()
        by_label(app.number_input, "Amount").set_value(100).run()
        by_label(app.button, "Save transaction").click().run()

    transactions = storage.list_transactions()
    assert len(transactions) == 1
    assert transactions[0]["kind"] == "Income"


def test_add_expense_recurring_flow_creates_initial_occurrence_and_schedule() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with patch.object(
        storage,
        "create_recurring_expense",
        wraps=storage.create_recurring_expense,
    ) as create_recurring:
        with authenticated_app(storage) as app:
            navigate_to(app, "Transactions")
            by_label(app.number_input, "Amount").set_value(42).run()
            by_label(app.selectbox, "From Account").set_value("Checking").run()
            by_label(app.selectbox, "Category").set_value("Office").run()
            by_label(app.checkbox, "Repeat this Expense").set_value(True).run()
            assert by_label(app.selectbox, "Repeat every").value == "month"
            assert by_label(app.number_input, "Interval").value == 1
            by_label(app.text_input, "Schedule name").set_value("Monthly office").run()
            by_label(app.button, "Save transaction").click().run()

    schedules = storage.list_recurring_schedules()
    transactions = storage.list_transactions()
    assert len(schedules) == 1
    assert schedules[0]["name"] == "Monthly office"
    assert len(transactions) == 1
    assert transactions[0]["recurring_schedule_id"] == schedules[0]["id"]
    assert transactions[0]["receipt_references"] == "[]"
    assert create_recurring.call_args.kwargs["transaction_id"] == transactions[0]["id"]


def test_edit_expense_can_create_schedule_from_existing_transaction() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Office supplier")
    transaction = storage.create_transaction(
        txn_date="2026-09-01", kind="Expense", amount="20",
        account_id=account["id"], category_id=category["id"],
        payee_id=payee["id"], description="Office supplies",
    )

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        editor = next(item for item in app.expander if item.label == "Edit transaction")
        by_label(editor.checkbox, "Repeat this Expense").set_value(True).run()
        editor = next(item for item in app.expander if item.label == "Edit transaction")
        assert by_label(editor.selectbox, "Repeat every").value == "month"
        assert by_label(editor.number_input, "Interval").value == 1
        by_label(editor.text_input, "Schedule name").set_value("Monthly supplies").run()
        editor = next(item for item in app.expander if item.label == "Edit transaction")
        by_label(editor.number_input, "Amount").set_value(25).run()
        editor = next(item for item in app.expander if item.label == "Edit transaction")
        original_empty = DeltaGenerator.empty
        root_container = st.empty.__self__
        cleared_slots = []

        def record_empty(generator):
            if generator is not root_container:
                cleared_slots.append(generator)
            return original_empty(generator)

        with patch.object(DeltaGenerator, "empty", record_empty):
            by_label(editor.button, "Save changes").click().run()
        assert len(cleared_slots) == 1
        editor = next(item for item in app.expander if item.label == "Edit transaction")
        assert not any(item.label == "Repeat this Expense" for item in editor.checkbox)
        assert not any(item.label == "Edit schedule template" for item in app.expander)
        schedule_id = storage.list_recurring_schedules()[0]["id"]
        app.session_state["recurring_schedule_test_selected_id"] = schedule_id
        app.run()
        by_label(app.button, "Edit").click().run()
        assert any(item.label == "Edit schedule template" for item in app.expander)

    schedules = storage.list_recurring_schedules()
    transactions = storage.list_transactions()
    assert len(schedules) == len(transactions) == 1
    assert transactions[0]["id"] == transaction["id"]
    assert transactions[0]["amount"] == "25.00"
    assert transactions[0]["payee_id"] == payee["id"]
    assert transactions[0]["recurring_schedule_id"] == schedules[0]["id"]
    assert schedules[0]["name"] == "Monthly supplies"
    assert schedules[0]["payee_id"] == payee["id"]


def test_invalid_recurring_submission_does_not_leave_pending_retry_state() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.checkbox, "Repeat this Expense").set_value(True).run()
        by_label(app.selectbox, "Repeat every").set_value("day").run()
        by_label(app.button, "Save transaction").click().run()

        assert by_label(app.selectbox, "Repeat every").value == "day"

        assert "recurring_pending_schedule_id_test" not in app.session_state
        assert "recurring_pending_transaction_id_test" not in app.session_state
        assert "recurring_pending_payload_test" not in app.session_state


def test_transaction_payload_from_draft_is_canonical() -> None:
    draft = {
        "txn_date": "2026-09-14",
        "kind": "Expense",
        "amount": 25,
        "account_id": "checking",
        "to_account_id": "",
        "category_id": "office",
        "payee_id": "vendor",
        "new_payee_name": "",
        "tag_ids": ["tax"],
        "new_tag_name": None,
        "reference": "INV-25",
        "description": "Draft description",
    }

    payload = transaction_payload_from_draft(
        draft,
        description="Saved description",
    )

    assert payload == {
        **draft,
        "new_tag_name": "",
        "description": "Saved description",
    }


def test_startup_reconciles_once_per_profile_and_keeps_profiles_isolated() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None),
    }
    profiles = {
        "alpha": profile_config(name="Alpha", spreadsheet_id="alpha-sheet"),
        "beta": profile_config(name="Beta", spreadsheet_id="beta-sheet"),
    }
    calls: list[GoogleSheetsStorage] = []
    from tabula_rasa.application import RecurringService
    original = RecurringService.reconcile

    def record_reconcile(service, *args, **kwargs):
        calls.append(service._repository._storage)
        return original(service, *args, **kwargs)

    with patch.object(
        RecurringService,
        "reconcile",
        autospec=True,
        side_effect=record_reconcile,
    ):
        with authenticated_app(storages=storages, profiles=profiles) as app:
            assert calls == [storages["alpha-sheet"]]
            app.run()
            assert calls == [storages["alpha-sheet"]]
            by_label(app.selectbox, "Business").set_value("beta").run()
            assert calls == [storages["alpha-sheet"], storages["beta-sheet"]]
            app.run()
            assert calls == [storages["alpha-sheet"], storages["beta-sheet"]]


def test_startup_reconciliation_failure_does_not_block_transactions_page() -> None:
    from tabula_rasa.application import RecurringService
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    with patch.object(
        RecurringService,
        "reconcile",
        side_effect=StorageUnavailableError("temporary Sheets outage"),
    ):
        with authenticated_app(storage) as app:
            assert any("Automatic recurring schedule reconciliation failed" in item.value for item in app.warning)
            navigate_to(app, "Transactions")

            assert any(item.label == "Save transaction" for item in app.button)
