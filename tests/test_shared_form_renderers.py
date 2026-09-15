from __future__ import annotations

from tabula_rasa.address_autocomplete import AddressSelection
from tabula_rasa.page_renderers.mileage_form_shared import (
    mileage_widget_key,
    validate_mileage_draft,
)
from tabula_rasa.page_renderers.transactions.transaction_form import (
    transaction_widget_key,
    validate_transaction_draft,
)


def test_shared_widget_keys_are_record_scoped() -> None:
    assert transaction_widget_key("edit_transaction", "amount", "north-row") != (
        transaction_widget_key("edit_transaction", "amount", "south-row")
    )
    assert mileage_widget_key("edit_mileage_trip", "miles", "north-row") != (
        mileage_widget_key("edit_mileage_trip", "miles", "south-row")
    )
    assert transaction_widget_key("add_transaction", "category_expense") != (
        transaction_widget_key("add_transaction", "category_income")
    )
    assert transaction_widget_key("add_transaction", "account_expense") != (
        transaction_widget_key("add_transaction", "account_income")
    )


def test_transaction_common_validation_rejects_invalid_transfer() -> None:
    draft = {
        "kind": "Transfer",
        "amount": 10.0,
        "account_id": "checking",
        "to_account_id": "checking",
    }

    assert validate_transaction_draft(draft) == "Transfer accounts must be different."


def test_mileage_common_validation_rejects_same_selected_place() -> None:
    selection = AddressSelection("Office", "place-1")
    draft = {"start_selection": selection, "destination_selection": selection}

    assert (
        validate_mileage_draft(draft)
        == "Starting location and destination must be different."
    )


def test_mileage_common_validation_rejects_missing_selections() -> None:
    assert validate_mileage_draft({}) == (
        "Starting location and destination must be selected."
    )


def test_mileage_common_validation_rejects_missing_recorded_text() -> None:
    start = AddressSelection("Office", "place-1")
    destination = AddressSelection("Client", "place-2")

    assert validate_mileage_draft(
        {
            "start_selection": start,
            "destination_selection": destination,
            "start_location": "",
            "destination": "Client",
        }
    ) == "Enter the starting location text to record in the ledger."
    assert validate_mileage_draft(
        {
            "start_selection": start,
            "destination_selection": destination,
            "start_location": "Office",
            "destination": "  ",
        }
    ) == "Enter the destination text to record in the ledger."


def test_metadata_references_preserve_only_selected_inactive_values_in_order() -> None:
    from tabula_rasa.page_renderers.transactions.metadata_fields import (
        active_or_selected, editable_account_ids, transaction_category_ids,
    )
    accounts = [
        {"id": "old", "name": "A", "active": False},
        {"id": "current", "name": "B", "active": True},
        {"id": "other", "name": "C", "active": False},
    ]
    assert editable_account_ids(accounts, ["old"], copy_mode=False) == ["old", "current"]
    assert editable_account_ids(accounts, ["old"], copy_mode=True) == ["current"]
    categories = [
        {"id": "old", "name": "A", "kind": "Expense", "active": False},
        {"id": "current", "name": "B", "kind": "Expense"},
        {"id": "income", "name": "C", "kind": "Income"},
    ]
    assert transaction_category_ids(
        active_or_selected(categories, ["old"], default_active=True), "Expense",
    ) == ["old", "current"]


def test_metadata_reference_normalizes_category_label_and_requires_copy_replacement() -> None:
    from unittest.mock import Mock, patch
    import streamlit as st
    from tabula_rasa.page_renderers.transactions.metadata_fields import render_metadata_reference
    widget = Mock()
    widget.selectbox.return_value = "Office"
    state = {"category": "Office"}
    with patch.object(st, "session_state", state):
        assert render_metadata_reference(
            "Category", ["office"], {"office": "Office"}, key="category",
            normalize_state=True, container=widget,
        ) == "office"
        assert state["category"] == "office"
        render_metadata_reference(
            "Account", ["active"], {"active": "Checking"}, current_id="inactive",
            require_selection=True, container=widget,
        )
    assert widget.selectbox.call_args.kwargs["index"] is None


def test_mileage_payload_excludes_route_state_and_operation_controls() -> None:
    from datetime import date
    from tabula_rasa.page_renderers.mileage_form_shared import mileage_payload_from_draft
    fields = {
        "trip_date": date(2026, 9, 15), "miles": 12.4, "vehicle": "Car",
        "start_location": "Office", "destination": "Client", "business_purpose": "Meeting",
        "notes": "Reviewed", "tag_ids": ["project", "tax"], "new_tag_name": None,
    }
    draft = {
        **fields, "round_trip": True, "return_miles": 13.1,
        "route_state": {"outbound": 99}, "start_selection": object(),
        "id": "existing", "fingerprint": "transient", "calculate_requested": False,
    }
    assert mileage_payload_from_draft(draft) == {**fields, "new_tag_name": ""}
    assert draft["new_tag_name"] is None
