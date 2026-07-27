from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password
from ledger_reporting import balance_sheet
from storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    app = AppTest.from_file("app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["business_profiles"] = {
        "test": {
            "name": "Test Business",
            "spreadsheet_id": "test-sheet",
            "gcp_service_account": {"type": "service_account"},
        }
    }

    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()

        app.radio[0].set_value("Accounts").run()
        by_label(app.text_input, "Account name").input("Savings")
        by_label(app.selectbox, "Type").set_value("Bank")
        by_label(app.number_input, "Opening balance").set_value(100)
        by_label(app.button, "Add account").click().run()
        assert len(app.exception) == 0

        savings = next(
            account
            for account in storage.list_accounts(active_only=False)
            if account["name"] == "Savings"
        )
        by_label(app.selectbox, "Account to manage").set_value(savings["id"]).run()
        by_label(app.selectbox, "Edit account type").set_value("Short-term debt").run()
        assert (
            by_label(app.selectbox, "Edit balance-sheet classification").value
            == "Liability"
        )
        by_label(app.button, "Save account changes").click().run()
        savings = next(
            account
            for account in storage.list_accounts(active_only=False)
            if account["id"] == savings["id"]
        )
        assert savings["type"] == "Short-term debt"
        assert savings["classification"] == "Liability"

        by_label(app.text_input, "Account name").input("Owner-paid expenses")
        by_label(app.selectbox, "Type").set_value("Equity").run()
        assert (
            by_label(app.selectbox, "Balance-sheet classification").value
            == "Equity"
        )
        by_label(app.number_input, "Opening balance").set_value(0)
        by_label(app.button, "Add account").click().run()
        owner_equity = next(
            account
            for account in storage.list_accounts(active_only=False)
            if account["name"] == "Owner-paid expenses"
        )

        app.radio[0].set_value("Categories").run()
        by_label(app.text_input, "Category name").input("Testing expense")
        by_label(app.selectbox, "Type").set_value("Expense")
        by_label(app.button, "Add category").click().run()
        assert len(app.exception) == 0

        app.radio[0].set_value("Transactions").run()
        by_label(app.segmented_control, "Transaction type").set_value("Expense").run()
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "Account").set_value("Owner-paid expenses")
        by_label(app.selectbox, "Category").set_value("Testing expense")
        by_label(app.text_input, "Payee / customer").input("Test vendor")
        by_label(app.button, "Save transaction").click().run()
        assert len(app.exception) == 0
        owner_expense = next(
            item
            for item in storage.list_transactions()
            if item["kind"] == "Expense"
        )
        assert owner_expense["account_id"] == owner_equity["id"]
        statement = balance_sheet(
            storage.list_accounts(active_only=False),
            storage.list_transactions(),
        )
        assert statement["total_equity"] == 0
        assert statement["current_earnings"] == -25
        assert next(
            item
            for item in statement["equity"]
            if item["id"] == owner_equity["id"]
        )["balance"] == 25

        by_label(app.segmented_control, "Transaction type").set_value("Income").run()
        by_label(app.number_input, "Amount").set_value(75)
        by_label(app.selectbox, "Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Sales")
        by_label(app.text_input, "Payee / customer").input("Test customer")
        by_label(app.button, "Save transaction").click().run()

        by_label(app.segmented_control, "Transaction type").set_value("Transfer").run()
        by_label(app.number_input, "Amount").set_value(10)
        by_label(app.selectbox, "From account").set_value("Checking")
        by_label(app.selectbox, "To account").set_value("Savings")
        by_label(app.button, "Save transaction").click().run()
        assert {item["kind"] for item in storage.list_transactions()} == {
            "Expense",
            "Income",
            "Transfer",
        }

        transaction = next(
            item for item in storage.list_transactions() if item["kind"] == "Expense"
        )
        checking = next(
            account
            for account in storage.list_accounts(active_only=False)
            if account["name"] == "Checking"
        )
        by_label(app.selectbox, "Transaction to edit").set_value(
            transaction["id"]
        ).run()
        by_label(app.selectbox, "Edit account").set_value(checking["id"])
        by_label(app.number_input, "Edit amount").set_value(30)
        by_label(app.button, "Save changes").click().run()
        edited_transaction = next(
            item
            for item in storage.list_transactions()
            if item["id"] == transaction["id"]
        )
        assert edited_transaction["amount"] == "30.00"
        assert edited_transaction["account_id"] == checking["id"]

        by_label(
            app.checkbox,
            "I understand this transaction will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete").click().run()
        assert len(storage.list_transactions()) == 2

        app.radio[0].set_value("Mileage").run()
        by_label(app.number_input, "Business miles").set_value(18.6)
        by_label(app.text_input, "Vehicle (optional)").input("Blue car")
        by_label(app.text_input, "Starting location").input("Office")
        by_label(app.text_input, "Destination").input("Client site")
        by_label(app.text_input, "Business purpose").input("Project meeting")
        by_label(app.button, "Save mileage trip").click().run()
        assert len(app.exception) == 0
        trip = storage.list_mileage_trips()[0]
        assert trip["miles"] == "18.6"
        assert trip["business_purpose"] == "Project meeting"

        by_label(app.number_input, "Edit business miles").set_value(20.1)
        by_label(app.button, "Save mileage changes").click().run()
        assert storage.list_mileage_trips()[0]["miles"] == "20.1"

        by_label(
            app.checkbox,
            "I understand this mileage trip will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete mileage trip").click().run()
        assert storage.list_mileage_trips() == []


if __name__ == "__main__":
    main()
