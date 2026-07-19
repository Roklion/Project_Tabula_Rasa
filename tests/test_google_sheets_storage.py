from __future__ import annotations

import io
import json
import re
import unittest
import zipfile
from copy import deepcopy

from storage.google_sheets import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
    WORKSHEET_HEADERS,
)


class FakeWorksheet:
    def __init__(self, title: str, headers: tuple[str, ...]):
        self.title = title
        self.rows = [list(headers)]

    def row_values(self, row: int) -> list[str]:
        return list(self.rows[row - 1]) if row <= len(self.rows) else []

    def get_all_values(self) -> list[list[str]]:
        return deepcopy(self.rows)

    def append_row(self, values: list[str], **_: object) -> None:
        self.rows.append(list(values))

    def append_rows(self, values: list[list[str]], **_: object) -> None:
        self.rows.extend(deepcopy(values))

    def update(
        self, values: list[list[str]], range_name: str, **_: object
    ) -> None:
        match = re.fullmatch(r"A(\d+)", range_name)
        if not match:
            raise AssertionError(f"Unexpected range: {range_name}")
        row_index = int(match.group(1)) - 1
        self.rows[row_index] = list(values[0])

    def delete_rows(self, row_number: int) -> None:
        del self.rows[row_number - 1]


class FakeWorkbook:
    title = "Test Ledger"

    def __init__(self, headers: dict[str, tuple[str, ...]] | None = None):
        headers = headers or WORKSHEET_HEADERS
        self.sheets = {
            title: FakeWorksheet(title, columns) for title, columns in headers.items()
        }

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self.sheets.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self.sheets[title]


class GoogleSheetsStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = FakeWorkbook()
        self.storage = GoogleSheetsStorage(self.workbook)

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


if __name__ == "__main__":
    unittest.main()
