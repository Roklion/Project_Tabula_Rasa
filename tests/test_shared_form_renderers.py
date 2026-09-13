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
