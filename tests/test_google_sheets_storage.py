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
            "opening_balance",
        )
        workbook = FakeWorkbook(headers)
        storage = GoogleSheetsStorage(workbook)

        created = storage.create_account("Checking", "Bank", 25)
        stored = dict(zip(headers["Accounts"], workbook.sheets["Accounts"].rows[1]))

        self.assertEqual(stored["id"], created["id"])
        self.assertEqual(stored["name"], "Checking")
        self.assertEqual(stored["opening_balance"], "25.00")

    def test_default_seed_is_idempotent(self) -> None:
        first = self.storage.ensure_defaults()
        second = self.storage.ensure_defaults()
        self.assertEqual(first, {"accounts": 2, "categories": 16})
        self.assertEqual(second, {"accounts": 0, "categories": 0})
        self.assertEqual(len(self.storage.list_accounts()), 2)
        self.assertEqual(len(self.storage.list_categories()), 16)

    def test_missing_header_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Categories"] = ("id", "name")
        with self.assertRaises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_account_crud_and_uniqueness(self) -> None:
        created = self.storage.create_account("Checking", "Bank", "100.25")
        self.assertEqual(len(self.storage.list_accounts()), 1)
        with self.assertRaises(StorageConflictError):
            self.storage.create_account("checking", "Cash", 0)

        edited = self.storage.edit_account(
            created["id"], name="Primary checking", opening_balance=-10
        )
        self.assertEqual(edited["name"], "Primary checking")
        self.assertEqual(edited["opening_balance"], "-10.00")

        self.storage.deactivate_account(created["id"])
        self.assertEqual(self.storage.list_accounts(), [])
        self.assertEqual(len(self.storage.list_accounts(active_only=False)), 1)

    def test_category_uniqueness_is_case_insensitive(self) -> None:
        self.storage.create_category("Software", "Expense")
        with self.assertRaises(StorageConflictError):
            self.storage.create_category("software", "Expense")

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

    def test_backup_contains_csv_files_and_manifest(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip()
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"Accounts.csv", "Categories.csv", "Transactions.csv", "manifest.json"},
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["row_counts"]["Accounts"], 1)
            self.assertIn("backup_time", manifest)
            self.assertEqual(manifest["format_version"], 1)
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
        backup = self.storage.export_backup_zip()
        restored_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        counts = restored_storage.restore_backup_zip(backup)

        self.assertEqual(counts, {"Accounts": 1, "Categories": 1, "Transactions": 1})
        self.assertEqual(restored_storage.list_accounts()[0]["id"], account["id"])
        self.assertEqual(restored_storage.list_transactions()[0]["id"], transaction["id"])

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
