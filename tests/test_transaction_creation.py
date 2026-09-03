from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


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
