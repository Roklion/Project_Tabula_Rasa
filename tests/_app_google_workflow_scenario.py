from __future__ import annotations

from datetime import date
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_reporting import balance_sheet
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tests.app_support import (
    account_named,
    authenticated_app,
    by_label,
    category_named,
    navigate_to,
    success_values,
)
from tests.fakes import FakeWorkbook

def ledger_controls(app: AppTest) -> list[tuple[str, str | None]]:
    ledger_tab = next(
        tab for tab in app.tabs if tab.label == "View & edit ledger"
    )
    controls: list[tuple[str, str | None]] = []
    for node in ledger_tab:
        if node.type == "dataframe":
            controls.append((node.type, None))
            break
        if node.type in {
            "date_input",
            "selectbox",
            "multiselect",
            "text_input",
            "button",
            "button_group",
        }:
            controls.append((node.type, getattr(node, "label", None)))
    return controls


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    for payee_name in ("Test vendor", "Test customer", "Test transfer"):
        storage.create_payee(payee_name)
    with authenticated_app(storage) as app:

        navigate_to(app, "Accounts")
        by_label(app.text_input, "Account name").input("Savings")
        by_label(app.selectbox, "Type").set_value("Bank")
        by_label(app.number_input, "Opening balance").set_value(100)
        by_label(app.button, "Add account").click().run()
        assert len(app.exception) == 0
        assert by_label(app.text_input, "Account name").value == ""
        assert by_label(app.selectbox, "Type").value == "Bank"
        assert by_label(app.number_input, "Opening balance").value == 0.0
        assert "Account added." in success_values(app)

        savings = account_named(storage, "Savings")
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
        by_label(app.text_input, "Edit account name").set_value(
            "Primary savings"
        ).run()
        by_label(app.button, "Save account changes").click().run()
        renamed_savings = [
            account
            for account in storage.list_accounts(active_only=False)
            if account["id"] == savings["id"]
        ]
        assert len(renamed_savings) == 1
        assert renamed_savings[0]["name"] == "Primary savings"
        assert not any(
            account["name"] == "Savings"
            for account in storage.list_accounts(active_only=False)
        )

        by_label(app.text_input, "Account name").input("Owner-paid expenses")
        by_label(app.selectbox, "Type").set_value("Equity").run()
        assert (
            by_label(app.selectbox, "Balance-sheet classification").value
            == "Equity"
        )
        by_label(app.number_input, "Opening balance").set_value(0)
        by_label(app.button, "Add account").click().run()
        owner_equity = account_named(storage, "Owner-paid expenses")

        navigate_to(app, "Categories")
        by_label(app.text_input, "Category name").input("Testing expense")
        by_label(app.selectbox, "Type").set_value("Expense")
        by_label(app.button, "Add category").click().run()
        assert len(app.exception) == 0
        assert by_label(app.text_input, "Category name").value == ""
        assert by_label(app.selectbox, "Type").value == "Expense"
        assert "Category added." in success_values(app)
        testing_expense = category_named(storage, "Testing expense")
        by_label(app.selectbox, "Category to edit").set_value(
            testing_expense["id"]
        ).run()
        by_label(app.text_input, "Edit category name").set_value(
            "Testing expense renamed"
        ).run()
        by_label(app.button, "Save category changes").click().run()
        renamed_categories = [
            category
            for category in storage.list_categories()
            if category["id"] == testing_expense["id"]
        ]
        assert len(renamed_categories) == 1
        assert renamed_categories[0]["name"] == "Testing expense renamed"
        assert not any(
            category["name"] == "Testing expense"
            for category in storage.list_categories()
        )

        navigate_to(app, "Transactions")
        assert ledger_controls(app) == [
            ("date_input", "From"),
            ("date_input", "To"),
            ("selectbox", "Type"),
            ("multiselect", "Accounts"),
            ("multiselect", "Tags"),
            ("text_input", "Search transactions"),
            ("button_group", "Ledger mode"),
            ("dataframe", None),
        ]
        assert by_label(app.segmented_control, "Ledger mode").value == "Edit"
        initial_ledger_key = app.dataframe[0].key
        assert initial_ledger_key == "transaction_ledger_test_1"
        by_label(app.segmented_control, "Transaction type").set_value("Expense").run()
        assert app.dataframe[0].key == initial_ledger_key
        assert by_label(app.number_input, "Amount").value == 0.0
        by_label(app.date_input, "Date").set_value(
            date(date.today().year, 1, 1)
        )
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "From Account").set_value("Owner-paid expenses")
        by_label(app.selectbox, "Category").set_value(
            "Testing expense renamed"
        )
        payee_selector = by_label(app.selectbox, "Payee / customer")
        assert payee_selector.options[0] == "No payee"
        payee_selector.set_value("Test vendor").run()
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
        assert (
            by_label(app.selectbox, "Category").value
            == "Testing expense renamed"
        )
        assert by_label(app.selectbox, "Payee / customer").value == next(
            item["id"]
            for item in storage.list_payees()
            if item["name"] == "Test vendor"
        )
        assert (
            by_label(app.text_input, "Description / memo").value
            == "Keep this memo"
        )

        by_label(app.button, "Save transaction").click().run()
        assert len(app.exception) == 0
        assert by_label(app.number_input, "Amount").value == 0.0
        assert by_label(app.selectbox, "Payee / customer").value == ""
        assert by_label(app.text_input, "Description / memo").value == ""
        assert "Transaction saved." in success_values(app)
        owner_expense = next(
            item
            for item in storage.list_transactions()
            if item["kind"] == "Expense"
        )
        stored_payee = next(
            item for item in storage.list_payees() if item["name"] == "Test vendor"
        )
        assert owner_expense["payee_id"] == stored_payee["id"]
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
        by_label(app.selectbox, "To Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Sales")
        by_label(app.selectbox, "Payee / customer").set_value("Test customer").run()
        by_label(app.button, "Save transaction").click().run()

        by_label(app.segmented_control, "Transaction type").set_value("Transfer").run()
        by_label(app.number_input, "Amount").set_value(10)
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "To account").set_value("Primary savings")
        by_label(app.selectbox, "Payee / customer").set_value("Test transfer").run()
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
        account_filter.set_value(["Primary savings"]).run()
        assert app.dataframe[0].value["Type"].tolist() == ["Transfer"]
        by_label(app.multiselect, "Accounts").set_value(
            ["Primary savings", "Owner-paid expenses"]
        ).run()
        assert set(app.dataframe[0].value["Type"]) == {"Expense", "Transfer"}
        by_label(app.multiselect, "Accounts").set_value([]).run()
        ledger_dates = app.dataframe[0].value["Date"].tolist()
        assert ledger_dates == sorted(ledger_dates, reverse=True)

        by_label(app.selectbox, "Type").set_value("Expense").run()
        by_label(app.multiselect, "Accounts").set_value(
            ["Owner-paid expenses"]
        ).run()
        search = by_label(app.text_input, "Search transactions")
        search.input("  test VENDOR  ").run()
        assert ledger_controls(app) == [
            ("date_input", "From"),
            ("date_input", "To"),
            ("selectbox", "Type"),
            ("multiselect", "Accounts"),
            ("multiselect", "Tags"),
            ("text_input", "Search transactions"),
            ("button", "Clear search"),
            ("button_group", "Ledger mode"),
            ("dataframe", None),
        ]
        assert app.dataframe[0].value["Payee"].tolist() == ["Test vendor"]
        assert app.dataframe[0].value["Type"].tolist() == ["Expense"]
        matching_transaction = next(
            item
            for item in storage.list_transactions()
            if item.get("payee") == "Test vendor"
        )
        assert app.session_state["edit_transaction_id"] == matching_transaction[
            "id"
        ]

        mode_key_before_switch = app.dataframe[0].key
        app.session_state["transaction_bulk_selected_ids_test"] = (
            matching_transaction["id"],
        )
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        assert by_label(app.segmented_control, "Ledger mode").value == "Bulk"
        assert by_label(app.selectbox, "Type").value == "Expense"
        assert by_label(app.multiselect, "Accounts").value == [
            "Owner-paid expenses"
        ]
        assert by_label(app.text_input, "Search transactions").value == (
            "  test VENDOR  "
        )
        assert app.session_state["transaction_bulk_selected_ids_test"] == ()
        assert app.dataframe[0].key != mode_key_before_switch
        assert app.dataframe[0].value["Date"].tolist() == sorted(
            app.dataframe[0].value["Date"].tolist(), reverse=True
        )

        bulk_ledger_key = app.dataframe[0].key
        by_label(app.segmented_control, "Ledger mode").set_value("Edit").run()
        assert by_label(app.segmented_control, "Ledger mode").value == "Edit"
        assert by_label(app.text_input, "Search transactions").value == (
            "  test VENDOR  "
        )
        assert app.dataframe[0].key != bulk_ledger_key
        assert app.session_state["edit_transaction_id"] == matching_transaction[
            "id"
        ]

        by_label(app.button, "Clear search").click().run()
        assert by_label(app.text_input, "Search transactions").value == ""
        assert by_label(app.selectbox, "Type").value == "Expense"
        assert by_label(app.multiselect, "Accounts").value == [
            "Owner-paid expenses"
        ]
        assert len(app.dataframe[0].value) == 1
        by_label(app.selectbox, "Type").set_value("All").run()
        by_label(app.multiselect, "Accounts").set_value([]).run()

        transaction = next(
            item for item in storage.list_transactions() if item["kind"] == "Expense"
        )
        checking = account_named(storage, "Checking")
        storage.deactivate_account(owner_equity["id"])
        app.run()
        by_label(app.selectbox, "Transaction to edit").set_value(
            transaction["id"]
        ).run()
        assert "Owner-paid expenses" in by_label(
            app.selectbox, "Edit account"
        ).options
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

        by_label(app.text_input, "Search transactions").input("not-found").run()
        assert app.dataframe[0].value.empty
        assert any(
            "No transactions match your search" in str(message.value)
            for message in app.info
        )
        assert app.session_state["edit_transaction_id"] is None
        by_label(app.button, "Clear search").click().run()

        navigate_to(app, "Accounts")
        navigate_to(app, "Transactions")
        assert app.dataframe[0].key.startswith("transaction_ledger_test_2")
        assert app.dataframe[0].key != initial_ledger_key

        navigate_to(app, "Mileage")
        assert app.dataframe[0].key == "mileage_log_test_1"
        assert list(app.dataframe[0].value.columns) == [
            "ID",
            "Date",
            "Miles",
            "From",
            "Destination",
            "Business purpose",
            "Vehicle",
            "Tags",
            "Notes",
        ]
        assert {metric.label for metric in app.metric} == {
            "Trips",
            "Business miles",
        }
        assert any(
            button.label == "Download filtered mileage CSV"
            for button in app.download_button
        )
        assert sum(
            field.label == "Starting location" for field in app.text_input
        ) == 1
        assert sum(
            field.label == "Destination" for field in app.text_input
        ) == 1
        assert by_label(app.number_input, "Business miles").value == 0.0
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
        assert outbound["id"] != return_trip["id"]
        assert set(outbound) == {
            "id",
            "trip_date",
            "miles",
            "vehicle",
            "start_location",
            "destination",
            "business_purpose",
            "notes",
            "tag_ids",
            "tags",
            "created_at",
        }
        assert set(return_trip) == set(outbound)
        assert outbound["miles"] == return_trip["miles"] == "18.6"
        assert outbound["business_purpose"] == "Project meeting"
        return_trip_id = return_trip["id"]
        return_trip_snapshot = {
            key: return_trip[key]
            for key in (
                "trip_date",
                "miles",
                "vehicle",
                "start_location",
                "destination",
                "business_purpose",
                "notes",
            )
        }
        assert by_label(app.number_input, "Business miles").value == 0.0
        assert by_label(app.text_input, "Vehicle (optional)").value == ""
        assert by_label(app.text_input, "Starting location").value == ""
        assert by_label(app.text_input, "Destination").value == ""
        assert by_label(app.checkbox, "Round trip").value is False
        assert by_label(app.text_input, "Business purpose").value == ""
        assert by_label(app.text_area, "Notes (optional)").value == ""

        navigate_to(app, "Accounts")
        navigate_to(app, "Mileage")
        assert app.dataframe[0].key == "mileage_log_test_2"

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
        unchanged_return = next(
            trip
            for trip in storage.list_mileage_trips()
            if trip["id"] == return_trip_id
        )
        assert {
            key: unchanged_return[key] for key in return_trip_snapshot
        } == return_trip_snapshot
        assert unchanged_return["id"] == return_trip_id

        by_label(
            app.checkbox,
            "I understand this mileage trip will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete mileage trip").click().run()
        assert len(storage.list_mileage_trips()) == 1
        assert storage.list_mileage_trips()[0]["id"] == return_trip_id
        by_label(
            app.checkbox,
            "I understand this mileage trip will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete mileage trip").click().run()
        assert storage.list_mileage_trips() == []


if __name__ == "__main__":
    main()
