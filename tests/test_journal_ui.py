from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import streamlit as st

from tabula_rasa.page_renderers.transactions.entry_creation import (
    JOURNAL_MODE,
    SIMPLE_MODE,
    _cancel_entry_mode_switch,
    _confirm_entry_mode_switch,
    _record_draft_state,
    _request_entry_mode,
)
from tabula_rasa.page_renderers.transactions.journal_editor import (
    _journal_edit_baseline,
    _line_target_options,
    _journal_target_options,
    _remove_line,
    journal_totals,
)
from tabula_rasa.presentation import reset_profile_presentation_state
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook


def _key(name: str) -> str:
    return f"entry_creation_{name}_north"


def test_dirty_mode_request_waits_for_confirmation_and_preserves_fields() -> None:
    state = {
        _key("active_mode"): SIMPLE_MODE,
        _key("requested_mode"): JOURNAL_MODE,
        _key("simple_dirty"): True,
        "add_transaction_amount": 125.0,
        "add_transaction_date": date(2026, 9, 20),
        "add_transaction_description": "Shared memo",
    }

    with patch.object(st, "session_state", state):
        _request_entry_mode("north")

    assert state[_key("active_mode")] == SIMPLE_MODE
    assert state[_key("requested_mode")] == SIMPLE_MODE
    assert state[_key("pending_mode")] == JOURNAL_MODE
    assert state["add_transaction_amount"] == 125.0

    with patch.object(st, "session_state", state):
        _confirm_entry_mode_switch("north")

    assert state[_key("active_mode")] == JOURNAL_MODE
    assert state[_key("requested_mode")] == JOURNAL_MODE
    assert _key("pending_mode") not in state
    assert "add_transaction_amount" not in state
    assert state["add_transaction_date"] == date(2026, 9, 20)
    assert state["add_transaction_description"] == "Shared memo"


def test_clean_mode_request_switches_immediately() -> None:
    state = {
        _key("active_mode"): SIMPLE_MODE,
        _key("requested_mode"): JOURNAL_MODE,
        _key("simple_dirty"): False,
        "add_transaction_amount": 0.0,
    }

    with patch.object(st, "session_state", state):
        _request_entry_mode("north")

    assert state[_key("active_mode")] == JOURNAL_MODE
    assert state[_key("requested_mode")] == JOURNAL_MODE
    assert "add_transaction_amount" not in state


def test_cancel_mode_switch_keeps_dirty_editor() -> None:
    state = {
        _key("active_mode"): SIMPLE_MODE,
        _key("requested_mode"): SIMPLE_MODE,
        _key("pending_mode"): JOURNAL_MODE,
        "add_transaction_amount": 90.0,
    }

    with patch.object(st, "session_state", state):
        _cancel_entry_mode_switch("north")

    assert state[_key("active_mode")] == SIMPLE_MODE
    assert state[_key("requested_mode")] == SIMPLE_MODE
    assert _key("pending_mode") not in state
    assert state["add_transaction_amount"] == 90.0


def test_pending_recurring_save_blocks_mode_switch() -> None:
    state = {
        _key("active_mode"): SIMPLE_MODE,
        _key("requested_mode"): JOURNAL_MODE,
        _key("simple_dirty"): True,
        _key("simple_switch_blocked"): True,
    }

    with patch.object(st, "session_state", state):
        _request_entry_mode("north")

    assert state[_key("requested_mode")] == SIMPLE_MODE
    assert _key("pending_mode") not in state
    assert "pending recurring transaction" in str(state[_key("switch_notice")])


def test_draft_dirty_state_returns_to_clean_when_values_match_baseline() -> None:
    state: dict[str, object] = {}
    with patch.object(st, "session_state", state):
        _record_draft_state(state, "north", SIMPLE_MODE, {"amount": 0})
        assert state[_key("simple_dirty")] is False
        _record_draft_state(state, "north", SIMPLE_MODE, {"amount": 10})
        assert state[_key("simple_dirty")] is True
        _record_draft_state(state, "north", SIMPLE_MODE, {"amount": 0})
        assert state[_key("simple_dirty")] is False


