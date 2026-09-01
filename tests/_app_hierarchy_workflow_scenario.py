from __future__ import annotations

from datetime import date
from streamlit.testing.v1 import AppTest

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import (
    account_named,
    authenticated_app,
    by_label,
    category_named,
    navigate_to,
    profile_config,
)
from tests.fakes import FakeWorkbook


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
    return account_named(storage, name)


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
    return category_named(storage, name)


def main() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook()),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook()),
    }

    profiles = {
        "alpha": profile_config(name="Alpha Business", spreadsheet_id="alpha-sheet"),
        "beta": profile_config(name="Beta Business", spreadsheet_id="beta-sheet"),
    }
    with authenticated_app(storages=storages, profiles=profiles) as app:
        navigate_to(app, "Accounts")

        alpha = storages["alpha-sheet"]
        beta = storages["beta-sheet"]
        operations = add_account(app, alpha, "Operations")
        petty_cash = add_account(
            app,
            alpha,
            "Petty cash",
            account_type="Cash",
            parent_id=operations["id"],
        )
        payables = add_account(app, alpha, "Payables", account_type="Credit card")
        parent_options = by_label(
            app.selectbox, "Parent account (optional)"
        ).options
        assert "Operations" in parent_options
        assert "Operations › Petty cash" not in parent_options
        assert "Payables" not in parent_options
        assert "Layer 2" in app.dataframe[0].value["Layer"].tolist()
        assert "Operations" in app.dataframe[0].value["Parent"].tolist()
        assert app.dataframe[0].key == "account_table_alpha_1"
        assert any(
            "Select an account row" in str(caption.value)
            for caption in app.caption
        )
        refresh_child = add_account(
            app,
            alpha,
            "ZZ Refresh child",
            account_type="Cash",
            parent_id=operations["id"],
        )
        app.session_state["edit_account_id"] = refresh_child["id"]
        app.run()
        assert (
            by_label(app.selectbox, "Account to manage").value
            == refresh_child["id"]
        )
        by_label(app.selectbox, "Edit account type").set_value("Credit card").run()
        assert by_label(app.selectbox, "Edit parent account").value == ""
        by_label(app.button, "Save account changes").click().run()
        account_selector = by_label(app.selectbox, "Account to manage")
        assert "ZZ Refresh child" in account_selector.options
        assert "Operations › ZZ Refresh child" not in account_selector.options

        by_label(app.selectbox, "Account to manage").set_value(
            petty_cash["id"]
        ).run()
        by_label(app.selectbox, "Edit parent account").set_value("").run()
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
        by_label(app.selectbox, "Edit parent account").set_value(
            operations["id"]
        ).run()
        by_label(app.button, "Save account changes").click().run()

        navigate_to(app, "Categories")
        travel = add_category(app, alpha, "Travel")
        flights = add_category(app, alpha, "Flights", parent_id=travel["id"])
        assert "Travel" in app.dataframe[0].value["Parent"].tolist()
        assert app.dataframe[0].key == "category_table_alpha_1"
        assert any(
            "Select a category row" in str(caption.value)
            for caption in app.caption
        )
        app.session_state["edit_category_id"] = flights["id"]
        app.run()
        assert by_label(app.selectbox, "Category to edit").value == flights["id"]
        category_options = by_label(app.selectbox, "Category to edit").options
        travel_option = next(
            option for option in category_options if option.startswith("Travel ")
        )
        flights_option = next(
            option for option in category_options if "Flights" in option
        )
        assert category_options.index(travel_option) < category_options.index(
            flights_option
        )
        by_label(app.selectbox, "Category to edit").set_value(travel["id"]).run()
        by_label(
            app.checkbox,
            "I understand this category will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete category").click().run()
        assert any(
            "child categories" in str(error.value).casefold()
            for error in app.error
        )
        unused = add_category(app, alpha, "Unused")
        by_label(app.selectbox, "Category to edit").set_value(unused["id"]).run()
        by_label(
            app.checkbox,
            "I understand this category will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete category").click().run()
        assert not any(
            category["id"] == unused["id"]
            for category in alpha.list_categories()
        )
        by_label(app.selectbox, "Parent category (optional)").set_value(
            travel["id"]
        )
        by_label(app.selectbox, "Type").set_value("Income").run()
        assert by_label(app.selectbox, "Parent category (optional)").value == ""
        add_parent_options = by_label(
            app.selectbox, "Parent category (optional)"
        ).options
        assert "Sales" in add_parent_options
        assert "Travel" not in add_parent_options
        by_label(app.selectbox, "Type").set_value("Expense").run()
        by_label(app.selectbox, "Category to edit").set_value(flights["id"]).run()
        by_label(app.selectbox, "Edit category type").set_value("Income").run()
        edit_parent_options = by_label(
            app.selectbox, "Edit parent category"
        ).options
        assert "Sales" in edit_parent_options
        assert "Travel" not in edit_parent_options
        by_label(app.selectbox, "Edit category type").set_value("Expense").run()

        by_label(app.selectbox, "Business").set_value("beta").run()
        navigate_to(app, "Categories")
        beta_only = add_category(app, beta, "Beta only")
        app.session_state["edit_category_id"] = beta_only["id"]
        app.run()
        assert "Beta only" in app.dataframe[0].value["Category"].tolist()
        by_label(app.selectbox, "Business").set_value("alpha").run()
        navigate_to(app, "Categories")
        assert "Beta only" not in app.dataframe[0].value["Category"].tolist()
        assert (
            "edit_category_id" not in app.session_state
            or app.session_state["edit_category_id"] != beta_only["id"]
        )

        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Transaction type").set_value(
            "Expense"
        ).run()
        assert "Operations › Petty cash" in by_label(
            app.selectbox, "From Account"
        ).options
        from_account_options = by_label(
            app.selectbox, "From Account"
        ).options
        assert from_account_options.index("Operations") < from_account_options.index(
            "Operations › Petty cash"
        ) < from_account_options.index("Payables")
        assert "Travel › Flights" in by_label(
            app.selectbox, "Category"
        ).options
        by_label(app.date_input, "Date").set_value(date.today())
        by_label(app.number_input, "Amount").set_value(12)
        by_label(app.selectbox, "From Account").set_value(
            "Operations › Petty cash"
        )
        by_label(app.selectbox, "Category").set_value("Travel › Flights")
        by_label(app.text_input, "Payee / customer").input("Hierarchy vendor")
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
        by_label(app.text_input, "Payee / customer").input("Hierarchy transfer")
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

        by_label(app.segmented_control, "Transaction type").set_value(
            "Income"
        ).run()
        by_label(app.number_input, "Amount").set_value(20)
        by_label(app.selectbox, "From Account").set_value("Operations")
        by_label(app.selectbox, "Category").set_value("Sales")
        by_label(app.text_input, "Payee / customer").input("Hierarchy income")
        by_label(app.button, "Save transaction").click().run()

        navigate_to(app, "Accounts")
        account_table = app.dataframe[0].value
        operations_account_row = account_table.loc[
            account_table["Account"] == "Operations"
        ].iloc[0]
        petty_cash_account_row = account_table.loc[
            account_table["Account"].str.endswith("Petty cash")
        ].iloc[0]
        payables_account_row = account_table.loc[
            account_table["Account"] == "Payables"
        ].iloc[0]
        assert operations_account_row["Balance"] == 5.0
        assert operations_account_row["Transaction count"] == 3
        assert petty_cash_account_row["Transaction count"] == 2
        assert payables_account_row["Transaction count"] == 1

        by_label(app.selectbox, "Account to manage").set_value(payables["id"]).run()
        by_label(app.checkbox, "Active").uncheck()
        by_label(app.button, "Save account changes").click().run()
        assert next(
            account
            for account in alpha.list_accounts(active_only=False)
            if account["id"] == payables["id"]
        )["active"] is False
        inactive_row = app.dataframe[0].value.loc[
            app.dataframe[0].value["Account"] == "Payables"
        ].iloc[0]
        assert inactive_row["Active"] == "Inactive"

        navigate_to(app, "Categories")
        category_table = app.dataframe[0].value
        travel_category_row = category_table.loc[
            category_table["Category"] == "Travel"
        ].iloc[0]
        flights_category_row = category_table.loc[
            category_table["Category"].str.endswith("Flights")
        ].iloc[0]
        sales_category_row = category_table.loc[
            category_table["Category"] == "Sales"
        ].iloc[0]
        assert travel_category_row["Transaction count"] == 0
        assert flights_category_row["Transaction count"] == 1
        assert sales_category_row["Transaction count"] == 1
        by_label(app.selectbox, "Category to edit").set_value(flights["id"]).run()
        by_label(
            app.checkbox,
            "I understand this category will be permanently deleted",
        ).check()
        by_label(app.button, "Permanently delete category").click().run()
        assert any(
            "transactions" in str(error.value).casefold()
            for error in app.error
        )
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

        navigate_to(app, "Reports")
        category_report = next(
            frame.value
            for frame in app.dataframe
            if "Direct activity" in frame.value.columns
        )
        travel_row = category_report.loc[
            category_report["Category"] == "Travel"
        ].iloc[0]
        flights_row = category_report.loc[
            category_report["Category"] == "↳ Flights"
        ].iloc[0]
        assert travel_row["Direct activity"] == 0.0
        assert travel_row["Layer 1 total"] == 12.0
        assert flights_row["Direct activity"] == 12.0
        asset_report = next(
            frame.value
            for frame in app.dataframe
            if "Type" in frame.value.columns
            and "Layer 1 total" in frame.value["Type"].tolist()
        )
        operations_row = asset_report.loc[
            asset_report["Account"] == "Operations"
        ].iloc[0]
        direct_row = asset_report.loc[
            asset_report["Account"] == "↳ Direct activity"
        ].iloc[0]
        assert operations_row["Balance"] == 5.0
        assert direct_row["Balance"] == 20.0

        navigate_to(app, "Accounts")
        by_label(app.text_input, "Account name").input("Alpha draft")
        by_label(app.selectbox, "Parent account (optional)").set_value(
            operations["id"]
        )
        by_label(app.selectbox, "Business").set_value("beta").run()
        navigate_to(app, "Accounts")
        beta = storages["beta-sheet"]
        assert by_label(app.text_input, "Account name").value == ""
        assert by_label(app.selectbox, "Parent account (optional)").value == ""
        assert "Operations" not in by_label(
            app.selectbox, "Parent account (optional)"
        ).options

        add_account(app, beta, "Shared account")
        by_label(app.selectbox, "Business").set_value("alpha").run()
        navigate_to(app, "Accounts")
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

        navigate_to(app, "Transactions")
        by_label(app.text_input, "Search transactions").input("Flights").run()
        assert not app.dataframe[0].value.empty
        by_label(app.selectbox, "Business").set_value("beta").run()
        navigate_to(app, "Transactions")
        assert by_label(app.text_input, "Search transactions").value == ""
        assert app.dataframe[0].value.empty


if __name__ == "__main__":
    main()
