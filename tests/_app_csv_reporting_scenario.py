from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
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


def error_values(app: AppTest) -> list[str]:
    return [str(element.value) for element in app.error]


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
        by_label(app.text_input, "Account name").input("checking")
        by_label(app.selectbox, "Type").set_value("Bank")
        by_label(app.button, "Add account").click().run()
        assert any("unique" in value.casefold() for value in error_values(app))
        assert len(storage.list_accounts(active_only=False)) == 2
        assert by_label(app.text_input, "Account name").value == "checking"
        assert by_label(app.selectbox, "Type").value == "Bank"

        app.radio[0].set_value("Categories").run()
        by_label(app.text_input, "Category name").input("sales")
        by_label(app.selectbox, "Type").set_value("Income")
        by_label(app.button, "Add category").click().run()
        assert any("already exists" in value.casefold() for value in error_values(app))
        assert len(storage.list_categories()) == 16
        assert by_label(app.text_input, "Category name").value == "sales"
        assert by_label(app.selectbox, "Type").value == "Income"

        app.radio[0].set_value("Data & backup").run()
        invalid_csv = b"Date,Type,Amount,Account\n2026-07-19,Income,10,Checking\n"
        by_label(app.file_uploader, "CSV file").set_value(
            ("invalid.csv", invalid_csv, "text/csv")
        ).run()
        assert any("Missing columns" in value for value in error_values(app))
        assert storage.list_transactions() == []

        today = date.today().isoformat()
        valid_csv = (
            "Date,Type,Amount,Account,Category,Payee,Description,Reference\n"
            f"{today},Income,100,Checking,Sales,Customer,Invoice,INV-1\n"
            f"{today},Expense,40,Checking,Software,Vendor,Subscription,BILL-1\n"
        ).encode("utf-8")
        by_label(app.file_uploader, "CSV file").set_value(
            ("transactions.csv", valid_csv, "text/csv")
        ).run()
        by_label(app.button, "Import rows").click().run()
        assert len(storage.list_transactions()) == 2

        by_label(app.button, "Import rows").click().run()
        assert len(storage.list_transactions()) == 2
        assert any("already completed" in str(item.value) for item in app.warning)

        quickbooks_mileage_csv = (
            "Date,Type,Trip Purpose,Vehicle,Start Address,End Address,"
            "Distance,Deduction,Logging Method\n"
            f"{date.today().strftime('%m/%d/%Y')},Business,Client meeting,"
            "Blue car,Office,Client site,14.6,10.22,Auto-tracked\n"
            f"{date.today().strftime('%m/%d/%Y')},Personal,,"
            "Blue car,Home,Store,3.2,0,Auto-tracked\n"
        ).encode("utf-8")
        by_label(app.file_uploader, "QuickBooks mileage CSV").set_value(
            ("quickbooks-trips.csv", quickbooks_mileage_csv, "text/csv")
        ).run()
        mileage_metrics = {metric.label: metric.value for metric in app.metric}
        assert mileage_metrics == {
            "Mileage ready": "1",
            "Mileage duplicates": "0",
            "Personal skipped": "1",
            "Unreviewed skipped": "0",
        }
        by_label(app.button, "Import validated mileage").click().run()
        imported_mileage = storage.list_mileage_trips()
        assert len(imported_mileage) == 1
        assert imported_mileage[0]["miles"] == "14.6"
        assert imported_mileage[0]["business_purpose"] == "Client meeting"

        app.radio[0].set_value("Reports").run()
        report_metrics = {metric.label: metric.value for metric in app.metric}
        assert report_metrics == {
            "Income": "$100.00",
            "Expenses": "$40.00",
            "Net": "$60.00",
            "Total assets": "$60.00",
            "Total liabilities": "$0.00",
            "Total equity": "$60.00",
        }

        app.radio[0].set_value("Dashboard").run()
        dashboard_metrics = {metric.label: metric.value for metric in app.metric}
        assert dashboard_metrics["Income this month"] == "$100.00"
        assert dashboard_metrics["Expenses this month"] == "$40.00"
        assert dashboard_metrics["Net this month"] == "$60.00"
        assert dashboard_metrics["Total balance"] == "$60.00"


if __name__ == "__main__":
    main()
