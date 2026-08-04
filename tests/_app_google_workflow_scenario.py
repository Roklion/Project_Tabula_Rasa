from __future__ import annotations

from datetime import date
import sys
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.ledger_reporting import balance_sheet
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def success_values(app: AppTest) -> list[str]:
    return [str(element.value) for element in app.success]


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
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
        assert by_label(app.text_input, "Account name").value == ""
        assert by_label(app.selectbox, "Type").value == "Bank"
        assert by_label(app.number_input, "Opening balance").value == 0.0
        assert "Account added." in success_values(app)

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
        assert "Account updated." in success_values(app)

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
        assert by_label(app.text_input, "Category name").value == ""
        assert by_label(app.selectbox, "Type").value == "Expense"
        assert "Category added." in success_values(app)

        app.radio[0].set_value("Transactions").run()
        initial_ledger_key = app.dataframe[0].key
        assert initial_ledger_key == "transaction_ledger_1"
        by_label(app.segmented_control, "Transaction type").set_value("Expense").run()
        assert app.dataframe[0].key == initial_ledger_key
        by_label(app.date_input, "Date").set_value(
            date(date.today().year, 1, 1)
        )
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "From Account").set_value("Owner-paid expenses")
        by_label(app.selectbox, "Category").set_value("Testing expense")
        by_label(app.text_input, "Payee / customer").input("Test vendor")
        by_label(app.text_input, "Description / memo").input("Keep this memo")
        with patch.object(
            storage,
            "create_transaction",
            side_effect=StorageValidationError("Test validation error"),
        ):
            by_label(app.button, "Save transaction").click().run()
        assert storage.list_transactions() == []
        assert by_label(app.number_input, "Amount").value == 25
        assert (
            by_label(app.selectbox, "From Account").value
            == "Owner-paid expenses"
        )
        assert by_label(app.selectbox, "Category").value == "Testing expense"
        assert by_label(app.text_input, "Payee / customer").value == "Test vendor"
        assert (
            by_label(app.text_input, "Description / memo").value
            == "Keep this memo"
        )

        by_label(app.button, "Save transaction").click().run()
        assert len(app.exception) == 0
        assert by_label(app.number_input, "Amount").value == 0.01
        assert by_label(app.text_input, "Payee / customer").value == ""
        assert by_label(app.text_input, "Description / memo").value == ""
        assert "Transaction saved." in success_values(app)
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
        by_label(app.selectbox, "From Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Sales")
        by_label(app.text_input, "Payee / customer").input("Test customer")
        by_label(app.button, "Save transaction").click().run()

        by_label(app.segmented_control, "Transaction type").set_value("Transfer").run()
        by_label(app.number_input, "Amount").set_value(10)
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "To account").set_value("Savings")
        by_label(app.button, "Save transaction").click().run()
        assert {item["kind"] for item in storage.list_transactions()} == {
            "Expense",
            "Income",
            "Transfer",
        }
        assert [
            item["kind"]
            for item in storage.list_transactions(account_ids=[savings["id"]])
        ] == ["Transfer"]
        account_filter = by_label(app.multiselect, "Accounts")
        account_filter.set_value(["Savings"]).run()
        assert app.dataframe[0].value["Type"].tolist() == ["Transfer"]
        by_label(app.multiselect, "Accounts").set_value(
            ["Savings", "Owner-paid expenses"]
        ).run()
        assert set(app.dataframe[0].value["Type"]) == {"Expense", "Transfer"}
        by_label(app.multiselect, "Accounts").set_value([]).run()
        ledger_dates = app.dataframe[0].value["Date"].tolist()
        assert ledger_dates == sorted(ledger_dates, reverse=True)

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
        assert "Transaction updated." in success_values(app)

        by_label(
            app.checkbox,
            "I understand this transaction will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete").click().run()
        assert len(storage.list_transactions()) == 2

        app.radio[0].set_value("Accounts").run()
        app.radio[0].set_value("Transactions").run()
        assert app.dataframe[0].key == "transaction_ledger_2"
        assert app.dataframe[0].key != initial_ledger_key

        app.radio[0].set_value("Mileage").run()
        by_label(app.number_input, "Business miles").set_value(18.6)
        by_label(app.text_input, "Vehicle (optional)").input("Blue car")
        by_label(app.text_input, "Starting location").input("Office")
        by_label(app.text_input, "Destination").input("Client site")
        by_label(app.checkbox, "Round trip").check()
        by_label(app.text_area, "Notes (optional)").input("Keep this note")
        by_label(app.button, "Save mileage trip").click().run()
        assert storage.list_mileage_trips() == []
        assert any(
            "Business purpose is required" in str(error.value)
            for error in app.error
        )
        assert by_label(app.number_input, "Business miles").value == 18.6
        assert by_label(app.text_input, "Vehicle (optional)").value == "Blue car"
        assert by_label(app.text_input, "Starting location").value == "Office"
        assert by_label(app.text_input, "Destination").value == "Client site"
        assert by_label(app.checkbox, "Round trip").value is True
        assert by_label(app.text_area, "Notes (optional)").value == "Keep this note"

        by_label(app.text_input, "Business purpose").input("Project meeting")
        by_label(app.button, "Save mileage trip").click().run()
        assert len(app.exception) == 0
        mileage_trips = storage.list_mileage_trips()
        assert len(mileage_trips) == 2
        outbound = next(
            trip
            for trip in mileage_trips
            if trip["start_location"] == "Office"
        )
        return_trip = next(
            trip
            for trip in mileage_trips
            if trip["start_location"] == "Client site"
        )
        assert outbound["destination"] == "Client site"
        assert return_trip["destination"] == "Office"
        assert outbound["miles"] == return_trip["miles"] == "18.6"
        assert outbound["business_purpose"] == "Project meeting"
        assert by_label(app.number_input, "Business miles").value == 0.1
        assert by_label(app.text_input, "Vehicle (optional)").value == ""
        assert by_label(app.text_input, "Starting location").value == ""
        assert by_label(app.text_input, "Destination").value == ""
        assert by_label(app.checkbox, "Round trip").value is False
        assert by_label(app.text_input, "Business purpose").value == ""
        assert by_label(app.text_area, "Notes (optional)").value == ""

        by_label(app.selectbox, "Mileage trip to edit").set_value(
            outbound["id"]
        ).run()
        by_label(app.number_input, "Edit business miles").set_value(20.1)
        by_label(app.button, "Save mileage changes").click().run()
        edited_outbound = next(
            trip
            for trip in storage.list_mileage_trips()
            if trip["id"] == outbound["id"]
        )
        assert edited_outbound["miles"] == "20.1"

        by_label(
            app.checkbox,
            "I understand this mileage trip will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete mileage trip").click().run()
        assert len(storage.list_mileage_trips()) == 1
        by_label(
            app.checkbox,
            "I understand this mileage trip will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete mileage trip").click().run()
        assert storage.list_mileage_trips() == []


if __name__ == "__main__":
    main()
