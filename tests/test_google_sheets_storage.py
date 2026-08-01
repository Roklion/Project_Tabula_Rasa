from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from unittest.mock import Mock, patch

import gspread
import pytest
from google.oauth2.service_account import Credentials

from tabula_rasa.storage.google_sheets import (
    BACKUP_FORMAT_VERSION,
    decode_receipt_references,
    GoogleSheetsStorage,
    SHEETS_SCOPE,
    StorageAuthenticationError,
    StorageConflictError,
    StorageInitializationError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    StorageWorkbookAccessError,
    VERSION_3_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
from tabula_rasa.quickbooks_import import (
    general_ledger_rows,
    suggested_account_classification,
    suggested_account_type,
)
from tabula_rasa.receipt_manifest import (
    build_receipt_manifest,
    ReceiptManifestError,
)
from tests.fakes import FakeWorkbook


TEST_RECEIPT_REFERENCE = {
    "id": "receipt123456",
    "name": "customer-receipt.pdf",
    "receipt_id": "a" * 32,
    "original_filename": "customer-receipt.pdf",
    "mime_type": "application/pdf",
    "byte_size": 7,
    "sha256": "b" * 64,
}


def drive_file_from_reference(
    reference: dict[str, object],
    *,
    profile_key: str = "test",
) -> dict[str, object]:
    return {
        "id": reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": reference["receipt_id"],
            "tabulaRasaSha256": reference["sha256"],
            "tabulaRasaOriginalName": reference["original_filename"],
        },
    }


def backup_receipt_manifest(storage: GoogleSheetsStorage) -> dict[str, object]:
    transactions = storage.list_transactions(_force_refresh=True)
    files = []
    for transaction in transactions:
        for reference in decode_receipt_references(
            transaction.get("receipt_references", "")
        ):
            if "receipt_id" not in reference:
                continue
            files.append(drive_file_from_reference(reference))
    return build_receipt_manifest("test", transactions, files)


