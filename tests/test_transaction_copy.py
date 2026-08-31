from __future__ import annotations

from datetime import date
from unittest.mock import patch

from tests.app_support import (
    authenticated_app,
    by_label,
    navigate_to,
    profile_config,
)
from tests.fakes import FakeWorkbook
from tabula_rasa.page_renderers.transactions.ledger import (
    _change_ledger_mode,
    _editable_account_ids,
    copied_transaction_description,
)
from tabula_rasa.storage import GoogleSheetsStorage


def _transaction_fixture() -> tuple[GoogleSheetsStorage, dict[str, str]]:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    transaction = storage.create_transaction(
        txn_date=f"{date.today().year}-07-19",
        kind="Expense",
        amount=12.5,
        account_id=account["id"],
        category_id=category["id"],
        payee="Vendor",
        description="Original memo",
        reference="INV-123",
    )
    return storage, transaction


def test_copied_transaction_description_retains_source_memo() -> None:
    transaction = {"id": "source-123", "description": "Original memo"}

    assert copied_transaction_description(transaction) == (
        "Copied from transaction source-123: Original memo"
    )
    assert copied_transaction_description({"id": "source-123"}) == (
        "Copied from transaction source-123"
    )
    assert copied_transaction_description({"id": None}) == (
        "Copied from transaction"
    )


def test_copy_account_choices_exclude_inactive_source_account() -> None:
    accounts = [
        {"id": "inactive", "name": "Old account", "active": False},
        {"id": "active", "name": "Current account", "active": True},
    ]

    assert _editable_account_ids(
        accounts, ["inactive"], copy_mode=True
    ) == ["active"]
    assert _editable_account_ids(
        accounts, ["inactive"], copy_mode=False
    ) == ["active", "inactive"]


def test_switching_ledger_mode_preserves_copy_editor_target() -> None:
    state = {
        "transaction_bulk_selection_generation": 0,
        "transaction_ledger_mode_generation": 0,
        "transaction_copy_source_test": "source-id",
        "edit_transaction_id": "source-id",
    }

    with patch(
        "tabula_rasa.page_renderers.transactions.ledger.st.session_state", state
    ):
        _change_ledger_mode("test")

    assert state["edit_transaction_id"] == "source-id"


def test_copy_form_can_be_canceled_without_creating_or_mutating_transaction() -> None:
    storage, source = _transaction_fixture()
    original_source = dict(source)
    original_rows = storage.list_transactions()

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        assert by_label(app.button, "Copy transaction").disabled is True
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()

        copy_button = by_label(app.button, "Copy transaction")
        assert copy_button.disabled is False
        copy_button.click().run()
        assert any(item.label == "Copy transaction" for item in app.expander)
        assert by_label(app.date_input, "Edit date").value == date.fromisoformat(
            source["txn_date"]
        )
        assert by_label(app.text_input, "Edit description").value == (
            "Copied from transaction "
            f"{source['id']}: Original memo"
        )
        assert by_label(app.date_input, "From").disabled is True
        assert by_label(app.date_input, "To").disabled is True
        assert by_label(app.selectbox, "Type").disabled is True
        assert by_label(app.multiselect, "Accounts").disabled is True
        assert by_label(app.text_input, "Search transactions").disabled is True
        assert app.dataframe[0].selection_mode == []

        by_label(app.button, "Cancel copy").click().run()

        assert storage.list_transactions() == original_rows
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.text_input, "Edit payee / customer").set_value("New vendor")
        by_label(app.button, "Save copied transaction").click().run()
        copied = next(
            item for item in storage.list_transactions() if item["id"] != source["id"]
        )
        assert app.session_state["edit_transaction_id"] == copied["id"]
        assert "transaction_copy_source_test" not in app.session_state

    transactions = storage.list_transactions()
    assert len(transactions) == 2
    copied = next(item for item in transactions if item["id"] != source["id"])
    assert copied["txn_date"] == original_source["txn_date"]
    assert copied["payee"] == "New vendor"
    assert copied["description"] == (
        "Copied from transaction "
        f"{source['id']}: Original memo"
    )
    assert copied["receipt_references"] == "[]"
    assert next(item for item in transactions if item["id"] == source["id"]) == (
        original_source
    )


def test_copy_with_inactive_source_allows_active_account_replacement() -> None:
    storage, source = _transaction_fixture()
    replacement = storage.create_account("Replacement", "Bank")
    storage.deactivate_account(source["account_id"])

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()

        account_selector = by_label(app.selectbox, "Edit account")
        assert source["account_id"] not in account_selector.options
        assert "Replacement" in account_selector.options
        assert by_label(app.button, "Save copied transaction").disabled is False

        account_selector.set_value(replacement["id"]).run()
        by_label(app.button, "Save copied transaction").click().run()

    transactions = storage.list_transactions()
    assert len(transactions) == 2
    copied = next(item for item in transactions if item["id"] != source["id"])
    assert copied["account_id"] == replacement["id"]


def test_copy_save_adjusts_filters_to_keep_new_transaction_selected() -> None:
    storage, source = _transaction_fixture()
    created_date = date(date.today().year + 1, 1, 2)

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.date_input, "Edit date").set_value(created_date)
        by_label(app.button, "Save copied transaction").click().run()

        copied = next(
            item for item in storage.list_transactions() if item["id"] != source["id"]
        )
        assert copied["txn_date"] == created_date.isoformat()
        assert app.session_state["edit_transaction_id"] == copied["id"]
        assert copied["id"] in [
            str(transaction_id)
            for transaction_id in app.dataframe[0].value["ID"]
        ]


def test_copy_state_is_cleared_when_switching_profiles() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook()),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook()),
    }
    profiles = {
        "alpha": profile_config(
            name="Alpha Business", spreadsheet_id="alpha-sheet"
        ),
        "beta": profile_config(name="Beta Business", spreadsheet_id="beta-sheet"),
    }
    alpha = storages["alpha-sheet"]
    alpha_account = alpha.create_account("Alpha Checking", "Bank")
    alpha_category = alpha.create_category("Alpha Office", "Expense")
    alpha_transaction = alpha.create_transaction(
        txn_date="2026-07-19",
        kind="Expense",
        amount=12.5,
        account_id=alpha_account["id"],
        category_id=alpha_category["id"],
        description="Alpha memo",
    )
    beta = storages["beta-sheet"]
    beta_account = beta.create_account("Beta Checking", "Bank")
    beta_category = beta.create_category("Beta Office", "Expense")
    beta.create_transaction(
        txn_date="2026-07-20",
        kind="Expense",
        amount=20.0,
        account_id=beta_account["id"],
        category_id=beta_category["id"],
        description="Beta memo",
    )

    with authenticated_app(storages=storages, profiles=profiles) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_alpha"] = (
            alpha_transaction["id"],
        )
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        assert "transaction_copy_source_alpha" in app.session_state
        assert by_label(app.button, "Save copied transaction")

        by_label(app.selectbox, "Business").set_value("beta").run()

        assert "transaction_copy_source_alpha" not in app.session_state
        assert not any(
            item.label == "Save copied transaction" for item in app.button
        )
        assert not any(item.label == "Copy transaction" for item in app.expander)
