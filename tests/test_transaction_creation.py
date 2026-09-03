from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


def test_add_transaction_can_select_payee() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.create_payee("New vendor")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.number_input, "Amount").set_value(25).run()
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "Category").set_value("Office").run()
        by_label(app.selectbox, "Payee / customer").set_value("New vendor").run()
        by_label(app.button, "Save transaction").click().run()

    transaction = storage.list_transactions()[0]
    assert transaction["payee"] == "New vendor"
    assert transaction["payee_id"] == storage.list_payees()[0]["id"]