class TestGoogleSheetsStorage:
    def setup_method(self) -> None:
        self.workbook = FakeWorkbook()
        self.storage = GoogleSheetsStorage(self.workbook, sleeper=lambda _: None)

    def test_profile_storage_initializes_tabs_and_headers_by_spreadsheet_id(
        self,
    ) -> None:
        workbook = FakeWorkbook({"Sheet1": (), "Accounts": ()})
        workbook.worksheets = Mock(wraps=workbook.worksheets)
        workbook.sheets["Accounts"].get_all_values = Mock(
            wraps=workbook.sheets["Accounts"].get_all_values
        )
        workbook.sheets["Accounts"].row_values = Mock(
            wraps=workbook.sheets["Accounts"].row_values
        )
        google_client = Mock()
        google_client.open_by_key.return_value = workbook
        credential_info = {"type": "service_account"}

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ) as from_service_account_info,
            patch.object(gspread, "authorize", return_value=google_client),
        ):
            storage = GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": credential_info,
                }
            )

        google_client.open_by_key.assert_called_once_with(
            "given-spreadsheet-id"
        )
        from_service_account_info.assert_called_once_with(
            credential_info, scopes=[SHEETS_SCOPE]
        )
        assert storage.workbook_title == workbook.title
        assert workbook.worksheets.call_count == 1
        assert workbook.sheets["Accounts"].get_all_values.call_count == 1
        assert workbook.sheets["Accounts"].row_values.call_count == 0
        assert workbook.sheets["Sheet1"].rows == [[]]
        for title, headers in WORKSHEET_HEADERS.items():
            assert workbook.sheets[title].rows == [list(headers)]

    def test_profile_storage_does_not_overwrite_incompatible_tab(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Accounts"] = ("legacy_id", "legacy_name")
        workbook = FakeWorkbook(headers)
        google_client = Mock()
        google_client.open_by_key.return_value = workbook

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ),
            patch.object(gspread, "authorize", return_value=google_client),
            pytest.raises(StorageValidationError),
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        assert workbook.sheets["Accounts"].rows == [
            ["legacy_id", "legacy_name"]
        ]

    def test_profile_storage_adds_receipt_references_to_existing_transactions(
        self,
    ) -> None:
        workbook = FakeWorkbook(VERSION_3_WORKSHEET_HEADERS)
        transaction_sheet = workbook.sheets["Transactions"]
        transaction_sheet.rows.append(
            ["txn-1", "2026-07-28", "Expense"]
        )
        google_client = Mock()
        google_client.open_by_key.return_value = workbook

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ),
            patch.object(gspread, "authorize", return_value=google_client),
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        assert transaction_sheet.rows[0] == [
            *VERSION_3_WORKSHEET_HEADERS["Transactions"],
            "receipt_references",
        ]
        assert transaction_sheet.rows[1][-1] == ""

    def test_profile_storage_reports_invalid_credential_safely(self) -> None:
        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                side_effect=ValueError("credential-content-must-not-leak"),
            ),
            pytest.raises(StorageAuthenticationError) as raised,
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        assert "credential-content-must-not-leak" not in str(raised.value)
        assert (
            str(raised.value)
            == "Google rejected the uploaded service-account credential"
        )

    def test_profile_storage_reports_inaccessible_workbook(self) -> None:
        google_client = Mock()
        google_client.open_by_key.side_effect = gspread.SpreadsheetNotFound()

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ),
            patch.object(gspread, "authorize", return_value=google_client),
            pytest.raises(StorageWorkbookAccessError, match="could not be opened"),
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

    def test_profile_storage_reports_initialization_permission_failure(
        self,
    ) -> None:
        workbook = FakeWorkbook(
            {title: () for title in WORKSHEET_HEADERS}
        )
        workbook.sheets["Accounts"].update = Mock(
            side_effect=PermissionError
        )
        google_client = Mock()
        google_client.open_by_key.return_value = workbook

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ),
            patch.object(gspread, "authorize", return_value=google_client),
            pytest.raises(
                StorageInitializationError,
                match="worksheet initialization failed",
            ),
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

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

        assert stored["id"] == created["id"]
        assert stored["name"] == "Checking"
        assert stored["opening_balance"] == "25.00"

    def test_accounts_sheet_without_classification_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Accounts"] = tuple(
            header for header in headers["Accounts"] if header != "classification"
        )
        with pytest.raises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_default_seed_is_idempotent(self) -> None:
        first = self.storage.ensure_defaults()
        second = self.storage.ensure_defaults()
        assert first == {"accounts": 2, "categories": 16}
        assert second == {"accounts": 0, "categories": 0}
        assert len(self.storage.list_accounts()) == 2
        assert len(self.storage.list_categories()) == 16

    def test_equity_account_inference_keeps_name_and_type_separate(self) -> None:
        account_type = suggested_account_type("Owners investment")

        assert account_type == "Equity"
        assert (
            suggested_account_classification("Owners investment", account_type)
            == "Equity"
        )

    def test_missing_header_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Categories"] = ("id", "name")
        with pytest.raises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_account_crud_and_uniqueness(self) -> None:
        created = self.storage.create_account(
            "Checking", "Bank", "100.25", classification="Asset"
        )
        assert len(self.storage.list_accounts()) == 1
        assert created["classification"] == "Asset"
        with pytest.raises(StorageConflictError):
            self.storage.create_account("checking", "Cash", 0)

        edited = self.storage.edit_account(
            created["id"],
            name="Primary checking",
            type="Short-term debt",
            classification="Liability",
            opening_balance=-10,
        )
        assert edited["name"] == "Primary checking"
        assert edited["type"] == "Short-term debt"
        assert edited["classification"] == "Liability"
        assert edited["opening_balance"] == "-10.00"

        self.storage.deactivate_account(created["id"])
        assert self.storage.list_accounts() == []
        assert len(self.storage.list_accounts(active_only=False)) == 1

    def test_unknown_account_type_is_rejected(self) -> None:
        with pytest.raises(StorageValidationError):
            self.storage.create_account(
                "Old loan",
                "Loan",
                -100,
                classification="Liability",
            )

    def test_category_uniqueness_is_case_insensitive(self) -> None:
        self.storage.create_category("Software", "Expense")
        with pytest.raises(StorageConflictError):
            self.storage.create_category("software", "Expense")

    def test_edit_category_name_and_kind(self) -> None:
        category = self.storage.create_category("Consulting", "Income")

        edited = self.storage.edit_category(
            category["id"], name="Professional services", kind="expense"
        )

        assert edited["id"] == category["id"]
        assert edited["name"] == "Professional services"
        assert edited["kind"] == "Expense"
        assert self.storage.list_categories() == [edited]

    def test_edit_category_rejects_duplicate_name_and_kind(self) -> None:
        first = self.storage.create_category("Services", "Income")
        self.storage.create_category("services", "Expense")

        with pytest.raises(StorageConflictError):
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
        assert transaction["amount"] == "12.50"
        assert len(self.storage.list_transactions()) == 1

        edited = self.storage.edit_transaction(
            transaction["id"],
            kind="Income",
            amount=20,
            category_id=income["id"],
            payee="Customer",
        )
        assert edited["kind"] == "Income"
        assert edited["created_at"] == transaction["created_at"]

        transfer = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Transfer",
            amount=5,
            account_id=source["id"],
            to_account_id=destination["id"],
        )
        assert transfer["category_id"] == ""
        assert [
            item["id"]
            for item in self.storage.list_transactions(account_ids=[destination["id"]])
        ] == [transfer["id"]]
        assert {
            item["id"]
            for item in self.storage.list_transactions(
                account_ids=[source["id"], destination["id"]]
            )
        } == {transaction["id"], transfer["id"]}

        self.storage.delete_transaction(transaction["id"])
        with pytest.raises(StorageNotFoundError):
            self.storage.edit_transaction(transaction["id"], amount=1)

    def test_transaction_receipt_references_can_be_linked_and_unlinked(
        self,
    ) -> None:
        source = self.storage.create_account("Checking", "Bank")
        expense = self.storage.create_category("Software", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=source["id"],
            category_id=expense["id"],
        )
        assert decode_receipt_references(
            transaction["receipt_references"]
        ) == []

        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
            name="statement.pdf",
        )
        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
            name="renamed-statement.pdf",
        )
        self.storage.link_transaction_receipt(
            transaction["id"],
            file_id="receipt234567",
            name="invoice.png",
        )
        linked = self.storage.list_transactions()[0]
        assert decode_receipt_references(
            linked["receipt_references"]
        ) == [
            {"id": "receipt123456", "name": "renamed-statement.pdf"},
            {"id": "receipt234567", "name": "invoice.png"},
        ]
        other_transaction = self.storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=8,
            account_id=source["id"],
            category_id=expense["id"],
        )
        with pytest.raises(
            StorageConflictError,
            match="already linked to another transaction",
        ):
            self.storage.link_transaction_receipt(
                other_transaction["id"],
                file_id="receipt123456",
                name="renamed-statement.pdf",
            )

        self.storage.unlink_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
        )

        unlinked = next(
            item
            for item in self.storage.list_transactions()
            if item["id"] == transaction["id"]
        )
        assert decode_receipt_references(
            unlinked["receipt_references"]
        ) == [{"id": "receipt234567", "name": "invoice.png"}]
        assert unlinked["id"] == transaction["id"]

    def test_transaction_receipt_reference_validation_is_strict(self) -> None:
        with pytest.raises(
            StorageValidationError,
            match="receipt references are invalid",
        ):
            decode_receipt_references(
                [{"id": "../not-a-drive-id", "name": "receipt.pdf"}]
            )

    def test_invalid_transfer_and_category_reference_are_rejected(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Sales", "Income")
        with pytest.raises(StorageValidationError):
            self.storage.create_transaction(
                txn_date="2026-07-19",
                kind="Transfer",
                amount=1,
                account_id=account["id"],
                to_account_id=account["id"],
            )
        with pytest.raises(StorageValidationError):
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

        assert first["miles"] == "12.3"
        assert [trip["id"] for trip in self.storage.list_mileage_trips()] == [
            second["id"],
            first["id"],
        ]
        assert [
            trip["id"] for trip in self.storage.list_mileage_trips(end="2026-07-19")
        ] == [first["id"]]

        edited = self.storage.edit_mileage_trip(
            first["id"],
            miles=14.2,
            destination="Updated client site",
        )
        assert edited["miles"] == "14.2"
        assert edited["created_at"] == first["created_at"]

        self.storage.delete_mileage_trip(second["id"])
        assert [trip["id"] for trip in self.storage.list_mileage_trips()] == [
            first["id"]
        ]
        with pytest.raises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=0,
                start_location="Office",
                destination="Client",
                business_purpose="Meeting",
            )
        with pytest.raises(StorageValidationError):
            self.storage.create_mileage_trip(
                trip_date="2026-07-20",
                miles=1,
                start_location="Office",
                destination="",
                business_purpose="Meeting",
            )

    def test_mileage_round_trip_creates_reversed_entries_in_one_batch(self) -> None:
        worksheet = self.workbook.sheets["Mileage"]
        original_append_many = worksheet.append_rows
        worksheet.append_rows = Mock(wraps=original_append_many)

        records = self.storage.create_mileage_round_trip(
            trip_date="2026-07-20",
            miles=12.6,
            vehicle="Blue car",
            start_location="Office",
            destination="Client site",
            business_purpose="Project meeting",
            notes="Parking receipt saved",
        )

        assert len(records) == 2
        assert worksheet.append_rows.call_count == 1
        assert records[0]["id"] != records[1]["id"]
        assert records[0]["created_at"] == records[1]["created_at"]
        assert [
            (
                record["start_location"],
                record["destination"],
                record["miles"],
            )
            for record in records
        ] == [
            ("Office", "Client site", "12.6"),
            ("Client site", "Office", "12.6"),
        ]
        assert {record["business_purpose"] for record in records} == {"Project meeting"}
        assert len(self.storage.list_mileage_trips()) == 2

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
        assert blocked["summary"]["ready"] == 1
        assert blocked["summary"]["personal_skipped"] == 1
        assert blocked["summary"]["unreviewed_skipped"] == 1
        assert len(blocked["errors"]) == 1
        with pytest.raises(StorageValidationError):
            self.storage.import_quickbooks_mileage(
                [business, personal, unreviewed, invalid]
            )
        assert self.storage.list_mileage_trips() == []

        preview = self.storage.preview_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        assert preview["summary"] == {
            "ready": 1,
            "duplicates": 1,
            "personal_skipped": 1,
            "unreviewed_skipped": 1,
        }
        assert preview["duplicate_rows"] == [3]

        imported = self.storage.import_quickbooks_mileage(
            [business, business, personal, unreviewed]
        )
        assert len(imported) == 1
        assert imported[0]["miles"] == "12.4"
        assert imported[0]["business_purpose"] == "Client meeting"

        repeated = self.storage.preview_quickbooks_mileage([business])
        assert repeated["summary"]["ready"] == 0
        assert repeated["duplicate_rows"] == [2]

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
        with pytest.raises(StorageValidationError):
            self.storage.import_csv_transactions(rows)
        assert self.storage.list_transactions() == []

        imported = self.storage.import_csv_transactions(rows[:1])
        assert len(imported) == 1
        assert len(self.storage.list_transactions()) == 1

    def test_quickbooks_preview_maps_income_expense_transfer_and_duplicates(
        self,
    ) -> None:
        checking = self.storage.create_account("Checking", "Bank")
        savings = self.storage.create_account("Savings", "Bank")
        self.storage.create_category("Sales", "Income")
        self.storage.create_category("Office", "Expense")
        rows = [
            {
                "Date": "07/01/2026",
                "Transaction Type": "Deposit",
                "Num": "1",
                "Name": "Client",
                "Memo/Description": "Invoice",
                "Account": "Checking",
                "Split": "Sales",
                "Amount": "125.00",
            },
            {
                "Date": "07/02/2026",
                "Transaction Type": "Expense",
                "Num": "2",
                "Name": "Shop",
                "Memo/Description": "Paper",
                "Account": "Checking",
                "Split": "Office",
                "Amount": "(20.50)",
            },
            {
                "Date": "07/03/2026",
                "Transaction Type": "Transfer",
                "Num": "3",
                "Name": "",
                "Memo/Description": "Reserve",
                "Account": "Checking",
                "Split": "Savings",
                "Amount": "50",
            },
        ]
        preview = self.storage.preview_quickbooks_transactions(rows)
        assert preview["summary"] == {
            "ready": 3,
            "duplicates": 0,
            "Income": 1,
            "Expense": 1,
            "Transfer": 1,
        }
        imported = self.storage.import_quickbooks_transactions(rows)
        assert [item["kind"] for item in imported] == ["Income", "Expense", "Transfer"]
        assert imported[2]["account_id"] == checking["id"]
        assert imported[2]["to_account_id"] == savings["id"]
        duplicate_preview = self.storage.preview_quickbooks_transactions(
            rows + rows[:1]
        )
        assert duplicate_preview["summary"]["ready"] == 0
        assert duplicate_preview["summary"]["duplicates"] == 4

    def test_quickbooks_account_splits_become_sign_aware_transfers(self) -> None:
        checking = self.storage.create_account("Checking", "Bank")
        investment = self.storage.create_account("Owners investment", "Equity")
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

        assert preview["errors"] == []
        assert preview["new_categories"] == []
        assert [
            (row["kind"], row["account_id"], row["to_account_id"])
            for row in preview["rows"]
        ] == [
            ("Transfer", investment["id"], checking["id"]),
            ("Transfer", checking["id"], owners_pay["id"]),
        ]

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
        preview = self.storage.preview_quickbooks_transactions(rows, auto_create=True)

        assert strict["new_accounts"] == ["Owners pay"]
        assert strict["new_categories"] == []
        assert "destination account" in strict["errors"][0]
        assert preview["errors"] == []
        assert preview["new_account_types"] == {"Owners pay": "Equity"}
        assert preview["new_account_classifications"] == {"Owners pay": "Equity"}
        assert preview["rows"][0]["kind"] == "Transfer"
        assert preview["rows"][0]["account_id"] == checking["id"]
        assert preview["rows"][0]["to_account_id"] == "pending-account:owners pay"

    def test_quickbooks_import_reports_all_errors_and_writes_nothing(self) -> None:
        self.storage.create_account("Checking", "Bank")
        rows = [
            {
                "Date": "bad",
                "Transaction Type": "Deposit",
                "Num": "",
                "Name": "",
                "Memo/Description": "",
                "Account": "Checking",
                "Split": "Missing",
                "Amount": "10",
            },
            {
                "Date": "07/02/2026",
                "Transaction Type": "Transfer",
                "Num": "",
                "Name": "",
                "Memo/Description": "",
                "Account": "Missing",
                "Split": "Checking",
                "Amount": "1",
            },
        ]
        preview = self.storage.preview_quickbooks_transactions(rows)
        assert len(preview["errors"]) == 2
        with pytest.raises(StorageValidationError):
            self.storage.import_quickbooks_transactions(rows)
        assert self.storage.list_transactions() == []

    def test_quickbooks_import_can_create_missing_references(self) -> None:
        rows = [
            {
                "Date": "07/01/2026",
                "Transaction Type": "Deposit",
                "Num": "1",
                "Name": "Client",
                "Memo/Description": "Invoice",
                "Account": "Operating",
                "Split": "Consulting",
                "Amount": "100",
            },
            {
                "Date": "07/02/2026",
                "Transaction Type": "Transfer",
                "Num": "2",
                "Name": "",
                "Memo/Description": "Reserve",
                "Account": "Operating",
                "Split": "Savings",
                "Amount": "25",
            },
        ]
        strict = self.storage.preview_quickbooks_transactions(rows)
        assert strict["errors"]
        preview = self.storage.preview_quickbooks_transactions(rows, auto_create=True)
        assert preview["errors"] == []
        assert preview["new_accounts"] == ["Operating", "Savings"]
        assert preview["new_account_types"] == {"Operating": "Other", "Savings": "Bank"}
        assert preview["new_account_classifications"] == {
            "Operating": "Asset",
            "Savings": "Asset",
        }
        assert preview["new_categories"] == [("Consulting", "Income")]
        imported = self.storage.import_quickbooks_transactions(rows, auto_create=True)
        assert len(imported) == 2
        assert [
            (item["name"], item["type"]) for item in self.storage.list_accounts()
        ] == [("Operating", "Other"), ("Savings", "Bank")]
        assert [
            (item["name"], item["kind"]) for item in self.storage.list_categories()
        ] == [("Consulting", "Income")]

    def test_quickbooks_batch_import_reuses_reference_reads(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_category("Sales", "Income")
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_sheet.get_all_values = Mock(wraps=account_sheet.get_all_values)
        category_sheet.get_all_values = Mock(wraps=category_sheet.get_all_values)
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

        assert len(imported) == 35
        assert account_sheet.get_all_values.call_count == 1
        assert category_sheet.get_all_values.call_count == 1

    def test_general_ledger_export_collapses_double_entries(self) -> None:
        matrix = [
            ["Example LLC"],
            [
                None,
                "Date",
                "Transaction Type",
                "Num",
                "Name",
                "Memo/Description",
                "Account",
                "Debit",
                "Credit",
                "Balance",
            ],
            [
                None,
                "06/01/2026",
                "Transfer",
                "",
                "",
                "Reserve",
                "Checking",
                "",
                50,
                950,
            ],
            [None, "06/01/2026", "Transfer", "", "", "Reserve", "Savings", 50, "", 50],
            [
                None,
                "06/02/2026",
                "Deposit",
                "1",
                "Client",
                "Invoice",
                "Checking",
                100,
                "",
                1050,
            ],
            [
                None,
                "06/02/2026",
                "Deposit",
                "1",
                "Client",
                "Invoice",
                "Services",
                "",
                100,
                100,
            ],
            [None, "06/03/2026", "Expense", "2", "", "Paper", "Checking", "", 10, 1040],
            [
                None,
                "06/03/2026",
                "Expense",
                "2",
                "Store",
                "Paper",
                "Office",
                10,
                "",
                10,
            ],
        ]
        rows, errors = general_ledger_rows(matrix)
        assert errors == []
        assert len(rows) == 3
        assert (rows[0]["Account"], rows[0]["Split"], rows[0]["Transaction Type"]) == (
            "Checking",
            "Savings",
            "Transfer",
        )
        assert (rows[1]["Split"], rows[1]["Amount"]) == ("Services", "100.00")
        assert (rows[2]["Name"], rows[2]["Split"], rows[2]["Amount"]) == (
            "Store",
            "Office",
            "-10.00",
        )

    def test_backup_contains_csv_files_and_manifest(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_mileage_trip(
            trip_date="2026-07-20",
            miles=4.5,
            start_location="Office",
            destination="Bank",
            business_purpose="Deposit",
        )
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            assert set(archive.namelist()) == {
                "Accounts.csv",
                "Categories.csv",
                "Transactions.csv",
                "Mileage.csv",
                "manifest.json",
                "receipts.json",
            }
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["row_counts"]["Accounts"] == 1
            assert manifest["row_counts"]["Mileage"] == 1
            assert "backup_time" in manifest
            assert manifest["format_version"] == BACKUP_FORMAT_VERSION
            assert "Accounts.csv" in manifest["sha256"]
            assert "receipts.json" in manifest["sha256"]
            receipts = json.loads(archive.read("receipts.json"))
            assert receipts == {
                "business_profile_key": "test",
                "receipts": [],
                "schema_version": 1,
            }
        validated = self.storage.validate_backup_zip(backup)
        assert validated["workbook_title"] == "Test Ledger"

    def test_backup_forces_fresh_worksheet_reads(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        headers = self.workbook.sheets["Accounts"].rows[0]
        self.workbook.sheets["Accounts"].rows[1][headers.index("name")] = "External"

        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            assert account["id"] in archive.read("Accounts.csv").decode("utf-8")
            assert "External" in archive.read("Accounts.csv").decode("utf-8")

    def test_backup_inventories_referenced_and_unreferenced_receipts(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Sales", "Income")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-31",
            kind="Income",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
        )
        self.storage.link_transaction_receipt(
            transaction["id"],
            reference=TEST_RECEIPT_REFERENCE,
        )
        unreferenced = {
            **TEST_RECEIPT_REFERENCE,
            "id": "receipt234567",
            "name": "customer-receipt (2).pdf",
            "receipt_id": "c" * 32,
            "sha256": "d" * 64,
        }
        manifest = build_receipt_manifest(
            "test",
            self.storage.list_transactions(_force_refresh=True),
            [
                drive_file_from_reference(TEST_RECEIPT_REFERENCE),
                drive_file_from_reference(unreferenced),
            ],
        )

        backup = self.storage.export_backup_zip(manifest)

        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            receipts = json.loads(archive.read("receipts.json"))["receipts"]
        by_id = {entry["receipt_id"]: entry for entry in receipts}
        assert by_id["a" * 32]["transaction_id"] == transaction["id"]
        assert by_id["a" * 32]["reference_state"] == "referenced"
        assert by_id["c" * 32]["transaction_id"] is None
        assert by_id["c" * 32]["reference_state"] == "unreferenced"
        assert by_id["c" * 32]["stored_filename"] == "customer-receipt (2).pdf"

    def test_backup_validation_rejects_unsafe_receipt_manifest_entry(self) -> None:
        receipt = drive_file_from_reference(TEST_RECEIPT_REFERENCE)
        manifest = build_receipt_manifest("test", [], [receipt])
        backup = self.storage.export_backup_zip(manifest)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
            output, "w"
        ) as destination:
            receipts = json.loads(source.read("receipts.json"))
            receipts["receipts"][0]["stored_filename"] = "../statement.pdf"
            receipts_bytes = json.dumps(receipts).encode("utf-8")
            ledger_manifest = json.loads(source.read("manifest.json"))
            ledger_manifest["sha256"]["receipts.json"] = hashlib.sha256(
                receipts_bytes
            ).hexdigest()
            for name in source.namelist():
                if name == "receipts.json":
                    content = receipts_bytes
                elif name == "manifest.json":
                    content = json.dumps(ledger_manifest).encode("utf-8")
                else:
                    content = source.read(name)
                destination.writestr(name, content)

        with pytest.raises(StorageValidationError, match="unsafe"):
            self.storage.validate_backup_zip(output.getvalue())

    def test_manifest_rejects_a_drive_filename_that_would_be_trimmed(self) -> None:
        receipt = drive_file_from_reference(
            {**TEST_RECEIPT_REFERENCE, "name": " customer-receipt.pdf "}
        )

        with pytest.raises(ReceiptManifestError, match="unsafe"):
            build_receipt_manifest("test", [], [receipt])

    @pytest.mark.parametrize(
        "filename",
        ["invoice:2026.pdf", "CON.pdf", "receipt?.pdf", "lpt1.txt"],
    )
    def test_manifest_rejects_windows_incompatible_drive_filename(
        self,
        filename: str,
    ) -> None:
        receipt = drive_file_from_reference(
            {**TEST_RECEIPT_REFERENCE, "name": filename}
        )

        with pytest.raises(ReceiptManifestError, match="unsafe"):
            build_receipt_manifest("test", [], [receipt])

    def test_pre_manifest_v4_backup_remains_readable_as_ledger_only(self) -> None:
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
            output, "w"
        ) as destination:
            ledger_manifest = json.loads(source.read("manifest.json"))
            ledger_manifest["format_version"] = 4
            ledger_manifest["sha256"].pop("receipts.json")
            for name in source.namelist():
                if name == "receipts.json":
                    continue
                content = (
                    json.dumps(ledger_manifest).encode("utf-8")
                    if name == "manifest.json"
                    else source.read(name)
                )
                destination.writestr(name, content)

        validated = self.storage.validate_backup_zip(output.getvalue())

        assert validated["format_version"] == 4
        assert validated["receipt_inventory"] is False
        assert self.storage.receipt_manifest_from_backup(output.getvalue()) is None

    def test_backup_uses_one_multi_range_values_request(self) -> None:
        class BatchWorkbook(FakeWorkbook):
            def __init__(self) -> None:
                super().__init__()
                self.batch_requests: list[list[str]] = []

            def values_batch_get(self, ranges: list[str]) -> dict[str, object]:
                self.batch_requests.append(ranges)
                return {
                    "valueRanges": [
                        {
                            "values": self.sheets[title.strip("'")].get_all_values()
                        }
                        for title in ranges
                    ]
                }

        workbook = BatchWorkbook()
        storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)

        storage.export_backup_zip(backup_receipt_manifest(storage))

        assert workbook.batch_requests == [
            [f"'{title}'" for title in WORKSHEET_HEADERS]
        ]

    def test_import_preview_reuses_cache_but_commit_revalidates(self) -> None:
        with patch.object(
            self.storage,
            "_refresh_rows",
            wraps=self.storage._refresh_rows,
        ) as refresh_rows:
            self.storage.preview_quickbooks_transactions([])
            preview_refreshes = refresh_rows.call_count
            self.storage.preview_quickbooks_transactions([])
            self.storage.import_quickbooks_transactions([])

        assert preview_refreshes == 1
        assert refresh_rows.call_count == preview_refreshes + 1

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
        self.storage.link_transaction_receipt(
            transaction["id"],
            reference=TEST_RECEIPT_REFERENCE,
        )
        mileage = self.storage.create_mileage_trip(
            trip_date="2026-07-19",
            miles=8.4,
            start_location="Office",
            destination="Customer",
            business_purpose="Sales meeting",
        )
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        restored_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        counts = restored_storage.restore_backup_zip(backup)

        assert counts == {
            "Accounts": 1,
            "Categories": 1,
            "Transactions": 1,
            "Mileage": 1,
        }
        assert restored_storage.list_accounts()[0]["id"] == account["id"]
        restored_transaction = restored_storage.list_transactions()[0]
        assert restored_transaction["id"] == transaction["id"]
        assert decode_receipt_references(
            restored_transaction["receipt_references"]
        ) == [
            TEST_RECEIPT_REFERENCE
        ]
        assert restored_storage.list_mileage_trips()[0]["id"] == mileage["id"]

    def test_restore_accepts_pre_mileage_backup(self) -> None:
        self.storage.create_account("Checking", "Bank")
        current_backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        legacy_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(current_backup)) as source:
            manifest = json.loads(source.read("manifest.json"))
            manifest["format_version"] = 2
            manifest["row_counts"].pop("Mileage")
            manifest["worksheet_headers"].pop("Mileage")
            manifest["sha256"].pop("Mileage.csv")
            manifest["sha256"].pop("receipts.json")
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

        assert counts == {"Accounts": 1, "Categories": 0, "Transactions": 0}
        assert target.list_mileage_trips() == []

        nonblank_target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        nonblank_target.create_mileage_trip(
            trip_date="2026-07-20",
            miles=2,
            start_location="Office",
            destination="Bank",
            business_purpose="Deposit",
        )
        with pytest.raises(StorageConflictError):
            nonblank_target.restore_backup_zip(legacy_buffer.getvalue())

    def test_restore_migrates_format_version_3_receipt_references(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Sales", "Income")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Income",
            amount=25,
            account_id=account["id"],
            category_id=category["id"],
        )
        current_backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        version_3_buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(current_backup)) as source:
            manifest = json.loads(source.read("manifest.json"))
            transaction_rows = list(
                csv.reader(
                    io.StringIO(
                        source.read("Transactions.csv").decode("utf-8")
                    )
                )
            )
            receipt_column = transaction_rows[0].index(
                "receipt_references"
            )
            for row in transaction_rows:
                del row[receipt_column]
            transaction_buffer = io.StringIO(newline="")
            writer = csv.writer(transaction_buffer, lineterminator="\n")
            writer.writerows(transaction_rows)
            transaction_csv = transaction_buffer.getvalue().encode("utf-8")
            manifest["format_version"] = 3
            manifest["worksheet_headers"]["Transactions"] = (
                transaction_rows[0]
            )
            manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
                transaction_csv
            ).hexdigest()
            manifest["sha256"].pop("receipts.json")
            with zipfile.ZipFile(version_3_buffer, "w") as version_3:
                for name in source.namelist():
                    if name == "receipts.json":
                        continue
                    if name == "Transactions.csv":
                        content = transaction_csv
                    elif name == "manifest.json":
                        content = json.dumps(manifest).encode("utf-8")
                    else:
                        content = source.read(name)
                    version_3.writestr(name, content)

        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        target.restore_backup_zip(version_3_buffer.getvalue())

        restored = target.list_transactions()[0]
        assert restored["id"] == transaction["id"]
        assert restored["receipt_references"] == ""

    def test_restore_refuses_nonblank_target(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        target.create_account("Existing", "Cash")

        with pytest.raises(StorageConflictError):
            target.restore_backup_zip(backup)

    def test_restore_rejects_tampered_csv(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
            output, "w"
        ) as destination:
            for name in source.namelist():
                content = source.read(name)
                if name == "Accounts.csv":
                    content += b"tampered,row\n"
                destination.writestr(name, content)

        with pytest.raises(StorageValidationError):
            self.storage.validate_backup_zip(output.getvalue())

    def test_temporary_api_failure_returns_safe_error(self) -> None:
        self.workbook.sheets["Accounts"].get_all_values = Mock(
            side_effect=OSError("credential-content-must-not-leak")
        )
        with pytest.raises(StorageUnavailableError) as raised:
            self.storage.list_accounts()
        assert (
            str(raised.value)
            == "Google Sheets is temporarily unavailable; no success was reported"
        )
        assert "credential-content" not in str(raised.value)

    def test_reads_are_cached_and_invalidated_after_write(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original = worksheet.get_all_values
        worksheet.get_all_values = Mock(wraps=original)

        self.storage.list_accounts(active_only=False)
        self.storage.list_accounts(active_only=False)
        assert worksheet.get_all_values.call_count == 1

        self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        assert worksheet.get_all_values.call_count == 3

    def test_edit_forces_reread_before_replacing_row(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        self.storage.list_accounts(active_only=False)
        headers = self.workbook.sheets["Accounts"].rows[0]
        name_index = headers.index("name")
        self.workbook.sheets["Accounts"].rows[1][name_index] = "Externally renamed"

        edited = self.storage.edit_account(account["id"], type="Cash")

        assert edited["name"] == "Externally renamed"
        assert edited["type"] == "Cash"

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

        assert delays == [0.25, 0.5]
        assert worksheet.get_all_values.call_count == 3

    def test_lost_append_response_is_confirmed_by_uuid_without_duplicate(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original_append = worksheet.append_row

        def commit_then_timeout(values: list[str], **kwargs: object) -> None:
            original_append(values, **kwargs)
            raise OSError("response lost after commit")

        worksheet.append_row = Mock(side_effect=commit_then_timeout)

        created = self.storage.create_account("Checking", "Bank")

        accounts = self.storage.list_accounts(active_only=False)
        assert [account["id"] for account in accounts] == [created["id"]]
        assert worksheet.append_row.call_count == 1

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
        assert remaining_ids == {second["id"]}
        assert worksheet.delete_rows.call_count == 1