def test_journal_totals_and_typed_target_options() -> None:
    debits, credits = journal_totals(
        [
            {"debit": "100.005", "credit": 0},
            {"debit": 0, "credit": "100.005"},
        ]
    )
    assert debits == credits == Decimal("100.00")

    options, labels = _journal_target_options(
        [
            {
                "id": "checking",
                "name": "Checking",
                "classification": "Asset",
                "active": True,
            },
            {
                "id": "old",
                "name": "Old account",
                "classification": "Asset",
                "active": False,
            },
        ],
        [{"id": "office", "name": "Office", "kind": "Expense"}],
        {"checking": "Checking", "old": "Old account"},
        {"office": "Office"},
    )
    assert options == ["account:checking", "category:office"]
    assert labels["account:checking"] == "Checking · Asset account"
    assert labels["category:office"] == "Office · Expense category"

    edit_options, edit_labels = _journal_target_options(
        [
            {
                "id": "checking",
                "name": "Checking",
                "classification": "Asset",
                "active": True,
            },
            {
                "id": "old",
                "name": "Old account",
                "classification": "Asset",
                "active": False,
            },
            {
                "id": "other-old",
                "name": "Other old account",
                "classification": "Asset",
                "active": False,
            },
        ],
        [],
        {
            "checking": "Checking",
            "old": "Old account",
            "other-old": "Other old account",
        },
        {},
        retained_tokens={"account:old"},
    )
    assert edit_options == ["account:checking", "account:old"]
    assert edit_labels["account:old"].endswith(" · inactive")


def test_journal_line_target_options_do_not_leak_retained_targets() -> None:
    options = ["account:active"]
    labels = {"account:active": "Active"}

    first_options, first_labels = _line_target_options(
        options, labels, "account:old"
    )
    second_options, second_labels = _line_target_options(
        options, labels, "account:other-old"
    )

    assert first_options == ["account:active", "account:old"]
    assert first_labels["account:old"] == "account:old · unavailable"
    assert second_options == ["account:active", "account:other-old"]
    assert second_labels["account:other-old"] == "account:other-old · unavailable"
    assert "account:old" not in second_options
    assert options == ["account:active"]
    assert labels == {"account:active": "Active"}


def test_journal_edit_baseline_survives_external_refresh_and_resets_for_config() -> None:
    original = {
        "id": "entry-1",
        "txn_date": "2026-09-01",
        "description": "Original",
        "postings": [
            {
                "id": "line-1",
                "target_type": "account",
                "target_id": "checking",
                "side": "Debit",
                "amount": "10.00",
            }
        ],
    }
    externally_changed = {
        **original,
        "txn_date": "2026-09-02",
        "description": "External edit",
        "postings": [{**original["postings"][0], "amount": "20.00"}],
    }
    state: dict[str, object] = {}

    baseline = _journal_edit_baseline(
        state,
        profile_key="north",
        configuration_revision="sheet-a",
        entry=original,
    )
    original["postings"][0]["amount"] = "99.00"
    refreshed_baseline = _journal_edit_baseline(
        state,
        profile_key="north",
        configuration_revision="sheet-a",
        entry=externally_changed,
    )

    assert baseline["description"] == "Original"
    assert refreshed_baseline["txn_date"] == "2026-09-01"
    assert refreshed_baseline["postings"][0]["amount"] == "10.00"

    state["journal_edit_north_entry-1_date"] = date(2026, 9, 3)
    replaced = _journal_edit_baseline(
        state,
        profile_key="north",
        configuration_revision="sheet-b",
        entry=externally_changed,
    )
    assert replaced["description"] == "External edit"
    assert replaced["postings"][0]["amount"] == "20.00"
    assert "journal_edit_north_entry-1_date" not in state


def test_profile_switch_clears_journal_creation_and_edit_widgets() -> None:
    state = {
        _key("active_mode"): JOURNAL_MODE,
        _key("requested_mode"): JOURNAL_MODE,
        _key("journal_dirty"): True,
        _key("simple_raw_baseline"): (("add_transaction_amount", 0.0),),
        _key("journal_raw_baseline"): (
            ("journal_create_north_0_line-1_debit", 0.0),
        ),
        "journal_create_north_0_line-1_debit": 50,
        "journal_create_generation_north": 2,
        "journal_edit_north_entry-1_line-1_credit": 50,
        "journal_edit_line_ids_entry-1_north": ["line-1", "line-2"],
        "journal_create_south_0_line-1_debit": 25,
    }

    reset_profile_presentation_state(
        state,
        previous_profile_key="north",
        selected_profile_key="south",
    )

    assert not any(
        key.endswith("_north") or key.startswith("journal_create_north_")
        for key in state
    )
    assert state["journal_create_south_0_line-1_debit"] == 25


def test_entry_type_switch_requires_confirmation_in_apptest() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        entry_type = by_label(app.segmented_control, "Entry Type")
        assert entry_type.value == SIMPLE_MODE

        by_label(app.number_input, "Amount").set_value(25).run()
        by_label(app.segmented_control, "Entry Type").set_value(JOURNAL_MODE).run()

        assert by_label(app.segmented_control, "Entry Type").value == SIMPLE_MODE
        assert by_label(app.number_input, "Amount").value == 25
        assert any(
            str(button.label).startswith("Discard and switch")
            for button in app.button
        )

        by_label(app.button, "Keep editing").click().run()
        assert by_label(app.segmented_control, "Entry Type").value == SIMPLE_MODE
        assert by_label(app.number_input, "Amount").value == 25


