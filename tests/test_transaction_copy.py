from __future__ import annotations

from datetime import date

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.page_renderers.transactions.ledger import (
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

        by_label(app.button, "Cancel copy").click().run()

        assert storage.list_transactions() == original_rows
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.text_input, "Edit payee / customer").set_value("New vendor")
        by_label(app.button, "Save copied transaction").click().run()

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
