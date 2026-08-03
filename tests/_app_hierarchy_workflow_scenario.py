from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def add_account(
    app: AppTest,
    storage: GoogleSheetsStorage,
    name: str,
    *,
    account_type: str = "Bank",
    parent_id: str = "",
) -> dict:
    by_label(app.text_input, "Account name").input(name)
    by_label(app.selectbox, "Type").set_value(account_type).run()
    if parent_id:
        by_label(app.selectbox, "Parent account (optional)").set_value(parent_id)
    by_label(app.button, "Add account").click().run()
    return next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == name
    )


def add_category(
    app: AppTest,
    storage: GoogleSheetsStorage,
    name: str,
    *,
    parent_id: str = "",
) -> dict:
    by_label(app.text_input, "Category name").input(name)
    by_label(app.selectbox, "Type").set_value("Expense").run()
    if parent_id:
        by_label(app.selectbox, "Parent category (optional)").set_value(parent_id)
    by_label(app.button, "Add category").click().run()
    return next(
        category
        for category in storage.list_categories()
        if category["name"] == name
    )


def main() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook()),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook()),
    }

    def storage_from_secrets(secrets: dict) -> GoogleSheetsStorage:
        return storages[secrets["spreadsheet_id"]]

    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["business_profiles"] = {
        "alpha": {
            "name": "Alpha Business",
            "spreadsheet_id": "alpha-sheet",
            "gcp_service_account": {"type": "service_account"},
        },
        "beta": {
            "name": "Beta Business",
            "spreadsheet_id": "beta-sheet",
            "gcp_service_account": {"type": "service_account"},
        },
    }

    with patch.object(
        GoogleSheetsStorage,
        "from_secrets",
        side_effect=storage_from_secrets,
    ):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Accounts").run()

        alpha = storages["alpha-sheet"]
        operations = add_account(app, alpha, "Operations")
        petty_cash = add_account(
            app,
            alpha,
            "Petty cash",
            account_type="Cash",
            parent_id=operations["id"],
        )
        add_account(app, alpha, "Payables", account_type="Credit card")
        parent_options = by_label(
            app.selectbox, "Parent account (optional)"
        ).options
        assert "Operations" in parent_options
        assert "Operations › Petty cash" not in parent_options
        assert "Payables" not in parent_options
        assert "Layer 2" in app.dataframe[0].value["Layer"].tolist()
        assert "Operations" in app.dataframe[0].value["Parent"].tolist()

        by_label(app.selectbox, "Account to manage").set_value(
            petty_cash["id"]
        ).run()
        by_label(app.selectbox, "Edit parent account").set_value("")
        by_label(app.button, "Save account changes").click().run()
        promoted_account = next(
            account
            for account in alpha.list_accounts(active_only=False)
            if account["id"] == petty_cash["id"]
        )
        assert promoted_account["parent_id"] == ""

        by_label(app.selectbox, "Account to manage").set_value(
            petty_cash["id"]
        ).run()
        by_label(app.selectbox, "Edit parent account").set_value(operations["id"])
        by_label(app.button, "Save account changes").click().run()

        app.radio[0].set_value("Categories").run()
        travel = add_category(app, alpha, "Travel")
        flights = add_category(app, alpha, "Flights", parent_id=travel["id"])
        assert "Travel" in app.dataframe[0].value["Parent"].tolist()

        app.radio[0].set_value("Transactions").run()
        by_label(app.segmented_control, "Transaction type").set_value(
            "Expense"
        ).run()
        assert "Operations › Petty cash" in by_label(
            app.selectbox, "From Account"
        ).options
        assert "Travel › Flights" in by_label(
            app.selectbox, "Category"
        ).options
        by_label(app.date_input, "Date").set_value(date.today())
        by_label(app.number_input, "Amount").set_value(12)
        by_label(app.selectbox, "From Account").set_value(
            "Operations › Petty cash"
        )
        by_label(app.selectbox, "Category").set_value("Travel › Flights")
        by_label(app.button, "Save transaction").click().run()
        transaction = alpha.list_transactions()[0]
        assert transaction["account_id"] == petty_cash["id"]
        assert transaction["category_id"] == flights["id"]

        by_label(app.segmented_control, "Transaction type").set_value(
            "Transfer"
        ).run()
        by_label(app.number_input, "Amount").set_value(3)
        by_label(app.selectbox, "From Account").set_value(
            "Operations › Petty cash"
        ).run()
        by_label(app.selectbox, "To account").set_value("Payables")
        by_label(app.button, "Save transaction").click().run()
        transfer = next(
            item for item in alpha.list_transactions() if item["kind"] == "Transfer"
        )
        assert transfer["account_id"] == petty_cash["id"]
        assert transfer["to_account_id"] == next(
            account["id"]
            for account in alpha.list_accounts(active_only=False)
            if account["name"] == "Payables"
        )

        app.radio[0].set_value("Categories").run()
        by_label(app.selectbox, "Category to edit").set_value(flights["id"]).run()
        by_label(app.selectbox, "Edit parent category").set_value("")
        by_label(app.button, "Save category changes").click().run()
        assert next(
            category
            for category in alpha.list_categories()
            if category["id"] == flights["id"]
        )["parent_id"] == ""
        by_label(app.selectbox, "Category to edit").set_value(flights["id"]).run()
        by_label(app.selectbox, "Edit parent category").set_value(travel["id"])
        by_label(app.button, "Save category changes").click().run()
        assert next(
            category
            for category in alpha.list_categories()
            if category["id"] == flights["id"]
        )["parent_id"] == travel["id"]

        app.radio[0].set_value("Accounts").run()
        by_label(app.text_input, "Account name").input("Alpha draft")
        by_label(app.selectbox, "Parent account (optional)").set_value(
            operations["id"]
        )
        by_label(app.selectbox, "Business").set_value("beta").run()
        app.radio[0].set_value("Accounts").run()
        beta = storages["beta-sheet"]
        assert by_label(app.text_input, "Account name").value == ""
        assert by_label(app.selectbox, "Parent account (optional)").value == ""
        assert "Operations" not in by_label(
            app.selectbox, "Parent account (optional)"
        ).options

        add_account(app, beta, "Shared account")
        by_label(app.selectbox, "Business").set_value("alpha").run()
        app.radio[0].set_value("Accounts").run()
        add_account(app, alpha, "Shared account")
        assert any(
            account["name"] == "Shared account"
            for account in alpha.list_accounts(active_only=False)
        )
        assert any(
            account["name"] == "Shared account"
            for account in beta.list_accounts(active_only=False)
        )
        unchanged_transaction = next(
            item for item in alpha.list_transactions() if item["kind"] == "Expense"
        )
        assert unchanged_transaction["id"] == transaction["id"]
        assert unchanged_transaction["account_id"] == petty_cash["id"]
        assert unchanged_transaction["category_id"] == flights["id"]


if __name__ == "__main__":
    main()