def test_balanced_journal_creation_starts_with_two_rows_and_saves() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Entry Type").set_value(JOURNAL_MODE).run()

        account_fields = [
            item
            for item in app.selectbox
            if item.label == "Account"
            and str(item.key).startswith("journal_create_")
        ]
        debit_fields = [
            item for item in app.number_input if item.label == "Debit"
        ]
        credit_fields = [
            item for item in app.number_input if item.label == "Credit"
        ]
        assert len(account_fields) == len(debit_fields) == len(credit_fields) == 2
        assert by_label(app.button, "Save journal entry").disabled

        account_fields[0].set_value(f"account:{account['id']}").run()
        account_fields = [
            item
            for item in app.selectbox
            if item.label == "Account"
            and str(item.key).startswith("journal_create_")
        ]
        account_fields[1].set_value(f"category:{category['id']}").run()
        debit_fields = [item for item in app.number_input if item.label == "Debit"]
        debit_fields[0].set_value(40).run()
        credit_fields = [item for item in app.number_input if item.label == "Credit"]
        credit_fields[1].set_value(40).run()

        assert not by_label(app.button, "Save journal entry").disabled
        by_label(app.button, "Save journal entry").click().run()

    entries = storage.list_journal_entries()
    assert len(entries) == 1
    assert entries[0]["total_debits"] == entries[0]["total_credits"] == "40.00"
    assert len(entries[0]["postings"]) == 2


def test_journal_rows_add_and_remove_explicitly_with_two_row_minimum() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Entry Type").set_value(JOURNAL_MODE).run()

        journal_remove_buttons = [
            button
            for button in app.button
            if button.label == "Remove"
            and str(button.key).startswith("journal_create_")
        ]
        assert len(journal_remove_buttons) == 2
        assert all(button.disabled for button in journal_remove_buttons)

        by_label(app.button, "+ Add line").click().run()
        journal_remove_buttons = [
            button
            for button in app.button
            if button.label == "Remove"
            and str(button.key).startswith("journal_create_")
        ]
        assert len(journal_remove_buttons) == 3
        assert not any(button.disabled for button in journal_remove_buttons)

        journal_remove_buttons[-1].click().run()
        journal_remove_buttons = [
            button
            for button in app.button
            if button.label == "Remove"
            and str(button.key).startswith("journal_create_")
        ]
        assert len(journal_remove_buttons) == 2
        assert all(button.disabled for button in journal_remove_buttons)


def test_removing_populated_middle_row_preserves_sibling_identity_and_values() -> None:
    line_ids_key = "journal_create_line_ids_0_north"
    prefix = "journal_create_north_0"
    state = {
        line_ids_key: ["line-1", "line-2", "line-3"],
        f"{prefix}_line-1_target": "account:checking",
        f"{prefix}_line-1_debit": 25.0,
        f"{prefix}_line-2_target": "category:meals",
        f"{prefix}_line-2_debit": 10.0,
        f"{prefix}_line-2_description": "Remove me",
        f"{prefix}_line-3_target": "account:savings",
        f"{prefix}_line-3_credit": 35.0,
        f"{prefix}_line-3_description": "Keep me",
    }

    with patch.object(st, "session_state", state):
        _remove_line("north", "create", "0", "line-2")

    assert state[line_ids_key] == ["line-1", "line-3"]
    assert state[f"{prefix}_line-1_debit"] == 25.0
    assert state[f"{prefix}_line-3_credit"] == 35.0
    assert state[f"{prefix}_line-3_description"] == "Keep me"
    assert not any("line-2" in key for key in state if key != line_ids_key)


def test_unbalanced_journal_shows_running_totals_and_keeps_save_disabled() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Entry Type").set_value(JOURNAL_MODE).run()
        account_fields = [
            item
            for item in app.selectbox
            if item.label == "Account"
            and str(item.key).startswith("journal_create_")
        ]
        account_fields[0].set_value(f"account:{account['id']}").run()
        debit_fields = [item for item in app.number_input if item.label == "Debit"]
        debit_fields[0].set_value(12).run()

        metrics = {metric.label: str(metric.value) for metric in app.metric}
        assert metrics["Total Debits"] == "$12.00"
        assert metrics["Total Credits"] == "$0.00"
        assert metrics["Difference"] == "$12.00"
        assert by_label(app.button, "Save journal entry").disabled
        assert any(
            "requires one debit or credit amount" in str(message.value)
            or "at least two complete postings" in str(message.value)
            for message in app.info
        )
