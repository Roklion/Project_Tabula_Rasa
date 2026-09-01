from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


def test_add_transaction_rejects_blank_new_payee() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        payee_selector = by_label(app.selectbox, "Payee / customer")
        payee_selector.set_value("+ Add new payee").run()
        by_label(app.text_input, "Payee / customer").set_value("")
        by_label(app.button, "Save transaction").click().run()

        assert storage.list_transactions() == []
        assert any(
            "Enter a payee / customer name before saving." in str(error.value)
            for error in app.error
        )
