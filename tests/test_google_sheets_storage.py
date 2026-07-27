from __future__ import annotations

import io
import json
import unittest
import zipfile
from unittest.mock import Mock

from storage.google_sheets import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    WORKSHEET_HEADERS,
)
from quickbooks_import import (
    general_ledger_rows,
    suggested_account_classification,
    suggested_account_type,
)
from tests.fakes import FakeWorkbook


class GoogleSheetsStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = FakeWorkbook()
        self.storage = GoogleSheetsStorage(self.workbook, sleeper=lambda _: None)

    def test_reordered_headers_are_addressed_by_name(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Accounts"] = (
            "name",
            "id",
            "active",
            "created_at",
            "type",
            "classification",
            "opening_balance",
        )
        workbook = FakeWorkbook(headers)
        storage = GoogleSheetsStorage(workbook)

        created = storage.create_account("Checking", "Bank", 25)
        stored = dict(zip(headers["Accounts"], workbook.sheets["Accounts"].rows[1]))

        self.assertEqual(stored["id"], created["id"])
        self.assertEqual(stored["name"], "Checking")
        self.assertEqual(stored["opening_balance"], "25.00")

    def test_accounts_sheet_without_classification_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Accounts"] = tuple(
            header
            for header in headers["Accounts"]
            if header != "classification"
        )
        with self.assertRaises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_default_seed_is_idempotent(self) -> None:
        first = self.storage.ensure_defaults()
        second = self.storage.ensure_defaults()
        self.assertEqual(first, {"accounts": 2, "categories": 16})
        self.assertEqual(second, {"accounts": 0, "categories": 0})
        self.assertEqual(len(self.storage.list_accounts()), 2)
        self.assertEqual(len(self.storage.list_categories()), 16)

    def test_equity_account_inference_keeps_name_and_type_separate(self) -> None:
        account_type = suggested_account_type("Owners investment")

        self.assertEqual(account_type, "Equity")
        self.assertEqual(
            suggested_account_classification("Owners investment", account_type),
            "Equity",
        )

    def test_missing_header_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Categories"] = ("id", "name")
        with self.assertRaises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_account_crud_and_uniqueness(self) -> None:
        created = self.storage.create_account(
            "Checking", "Bank", "100.25", classification="Asset"
        )
        self.assertEqual(len(self.storage.list_accounts()), 1)
        self.assertEqual(created["classification"], "Asset")
        with self.assertRaises(StorageConflictError):
            self.storage.create_account("checking", "Cash", 0)

        edited = self.storage.edit_account(
            created["id"],
            name="Primary checking",
            type="Short-term debt",
            classification="Liability",
            opening_balance=-10,
        )
        self.assertEqual(edited["name"], "Primary checking")
        self.assertEqual(edited["type"], "Short-term debt")
        self.assertEqual(edited["classification"], "Liability")
        self.assertEqual(edited["opening_balance"], "-10.00")

        self.storage.deactivate_account(created["id"])
        self.assertEqual(self.storage.list_accounts(), [])
        self.assertEqual(len(self.storage.list_accounts(active_only=False)), 1)

    def test_unknown_account_type_is_rejected(self) -> None:
        with self.assertRaises(StorageValidationError):
            self.storage.create_account(
                "Old loan",
                "Loan",
                -100,
                classification="Liability",
            )

    def test_category_uniqueness_is_case_insensitive(self) -> None:
        self.storage.create_category("Software", "Expense")
        with self.assertRaises(StorageConflictError):
            self.storage.create_category("software", "Expense")

    def test_edit_category_name_and_kind(self) -> None:
        category = self.storage.create_category("Consulting", "Income")

        edited = self.storage.edit_category(
            category["id"], name="Professional services", kind="expense"
        )

        self.assertEqual(edited["id"], category["id"])
        self.assertEqual(edited["name"], "Professional services")
        self.assertEqual(edited["kind"], "Expense")
        self.assertEqual(self.storage.list_categories(), [edited])

    def test_edit_category_rejects_duplicate_name_and_kind(self) -> None:
        first = self.storage.create_category("Services", "Income")
        self.storage.create_category("services", "Expense")

        with self.assertRaises(StorageConflictError):
            self.storage.edit_category(first["id"], kind="Expense")

    def test_category_and_transaction_crud(self) -> None:
        source = self.storage.create_account("Checking", "Bank")
        destination = self.storage.create_account("Savings", "Bank")
        expense = self.storage.create_category("Software", "Expense")
        income = self.storage.create_category("Sales", "Income")

        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=source["id"],
            category_id=expense["id"],
            payee="Vendor",
        )
        self.assertEqual(transaction["amount"], "12.50")
        self.assertEqual(len(self.storage.list_transactions()), 1)

        edited = self.storage.edit_transaction(
            transaction["id"],
            kind="Income",
            amount=20,
            category_id=income["id"],
            payee="Customer",
        )
        self.assertEqual(edited["kind"], "Income")
        self.assertEqual(edited["created_at"], transaction["created_at"])

        transfer = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Transfer",
            amount=5,
            account_id=source["id"],
            to_account_id=destination["id"],
        )
        self.assertEqual(transfer["category_id"], "")
        self.assertEqual(
            [item["id"] for item in self.storage.list_transactions(
                account_ids=[destination["id"]]
            )],
            [transfer["id"]],
        )
        self.assertEqual(
            {
                item["id"]
                for item in self.storage.list_transactions(
                    account_ids=[source["id"], destination["id"]]
                )
            },
            {transaction["id"], transfer["id"]},
        )

        self.storage.delete_transaction(transaction["id"])
        with self.assertRaises(StorageNotFoundError):
            self.storage.edit_transaction(transaction["id"], amount=1)

    def test_invalid_transfer_and_category_reference_are_rejected(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Sales", "Income")
        with self.assertRaises(StorageValidationError):
            self.storage.create_transaction(
                txn_date="2026-07-19",
                kind="Transfer",
                amount=1,
                account_id=account["id"],
                to_account_id=account["id"],
            )
        with self.assertRaises(StorageValidationError):
            self.storage.create_transaction(
                txn_date="2026-07-19",
                kind="Expense",
                amount=1,
                account_id=account["id"],
                category_id=category["id"],
            )

    def test_mileage_trip_crud_filtering_and_validation(self) -> None:
        first = self.storage.create_mileage_trip(
            trip_date="2026-07-18",
            miles="12.34",
            vehicle="Blue car",
            start_location="Office",
            destination="Client site",
            business_purpose="Project meeting",
            notes="Tolls paid separately",
        )
        second = self.storage.create_mileage_trip(
            trip_date="2026-07-20",
            miles=5,
            start_location="Client site",
            destination="Office",
            business_purpose="Return trip",
        )

        self.assertEqual(first["miles"], "12.3")
        self.assertEqual(
            [trip["id"] for trip in self.storage.list_mileage_trips()],
            [second["id"], first["id"]],
        )
        self.assertEqual(
            [trip["id"] for trip in self.storage.list_mileage_trips(end="2026-07-19")],
            [first["id"]],
        )

        edited = self.storage.edit_mileage_trip(
            first["id"],
            miles=14.2,
            destination="Updated client site",
        )
        self.assertEqual(edited["miles"], "14.2")
        self.assertEqual(edited["created_at"], first["created_at"])

        self.storage.delete_mileage_trip(second["id"])
        self.assertEqual(
            [trip["id"] for trip in self.storage.list_mileage_trips()],
            [first["id"]],
        )
        with self.assertRaises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=0,
                start_location="Office",
                destination="Client",
                business_purpose="Meeting",
            )
        with self.assertRaises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=1,
                start_location="Office",
                destination="",
                business_purpose="Meeting",
            )

    def test_quickbooks_mileage_preview_import_and_duplicates(self) -> None:
        business = {
            "Date": "07/20/2026",
            "Type": "Business",
            "Trip Purpose": "Client meeting",
            "Vehicle": "Blue car",
            "Start Address": "Office",
            "End Address": "Client site",
            "Distance": "12.4",
            "Deduction": "8.68",
            "Logging Method": "Auto-tracked",
        }
        personal = {
            **business,
            "Date": "07/21/2026",
            "Type": "Personal",
            "Trip Purpose": "",
        }
        unreviewed = {
            **business,
            "Date": "07/22/2026",
            "Type": "",
            "Trip Purpose": "",
        }
        invalid = {
            **business,
            "Date": "07/23/2026",
            "Trip Purpose": "",
        }

        blocked = self.storage.preview_quickbooks_mileage(
            [business, personal, unreviewed, invalid]
        )
        self.assertEqual(blocked["summary"]["ready"], 1)
        self.assertEqual(blocked["summary"]["personal_skipped"], 1)
        self.assertEqual(blocked["summary"]["unreviewed_skipped"], 1)
        self.assertEqual(len(blocked["errors"]), 1)
        with self.assertRaises(StorageValidationError):
            self.storage.import_quickbooks_mileage(
                [business, personal, unreviewed, invalid]
            )
        self.assertEqual(self.storage.list_mileage_trips(), [])

        preview = self.storage.preview_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        self.assertEqual(
            preview["summary"],
            {
                "ready": 1,
                "duplicates": 1,
                "personal_skipped": 1,
                "unreviewed_skipped": 1,
            },
        )
        self.assertEqual(preview["duplicate_rows"], [3])

        imported = self.storage.import_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["miles"], "12.4")
        self.assertEqual(imported[0]["business_purpose"], "Client meeting")

        repeated = self.storage.preview_quickbooks_mileage([business])
        self.assertEqual(repeated["summary"]["ready"], 0)
        self.assertEqual(repeated["duplicate_rows"], [2])

    def test_csv_import_validates_all_rows_before_batch_append(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_category("Sales", "Income")
        rows = [
            {
                "Date": "2026-07-18",
                "Type": "Income",
                "Amount": "10",
                "Account": "Checking",
                "Category": "Sales",
            },
            {
                "Date": "2026-07-19",
                "Type": "Income",
                "Amount": "20",
                "Account": "Missing",
                "Category": "Sales",
            },
        ]
        with self.assertRaises(StorageValidationError):
            self.storage.import_csv_transactions(rows)
        self.assertEqual(self.storage.list_transactions(), [])

        imported = self.storage.import_csv_transactions(rows[:1])
        self.assertEqual(len(imported), 1)
        self.assertEqual(len(self.storage.list_transactions()), 1)

    def test_quickbooks_preview_maps_income_expense_transfer_and_duplicates(self) -> None:
        checking = self.storage.create_account("Checking", "Bank")
        savings = self.storage.create_account("Savings", "Bank")
        self.storage.create_category("Sales", "Income")
        self.storage.create_category("Office", "Expense")
        rows = [
            {"Date": "07/01/2026", "Transaction Type": "Deposit", "Num": "1", "Name": "Client", "Memo/Description": "Invoice", "Account": "Checking", "Split": "Sales", "Amount": "125.00"},
            {"Date": "07/02/2026", "Transaction Type": "Expense", "Num": "2", "Name": "Shop", "Memo/Description": "Paper", "Account": "Checking", "Split": "Office", "Amount": "(20.50)"},
            {"Date": "07/03/2026", "Transaction Type": "Transfer", "Num": "3", "Name": "", "Memo/Description": "Reserve", "Account": "Checking", "Split": "Savings", "Amount": "50"},
        ]
        preview = self.storage.preview_quickbooks_transactions(rows)
        self.assertEqual(preview["summary"], {"ready": 3, "duplicates": 0, "Income": 1, "Expense": 1, "Transfer": 1})
        imported = self.storage.import_quickbooks_transactions(rows)
        self.assertEqual([item["kind"] for item in imported], ["Income", "Expense", "Transfer"])
        self.assertEqual(imported[2]["account_id"], checking["id"])
        self.assertEqual(imported[2]["to_account_id"], savings["id"])
        duplicate_preview = self.storage.preview_quickbooks_transactions(rows + rows[:1])
        self.assertEqual(duplicate_preview["summary"]["ready"], 0)
        self.assertEqual(duplicate_preview["summary"]["duplicates"], 4)

    def test_quickbooks_account_splits_become_sign_aware_transfers(self) -> None:
        checking = self.storage.create_account("Checking", "Bank")
        investment = self.storage.create_account(
            "Owners investment", "Equity"
        )
        owners_pay = self.storage.create_account("Owners pay", "Equity")
        rows = [
            {
                "Date": "07/01/2026",
                "Transaction Type": "Deposit",
                "Num": "1",
                "Name": "Owner",
                "Memo/Description": "Contribution",
                "Account": "Checking",
                "Split": "Owners investment",
                "Amount": "100.00",
            },
            {
                "Date": "07/02/2026",
                "Transaction Type": "Check",
                "Num": "2",
                "Name": "Owner",
                "Memo/Description": "Draw",
                "Account": "Checking",
                "Split": "Owners\u00a0pay",
                "Amount": "(25.00)",
            },
        ]

        preview = self.storage.preview_quickbooks_transactions(rows)

        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["new_categories"], [])
        self.assertEqual(
            [
                (row["kind"], row["account_id"], row["to_account_id"])
                for row in preview["rows"]
            ],
            [
                ("Transfer", investment["id"], checking["id"]),
                ("Transfer", checking["id"], owners_pay["id"]),
            ],
        )

    def test_quickbooks_auto_creates_missing_owner_pay_as_equity_account(self) -> None:
        checking = self.storage.create_account("Checking", "Bank")
        rows = [
            {
                "Date": "07/02/2026",
                "Transaction Type": "Check",
                "Num": "2",
                "Name": "Owner",
                "Memo/Description": "Draw",
                "Account": "Checking",
                "Split": "Owners pay",
                "Amount": "(25.00)",
            }
        ]

        strict = self.storage.preview_quickbooks_transactions(rows)
        preview = self.storage.preview_quickbooks_transactions(
            rows, auto_create=True
        )

        self.assertEqual(strict["new_accounts"], ["Owners pay"])
        self.assertEqual(strict["new_categories"], [])
        self.assertIn("destination account", strict["errors"][0])
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["new_account_types"], {"Owners pay": "Equity"})
        self.assertEqual(
            preview["new_account_classifications"],
            {"Owners pay": "Equity"},
        )
        self.assertEqual(preview["rows"][0]["kind"], "Transfer")
        self.assertEqual(preview["rows"][0]["account_id"], checking["id"])
        self.assertEqual(
            preview["rows"][0]["to_account_id"],
            "pending-account:owners pay",
        )

    def test_quickbooks_import_reports_all_errors_and_writes_nothing(self) -> None:
        self.storage.create_account("Checking", "Bank")
        rows = [
            {"Date": "bad", "Transaction Type": "Deposit", "Num": "", "Name": "", "Memo/Description": "", "Account": "Checking", "Split": "Missing", "Amount": "10"},
            {"Date": "07/02/2026", "Transaction Type": "Transfer", "Num": "", "Name": "", "Memo/Description": "", "Account": "Missing", "Split": "Checking", "Amount": "1"},
        ]
        preview = self.storage.preview_quickbooks_transactions(rows)
        self.assertEqual(len(preview["errors"]), 2)
        with self.assertRaises(StorageValidationError):
            self.storage.import_quickbooks_transactions(rows)
        self.assertEqual(self.storage.list_transactions(), [])

    def test_quickbooks_import_can_create_missing_references(self) -> None:
        rows = [
            {"Date": "07/01/2026", "Transaction Type": "Deposit", "Num": "1", "Name": "Client", "Memo/Description": "Invoice", "Account": "Operating", "Split": "Consulting", "Amount": "100"},
            {"Date": "07/02/2026", "Transaction Type": "Transfer", "Num": "2", "Name": "", "Memo/Description": "Reserve", "Account": "Operating", "Split": "Savings", "Amount": "25"},
        ]
        strict = self.storage.preview_quickbooks_transactions(rows)
        self.assertTrue(strict["errors"])
        preview = self.storage.preview_quickbooks_transactions(rows, auto_create=True)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["new_accounts"], ["Operating", "Savings"])
        self.assertEqual(preview["new_account_types"], {"Operating": "Other", "Savings": "Bank"})
        self.assertEqual(
            preview["new_account_classifications"],
            {"Operating": "Asset", "Savings": "Asset"},
        )
        self.assertEqual(preview["new_categories"], [("Consulting", "Income")])
        imported = self.storage.import_quickbooks_transactions(rows, auto_create=True)
        self.assertEqual(len(imported), 2)
        self.assertEqual(
            [(item["name"], item["type"]) for item in self.storage.list_accounts()],
            [("Operating", "Other"), ("Savings", "Bank")],
        )
        self.assertEqual(
            [(item["name"], item["kind"]) for item in self.storage.list_categories()],
            [("Consulting", "Income")],
        )

    def test_quickbooks_batch_import_reuses_reference_reads(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_category("Sales", "Income")
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_sheet.get_all_values = Mock(
            wraps=account_sheet.get_all_values
        )
        category_sheet.get_all_values = Mock(
            wraps=category_sheet.get_all_values
        )
        rows = [
            {
                "Date": "07/01/2026",
                "Transaction Type": "Deposit",
                "Num": str(index),
                "Name": "Client",
                "Memo/Description": "Invoice",
                "Account": "Checking",
                "Split": "Sales",
                "Amount": "1.00",
            }
            for index in range(35)
        ]

        imported = self.storage.import_quickbooks_transactions(rows)

        self.assertEqual(len(imported), 35)
        self.assertEqual(account_sheet.get_all_values.call_count, 1)
        self.assertEqual(category_sheet.get_all_values.call_count, 1)

    def test_general_ledger_export_collapses_double_entries(self) -> None:
        matrix = [
            ["Example LLC"],
            [None, "Date", "Transaction Type", "Num", "Name", "Memo/Description", "Account", "Debit", "Credit", "Balance"],
            [None, "06/01/2026", "Transfer", "", "", "Reserve", "Checking", "", 50, 950],
            [None, "06/01/2026", "Transfer", "", "", "Reserve", "Savings", 50, "", 50],
            [None, "06/02/2026", "Deposit", "1", "Client", "Invoice", "Checking", 100, "", 1050],
            [None, "06/02/2026", "Deposit", "1", "Client", "Invoice", "Services", "", 100, 100],
            [None, "06/03/2026", "Expense", "2", "", "Paper", "Checking", "", 10, 1040],
            [None, "06/03/2026", "Expense", "2", "Store", "Paper", "Office", 10, "", 10],
        ]
        rows, errors = general_ledger_rows(matrix)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0]["Account"], rows[0]["Split"], rows[0]["Transaction Type"]), ("Checking", "Savings", "Transfer"))
        self.assertEqual((rows[1]["Split"], rows[1]["Amount"]), ("Services", "100.00"))
        self.assertEqual((rows[2]["Name"], rows[2]["Split"], rows[2]["Amount"]), ("Store", "Office", "-10.00"))

    def test_backup_contains_csv_files_and_manifest(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_mileage_trip(
            trip_date="2026-07-20",
            miles=4.5,
            start_location="Office",
            destination="Bank",
            business_purpose="Deposit",
        )
        backup = self.storage.export_backup_zip()
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "Accounts.csv",
                    "Categories.csv",
                    "Transactions.csv",
                    "Mileage.csv",
                    "manifest.json",
                },
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["row_counts"]["Accounts"], 1)
            self.assertEqual(manifest["row_counts"]["Mileage"], 1)
            self.assertIn("backup_time", manifest)
            self.assertEqual(manifest["format_version"], 3)
            self.assertIn("Accounts.csv", manifest["sha256"])
        validated = self.storage.validate_backup_zip(backup)
        self.assertEqual(validated["workbook_title"], "Test Ledger")

    def test_backup_forces_fresh_worksheet_reads(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        headers = self.workbook.sheets["Accounts"].rows[0]
        self.workbook.sheets["Accounts"].rows[1][headers.index("name")] = "External"

        backup = self.storage.export_backup_zip()

        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertIn(account["id"], archive.read("Accounts.csv").decode("utf-8"))
            self.assertIn("External", archive.read("Accounts.csv").decode("utf-8"))

    def test_restore_backup_into_blank_workbook_and_verify_rows(self) -> None:
        account = self.storage.create_account("Checking", "Bank", 125)
        category = self.storage.create_category("Sales", "Income")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Income",
            amount=25,
            account_id=account["id"],
            category_id=category["id"],
            payee="Customer",
        )
        mileage = self.storage.create_mileage_trip(
            trip_date="2026-07-19",
            miles=8.4,
            start_location="Office",
            destination="Customer",
            business_purpose="Sales meeting",
        )
        backup = self.storage.export_backup_zip()
        restored_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        counts = restored_storage.restore_backup_zip(backup)

        self.assertEqual(
            counts,
            {"Accounts": 1, "Categories": 1, "Transactions": 1, "Mileage": 1},
        )
        self.assertEqual(restored_storage.list_accounts()[0]["id"], account["id"])
        self.assertEqual(restored_storage.list_transactions()[0]["id"], transaction["id"])
        self.assertEqual(restored_storage.list_mileage_trips()[0]["id"], mileage["id"])

    def test_restore_accepts_pre_mileage_backup(self) -> None:
        self.storage.create_account("Checking", "Bank")
        current_backup = self.storage.export_backup_zip()
        legacy_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(current_backup)) as source:
            manifest = json.loads(source.read("manifest.json"))
            manifest["format_version"] = 2
            manifest["row_counts"].pop("Mileage")
            manifest["worksheet_headers"].pop("Mileage")
            manifest["sha256"].pop("Mileage.csv")
            with zipfile.ZipFile(legacy_buffer, "w") as legacy:
                for name in (
                    "Accounts.csv",
                    "Categories.csv",
                    "Transactions.csv",
                ):
                    legacy.writestr(name, source.read(name))
                legacy.writestr("manifest.json", json.dumps(manifest))

        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        counts = target.restore_backup_zip(legacy_buffer.getvalue())

        self.assertEqual(
            counts,
            {"Accounts": 1, "Categories": 0, "Transactions": 0},
        )
        self.assertEqual(target.list_mileage_trips(), [])

        nonblank_target = GoogleSheetsStorage(
            FakeWorkbook(), sleeper=lambda _: None
        )
        nonblank_target.create_mileage_trip(
            trip_date="2026-07-20",
            miles=2,
            start_location="Office",
            destination="Bank",
            business_purpose="Deposit",
        )
        with self.assertRaises(StorageConflictError):
            nonblank_target.restore_backup_zip(legacy_buffer.getvalue())

    def test_restore_refuses_nonblank_target(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip()
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        target.create_account("Existing", "Cash")

        with self.assertRaises(StorageConflictError):
            target.restore_backup_zip(backup)

    def test_restore_rejects_tampered_csv(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip()
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
            output, "w"
        ) as destination:
            for name in source.namelist():
                content = source.read(name)
                if name == "Accounts.csv":
                    content += b"tampered,row\n"
                destination.writestr(name, content)

        with self.assertRaises(StorageValidationError):
            self.storage.validate_backup_zip(output.getvalue())

    def test_temporary_api_failure_returns_safe_error(self) -> None:
        self.workbook.sheets["Accounts"].get_all_values = Mock(
            side_effect=OSError("credential-content-must-not-leak")
        )
        with self.assertRaises(StorageUnavailableError) as raised:
            self.storage.list_accounts()
        self.assertEqual(
            str(raised.exception),
            "Google Sheets is temporarily unavailable; no success was reported",
        )
        self.assertNotIn("credential-content", str(raised.exception))

    def test_reads_are_cached_and_invalidated_after_write(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original = worksheet.get_all_values
        worksheet.get_all_values = Mock(wraps=original)

        self.storage.list_accounts(active_only=False)
        self.storage.list_accounts(active_only=False)
        self.assertEqual(worksheet.get_all_values.call_count, 1)

        self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        self.assertEqual(worksheet.get_all_values.call_count, 3)

    def test_edit_forces_reread_before_replacing_row(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        headers = self.workbook.sheets["Accounts"].rows[0]
        name_index = headers.index("name")
        self.workbook.sheets["Accounts"].rows[1][name_index] = "Externally renamed"

        edited = self.storage.edit_account(account["id"], type="Cash")

        self.assertEqual(edited["name"], "Externally renamed")
        self.assertEqual(edited["type"], "Cash")

    def test_temporary_failure_retries_with_exponential_backoff(self) -> None:
        delays: list[float] = []
        storage = GoogleSheetsStorage(
            self.workbook,
            retry_attempts=4,
            retry_base_delay_seconds=0.25,
            sleeper=delays.append,
        )
        worksheet = self.workbook.sheets["Accounts"]
        successful_values = worksheet.get_all_values()
        worksheet.get_all_values = Mock(
            side_effect=[OSError("temporary"), OSError("temporary"), successful_values]
        )

        storage.list_accounts(active_only=False, _force_refresh=True)

        self.assertEqual(delays, [0.25, 0.5])
        self.assertEqual(worksheet.get_all_values.call_count, 3)

    def test_lost_append_response_is_confirmed_by_uuid_without_duplicate(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original_append = worksheet.append_row

        def commit_then_timeout(values: list[str], **kwargs: object) -> None:
            original_append(values, **kwargs)
            raise OSError("response lost after commit")

        worksheet.append_row = Mock(side_effect=commit_then_timeout)

        created = self.storage.create_account("Checking", "Bank")

        accounts = self.storage.list_accounts(active_only=False)
        self.assertEqual([account["id"] for account in accounts], [created["id"]])
        self.assertEqual(worksheet.append_row.call_count, 1)

    def test_lost_delete_response_does_not_delete_following_row(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Software", "Expense")
        first = self.storage.create_transaction(
            txn_date="2026-07-18",
            kind="Expense",
            amount=1,
            account_id=account["id"],
            category_id=category["id"],
        )
        second = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount=2,
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.sheets["Transactions"]
        original_delete = worksheet.delete_rows

        def commit_then_timeout(row_number: int) -> None:
            original_delete(row_number)
            raise OSError("response lost after commit")

        worksheet.delete_rows = Mock(side_effect=commit_then_timeout)

        self.storage.delete_transaction(first["id"])

        remaining_ids = {
            transaction["id"] for transaction in self.storage.list_transactions()
        }
        self.assertEqual(remaining_ids, {second["id"]})
        self.assertEqual(worksheet.delete_rows.call_count, 1)


if __name__ == "__main__":
    unittest.main()
