from __future__ import annotations

from datetime import date
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import (
    authenticated_app,
    by_label,
    error_values,
    navigate_to,
)
from tests.fakes import FakeWorkbook


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    with authenticated_app(storage) as app:

        navigate_to(app, "Accounts")
        by_label(app.text_input, "Account name").input("checking")
        by_label(app.selectbox, "Type").set_value("Bank")
        by_label(app.button, "Add account").click().run()
        assert any("unique" in value.casefold() for value in error_values(app))
        assert len(storage.list_accounts(active_only=False)) == 2
        assert by_label(app.text_input, "Account name").value == "checking"
        assert by_label(app.selectbox, "Type").value == "Bank"

        navigate_to(app, "Categories")
        by_label(app.text_input, "Category name").input("sales")
        by_label(app.selectbox, "Type").set_value("Income")
        by_label(app.button, "Add category").click().run()
        assert any("already exists" in value.casefold() for value in error_values(app))
        assert len(storage.list_categories()) == 16
        assert by_label(app.text_input, "Category name").value == "sales"
        assert by_label(app.selectbox, "Type").value == "Income"

        navigate_to(app, "Data & backup")
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

        navigate_to(app, "Reports")
        report_metrics = {metric.label: metric.value for metric in app.metric}
        assert report_metrics == {
            "Income": "$100.00",
            "Expenses": "$40.00",
            "Net": "$60.00",
            "Total assets": "$60.00",
            "Total liabilities": "$0.00",
            "Total equity": "$60.00",
        }
        report_subheaders = {item.value for item in app.subheader}
        assert report_subheaders == {
            "Monthly performance",
            "Expenses by category",
            "Balance sheet",
        }
        assert "Balance sheet is balanced." in {
            item.value for item in app.success
        }

        by_label(app.date_input, "From").set_value(date(2026, 8, 1))
        by_label(app.date_input, "To").set_value(date(2026, 7, 1)).run()
        assert any(
            "From date must be on or before To date" in message
            for message in error_values(app)
        )
        invalid_period_metrics = {
            metric.label: metric.value for metric in app.metric
        }
        assert invalid_period_metrics["Income"] == "$0.00"
        assert invalid_period_metrics["Expenses"] == "$0.00"
        assert invalid_period_metrics["Net"] == "$0.00"

        app.radio[0].set_value("Dashboard").run()
        dashboard_metrics = {metric.label: metric.value for metric in app.metric}
        assert dashboard_metrics["Income this month"] == "$100.00"
        assert dashboard_metrics["Expenses this month"] == "$40.00"
        assert dashboard_metrics["Net this month"] == "$60.00"
        assert dashboard_metrics["Total balance"] == "$60.00"
        dashboard_frames = [frame.value for frame in app.dataframe]
        assert any(
            list(frame.columns)
            == ["Date", "Type", "Payee", "Category", "Account", "Amount"]
            for frame in dashboard_frames
        )
        assert any(
            list(frame.columns) == ["Account", "Classification", "Type", "Balance"]
            for frame in dashboard_frames
        )


if __name__ == "__main__":
    main()
