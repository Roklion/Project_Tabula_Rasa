from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Callable, Mapping
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
    VERSION_5_WORKSHEET_HEADERS,
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

HISTORICAL_ACCOUNT_HEADERS = (
    "id",
    "name",
    "type",
    "classification",
    "opening_balance",
    "active",
    "created_at",
)
HISTORICAL_CATEGORY_HEADERS = ("id", "name", "kind")
HISTORICAL_TRANSACTION_HEADERS = (
    "id",
    "txn_date",
    "kind",
    "amount",
    "account_id",
    "to_account_id",
    "category_id",
    "payee",
    "description",
    "reference",
    "created_at",
)
HISTORICAL_MILEAGE_HEADERS = (
    "id",
    "trip_date",
    "miles",
    "vehicle",
    "start_location",
    "destination",
    "business_purpose",
    "notes",
    "created_at",
)
HISTORICAL_BACKUP_HEADERS = {
    2: {
        "Accounts": HISTORICAL_ACCOUNT_HEADERS,
        "Categories": HISTORICAL_CATEGORY_HEADERS,
        "Transactions": HISTORICAL_TRANSACTION_HEADERS,
    },
    3: {
        "Accounts": HISTORICAL_ACCOUNT_HEADERS,
        "Categories": HISTORICAL_CATEGORY_HEADERS,
        "Transactions": HISTORICAL_TRANSACTION_HEADERS,
        "Mileage": HISTORICAL_MILEAGE_HEADERS,
    },
    4: {
        "Accounts": HISTORICAL_ACCOUNT_HEADERS,
        "Categories": HISTORICAL_CATEGORY_HEADERS,
        "Transactions": (
            *HISTORICAL_TRANSACTION_HEADERS[:-1],
            "receipt_references",
            HISTORICAL_TRANSACTION_HEADERS[-1],
        ),
        "Mileage": HISTORICAL_MILEAGE_HEADERS,
    },
    5: {
        "Accounts": HISTORICAL_ACCOUNT_HEADERS,
        "Categories": HISTORICAL_CATEGORY_HEADERS,
        "Transactions": (
            *HISTORICAL_TRANSACTION_HEADERS[:-1],
            "receipt_references",
            HISTORICAL_TRANSACTION_HEADERS[-1],
        ),
        "Mileage": HISTORICAL_MILEAGE_HEADERS,
    },
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


def rewrite_backup_tables(
    backup: bytes,
    transforms: Mapping[str, Callable[[list[list[str]]], None]],
    *,
    format_version: int | None = None,
) -> bytes:
    """Rewrite selected backup CSVs and keep checksums/metadata consistent."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(contents["manifest.json"])
    if format_version is not None:
        manifest["format_version"] = format_version
    for title, transform in transforms.items():
        filename = f"{title}.csv"
        rows = list(
            csv.reader(io.StringIO(contents[filename].decode("utf-8")))
        )
        transform(rows)
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(rows)
        contents[filename] = csv_buffer.getvalue().encode("utf-8")
        manifest["worksheet_headers"][title] = rows[0]
        manifest["row_counts"][title] = len(rows) - 1
        manifest["sha256"][filename] = hashlib.sha256(
            contents[filename]
        ).hexdigest()
    contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in contents.items():
            destination.writestr(name, content)
    return output.getvalue()


def downgrade_backup(backup: bytes, format_version: int) -> bytes:
    """Rebuild a current backup using one exact historical archive schema."""
    expected_headers = HISTORICAL_BACKUP_HEADERS[format_version]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        manifest = json.loads(source.read("manifest.json"))
        csv_files: dict[str, bytes] = {}
        for title, headers in expected_headers.items():
            current_rows = list(
                csv.reader(
                    io.StringIO(
                        source.read(f"{title}.csv").decode("utf-8")
                    )
                )
            )
            indexes = [current_rows[0].index(header) for header in headers]
            historical_rows = [
                [row[index] for index in indexes] for row in current_rows
            ]
            csv_buffer = io.StringIO(newline="")
            csv.writer(csv_buffer, lineterminator="\n").writerows(
                historical_rows
            )
            csv_files[f"{title}.csv"] = csv_buffer.getvalue().encode("utf-8")

        include_receipts = format_version >= 5
        receipts = source.read("receipts.json") if include_receipts else None

    manifest["format_version"] = format_version
    manifest["row_counts"] = {
        title: sum(1 for _ in csv.reader(io.StringIO(content.decode("utf-8"))))
        - 1
        for title, content in (
            (filename.removesuffix(".csv"), content)
            for filename, content in csv_files.items()
        )
    }
    manifest["worksheet_headers"] = {
        title: list(headers) for title, headers in expected_headers.items()
    }
    manifest["sha256"] = {
        filename: hashlib.sha256(content).hexdigest()
        for filename, content in csv_files.items()
    }
    if receipts is not None:
        manifest["sha256"]["receipts.json"] = hashlib.sha256(
            receipts
        ).hexdigest()

    with zipfile.ZipFile(output, "w") as destination:
        for filename, content in csv_files.items():
            destination.writestr(filename, content)
        if receipts is not None:
            destination.writestr("receipts.json", receipts)
        destination.writestr("manifest.json", json.dumps(manifest))
    return output.getvalue()


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

    def test_profile_storage_migrates_hierarchy_columns_idempotently(
        self,
    ) -> None:
        workbook = FakeWorkbook(VERSION_5_WORKSHEET_HEADERS)
        workbook.sheets["Accounts"].rows.append(
            [
                "account-1",
                "Legacy checking",
                "Bank",
                "Asset",
                "0.00",
                "TRUE",
                "2026-01-01T00:00:00Z",
            ]
        )
        workbook.sheets["Categories"].rows.append(
            ["category-1", "Legacy travel", "Expense"]
        )
        for title in ("Accounts", "Categories"):
            worksheet = workbook.sheets[title]
            worksheet.add_cols = Mock(wraps=worksheet.add_cols)
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
            storage = GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        for title in ("Accounts", "Categories"):
            worksheet = workbook.sheets[title]
            assert worksheet.rows[0] == list(WORKSHEET_HEADERS[title])
            assert worksheet.add_cols.call_count == 1
            assert worksheet.rows[1][-1] == ""
        assert storage.list_accounts()[0]["parent_id"] == ""
        assert storage.list_categories()[0]["parent_id"] == ""

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
            "parent_id",
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
        assert all(
            item["parent_id"] == "" for item in self.storage.list_accounts()
        )
        assert all(
            item["parent_id"] == "" for item in self.storage.list_categories()
        )

    @pytest.mark.parametrize(
        ("corrupted_title", "item_label"),
        [("Accounts", "Account"), ("Categories", "Category")],
    )
    def test_default_seed_validates_hierarchy_before_writes(
        self, corrupted_title: str, item_label: str
    ) -> None:
        if corrupted_title == "Accounts":
            existing = self.storage.create_account("Legacy cash", "Cash")
        else:
            existing = self.storage.create_category("Legacy sales", "Income")
        corrupted_sheet = self.workbook.sheets[corrupted_title]
        parent_index = corrupted_sheet.rows[0].index("parent_id")
        existing_row = next(
            row for row in corrupted_sheet.rows[1:] if row[0] == existing["id"]
        )
        existing_row[parent_index] = "missing-parent"
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_sheet.append_rows = Mock(wraps=account_sheet.append_rows)
        category_sheet.append_rows = Mock(wraps=category_sheet.append_rows)

        with pytest.raises(
            StorageValidationError,
            match=f"{item_label} parent does not exist",
        ):
            self.storage.ensure_defaults()

        assert account_sheet.append_rows.call_count == 0
        assert category_sheet.append_rows.call_count == 0

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

    def test_account_hierarchy_transitions_preserve_ids_and_references(
        self,
    ) -> None:
        first_parent = self.storage.create_account("Operating", "Bank")
        second_parent = self.storage.create_account("Savings", "Cash")
        child = self.storage.create_account(
            "Reserve",
            "Cash",
            125,
        )
        category = self.storage.create_category("Interest", "Income")
        transaction = self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Income",
            amount=25,
            account_id=child["id"],
            category_id=category["id"],
        )

        nested = self.storage.edit_account(
            child["id"], parent_id=first_parent["id"]
        )
        moved = self.storage.edit_account(
            child["id"], parent_id=second_parent["id"]
        )
        promoted = self.storage.edit_account(child["id"], parent_id="")

        assert nested["id"] == child["id"]
        assert nested["parent_id"] == first_parent["id"]
        assert moved["id"] == child["id"]
        assert moved["parent_id"] == second_parent["id"]
        assert promoted["id"] == child["id"]
        assert promoted["parent_id"] == ""
        for field in (
            "id",
            "name",
            "type",
            "classification",
            "opening_balance",
            "active",
            "created_at",
        ):
            assert promoted[field] == child[field]
        assert self.storage.list_transactions()[0]["id"] == transaction["id"]
        assert (
            self.storage.list_transactions()[0]["account_id"] == child["id"]
        )

    def test_inactive_account_can_parent_an_active_child(self) -> None:
        parent = self.storage.create_account("Inactive parent", "Bank")
        self.storage.deactivate_account(parent["id"])

        child = self.storage.create_account(
            "Active child", "Cash", parent_id=parent["id"]
        )

        assert child["parent_id"] == parent["id"]
        assert child["active"] == "TRUE"
        assert self.storage.list_accounts() == [
            {
                **child,
                "active": True,
                "opening_balance": 0.0,
            }
        ]

    def test_invalid_account_hierarchy_changes_do_not_write(self) -> None:
        parent = self.storage.create_account("Operating", "Bank")
        child = self.storage.create_account(
            "Petty cash", "Cash", parent_id=parent["id"]
        )
        other_parent = self.storage.create_account("Receivables", "Other")
        self.storage.create_account(
            "Other asset", "Other", parent_id=other_parent["id"]
        )
        account_sheet = self.workbook.sheets["Accounts"]
        account_sheet.append_row = Mock(wraps=account_sheet.append_row)
        account_sheet.update = Mock(wraps=account_sheet.update)

        with pytest.raises(StorageValidationError, match="does not exist"):
            self.storage.create_account(
                "Dangling", "Cash", parent_id="missing-account"
            )
        with pytest.raises(StorageValidationError, match="own parent"):
            self.storage.edit_account(parent["id"], parent_id=parent["id"])
        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.create_account(
                "Grandchild", "Cash", parent_id=child["id"]
            )
        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.edit_account(
                parent["id"], parent_id=other_parent["id"]
            )
        with pytest.raises(StorageValidationError, match="same classification"):
            self.storage.create_account(
                "Card",
                "Credit card",
                classification="Liability",
                parent_id=other_parent["id"],
            )
        with pytest.raises(StorageValidationError, match="same classification"):
            self.storage.edit_account(
                other_parent["id"], classification="Liability"
            )

        assert account_sheet.append_row.call_count == 0
        assert account_sheet.update.call_count == 0
        assert "Accounts" in self.storage._row_cache

    def test_hierarchy_write_revalidates_fresh_external_state(self) -> None:
        first = self.storage.create_account("Operating", "Bank")
        externally_moved = self.storage.create_account("Savings", "Cash")
        self.storage.list_accounts(active_only=False)
        account_sheet = self.workbook.sheets["Accounts"]
        headers = account_sheet.rows[0]
        parent_index = headers.index("parent_id")
        moved_row = next(
            row for row in account_sheet.rows[1:] if row[0] == externally_moved["id"]
        )
        moved_row[parent_index] = first["id"]
        account_sheet.append_row = Mock(wraps=account_sheet.append_row)

        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.create_account(
                "Grandchild",
                "Cash",
                parent_id=externally_moved["id"],
            )

        assert account_sheet.append_row.call_count == 0

    def test_category_hierarchy_write_revalidates_external_state(self) -> None:
        first = self.storage.create_category("Travel", "Expense")
        externally_moved = self.storage.create_category("Flights", "Expense")
        self.storage.list_categories()
        category_sheet = self.workbook.sheets["Categories"]
        headers = category_sheet.rows[0]
        parent_index = headers.index("parent_id")
        moved_row = next(
            row
            for row in category_sheet.rows[1:]
            if row[0] == externally_moved["id"]
        )
        moved_row[parent_index] = first["id"]
        category_sheet.append_row = Mock(wraps=category_sheet.append_row)

        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.create_category(
                "International", "Expense", parent_id=externally_moved["id"]
            )

        assert category_sheet.append_row.call_count == 0

    def test_failed_hierarchy_edit_does_not_report_success_or_clear_cache(
        self,
    ) -> None:
        first = self.storage.create_account("Operating", "Bank")
        second = self.storage.create_account("Savings", "Cash")
        child = self.storage.create_account(
            "Reserve", "Cash", parent_id=first["id"]
        )
        account_sheet = self.workbook.sheets["Accounts"]
        account_sheet.update = Mock(side_effect=OSError("uncertain response"))

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.edit_account(child["id"], parent_id=second["id"])

        assert account_sheet.update.call_count == 4
        assert "Accounts" in self.storage._row_cache
        cached_child = next(
            item
            for item in self.storage.list_accounts(active_only=False)
            if item["id"] == child["id"]
        )
        assert cached_child["parent_id"] == first["id"]

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

    def test_category_hierarchy_transitions_and_validation(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        travel = self.storage.create_category("Travel", "Expense")
        operations = self.storage.create_category("Operations", "Expense")
        flight = self.storage.create_category("Flight", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Expense",
            amount=25,
            account_id=account["id"],
            category_id=flight["id"],
        )

        nested = self.storage.edit_category(
            flight["id"], parent_id=travel["id"]
        )

        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.edit_category(
                travel["id"], parent_id=operations["id"]
            )
        with pytest.raises(StorageValidationError, match="same kind"):
            self.storage.edit_category(travel["id"], kind="Income")

        moved = self.storage.edit_category(
            flight["id"], parent_id=operations["id"]
        )
        promoted = self.storage.edit_category(flight["id"], parent_id="")

        assert nested["id"] == flight["id"]
        assert nested["parent_id"] == travel["id"]
        assert moved["id"] == flight["id"]
        assert moved["parent_id"] == operations["id"]
        assert promoted["parent_id"] == ""
        for field in ("id", "name", "kind"):
            assert promoted[field] == flight[field]
        assert self.storage.list_transactions()[0]["id"] == transaction["id"]
        assert (
            self.storage.list_transactions()[0]["category_id"] == flight["id"]
        )
        with pytest.raises(StorageValidationError, match="same kind"):
            self.storage.create_category(
                "Consulting", "Income", parent_id=travel["id"]
            )

    def test_hierarchy_parent_ids_are_isolated_between_profile_storages(
        self,
    ) -> None:
        other_storage = GoogleSheetsStorage(
            FakeWorkbook(), sleeper=lambda _: None
        )
        assert other_storage.list_accounts(active_only=False) == []
        assert other_storage.list_categories() == []
        account_parent = self.storage.create_account("Operating", "Bank")
        category_parent = self.storage.create_category("Travel", "Expense")

        assert other_storage.list_accounts(active_only=False) == []
        assert other_storage.list_categories() == []

        with pytest.raises(StorageValidationError, match="does not exist"):
            other_storage.create_account(
                "Other checking", "Bank", parent_id=account_parent["id"]
            )
        with pytest.raises(StorageValidationError, match="does not exist"):
            other_storage.create_category(
                "Other travel", "Expense", parent_id=category_parent["id"]
            )

        assert self.storage.create_account(
            "Savings", "Cash", parent_id=account_parent["id"]
        )["parent_id"] == account_parent["id"]
        assert self.storage.create_category(
            "Flights", "Expense", parent_id=category_parent["id"]
        )["parent_id"] == category_parent["id"]

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

    def test_legacy_nonportable_reference_remains_readable_and_unlinkable(
        self,
    ) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Software", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.worksheet("Transactions")
        headers = worksheet.rows[0]
        id_index = headers.index("id")
        references_index = headers.index("receipt_references")
        row = next(
            item for item in worksheet.rows[1:] if item[id_index] == transaction["id"]
        )
        row[references_index] = (
            '[{"id":"receipt123456","name":"invoice:2026.pdf"}]'
        )

        current = self.storage.list_transactions(_force_refresh=True)[0]
        assert decode_receipt_references(current["receipt_references"]) == [
            {"id": "receipt123456", "name": "invoice:2026.pdf"}
        ]

        self.storage.unlink_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
        )
        current = self.storage.list_transactions(_force_refresh=True)[0]
        assert decode_receipt_references(current["receipt_references"]) == []

        with pytest.raises(StorageValidationError, match="unsafe"):
            self.storage.link_transaction_receipt(
                transaction["id"],
                file_id="receipt123456",
                name="invoice:2026.pdf",
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
        assert all(
            item["parent_id"] == "" for item in self.storage.list_accounts()
        )
        assert all(
            item["parent_id"] == "" for item in self.storage.list_categories()
        )

    @pytest.mark.parametrize(
        ("corrupted_title", "item_label"),
        [("Accounts", "Account"), ("Categories", "Category")],
    )
    def test_quickbooks_auto_create_validates_hierarchy_before_writes(
        self, corrupted_title: str, item_label: str
    ) -> None:
        if corrupted_title == "Accounts":
            existing = self.storage.create_account("Legacy cash", "Cash")
        else:
            existing = self.storage.create_category("Legacy sales", "Income")
        corrupted_sheet = self.workbook.sheets[corrupted_title]
        parent_index = corrupted_sheet.rows[0].index("parent_id")
        existing_row = next(
            row for row in corrupted_sheet.rows[1:] if row[0] == existing["id"]
        )
        existing_row[parent_index] = "missing-parent"
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        transaction_sheet = self.workbook.sheets["Transactions"]
        account_sheet.append_rows = Mock(wraps=account_sheet.append_rows)
        category_sheet.append_rows = Mock(wraps=category_sheet.append_rows)
        transaction_sheet.append_rows = Mock(wraps=transaction_sheet.append_rows)
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
            }
        ]

        with pytest.raises(
            StorageValidationError,
            match=f"{item_label} parent does not exist",
        ):
            self.storage.import_quickbooks_transactions(rows, auto_create=True)

        assert account_sheet.append_rows.call_count == 0
        assert category_sheet.append_rows.call_count == 0
        assert transaction_sheet.append_rows.call_count == 0

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

    def test_backup_rejects_an_externally_corrupted_hierarchy(self) -> None:
        parent = self.storage.create_account("Operating", "Bank")
        child = self.storage.create_account(
            "Savings", "Cash", parent_id=parent["id"]
        )
        account_sheet = self.workbook.sheets["Accounts"]
        headers = account_sheet.rows[0]
        parent_index = headers.index("parent_id")
        parent_row = next(
            row for row in account_sheet.rows[1:] if row[0] == parent["id"]
        )
        parent_row[parent_index] = child["id"]

        with pytest.raises(StorageValidationError, match="only two levels"):
            self.storage.export_backup_zip(
                backup_receipt_manifest(self.storage)
            )

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
        account = self.storage.create_account("Checking", "Bank")
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        version_4_backup = downgrade_backup(backup, 4)
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        validated = self.storage.validate_backup_zip(version_4_backup)
        target.restore_backup_zip(version_4_backup)

        assert validated["format_version"] == 4
        assert validated["receipt_inventory"] is False
        assert self.storage.receipt_manifest_from_backup(version_4_backup) is None
        assert target.list_accounts()[0]["id"] == account["id"]
        assert target.list_accounts()[0]["parent_id"] == ""

    def test_format_5_backup_restores_with_blank_hierarchy_columns(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Travel", "Expense")
        current_backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        version_5_backup = downgrade_backup(current_backup, 5)
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        validated = target.validate_backup_zip(version_5_backup)
        target.restore_backup_zip(version_5_backup)

        assert validated["format_version"] == 5
        assert validated["receipt_inventory"] is True
        restored_account = target.list_accounts()[0]
        restored_category = target.list_categories()[0]
        assert restored_account["id"] == account["id"]
        assert restored_account["parent_id"] == ""
        assert restored_category["id"] == category["id"]
        assert restored_category["parent_id"] == ""

    def test_format_5_labeled_backup_preserves_present_hierarchy_columns(
        self,
    ) -> None:
        account_parent = self.storage.create_account("Operating", "Bank")
        account_child = self.storage.create_account(
            "Petty cash", "Bank", parent_id=account_parent["id"]
        )
        category_parent = self.storage.create_category("Travel", "Expense")
        category_child = self.storage.create_category(
            "Airfare", "Expense", parent_id=category_parent["id"]
        )
        current_backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        mixed_version_backup = rewrite_backup_tables(
            current_backup,
            {},
            format_version=5,
        )
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        validated = target.validate_backup_zip(mixed_version_backup)
        target.restore_backup_zip(mixed_version_backup)

        assert validated["format_version"] == 5
        restored_accounts = {
            item["id"]: item for item in target.list_accounts(active_only=False)
        }
        restored_categories = {
            item["id"]: item for item in target.list_categories()
        }
        assert restored_accounts[account_child["id"]]["parent_id"] == account_parent["id"]
        assert (
            restored_categories[category_child["id"]]["parent_id"]
            == category_parent["id"]
        )

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

    def test_backup_round_trips_account_and_category_hierarchies(self) -> None:
        account_parent = self.storage.create_account("Operating", "Bank")
        account_child = self.storage.create_account(
            "Savings", "Cash", parent_id=account_parent["id"]
        )
        category_parent = self.storage.create_category("Travel", "Expense")
        category_child = self.storage.create_category(
            "Flights", "Expense", parent_id=category_parent["id"]
        )
        backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        target.restore_backup_zip(backup)

        accounts = {
            item["id"]: item
            for item in target.list_accounts(active_only=False)
        }
        categories = {item["id"]: item for item in target.list_categories()}
        assert accounts[account_child["id"]]["parent_id"] == account_parent["id"]
        assert (
            categories[category_child["id"]]["parent_id"]
            == category_parent["id"]
        )

    def test_backup_validation_rejects_tampered_hierarchy_graphs(self) -> None:
        first = self.storage.create_account("First", "Other")
        second = self.storage.create_account("Second", "Other")
        third = self.storage.create_account("Third", "Other")
        liability = self.storage.create_account(
            "Liability",
            "Other",
            classification="Liability",
        )
        backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        invalid_parent_sets = [
            {first["id"]: "missing"},
            {first["id"]: first["id"]},
            {first["id"]: second["id"], second["id"]: first["id"]},
            {
                first["id"]: second["id"],
                second["id"]: third["id"],
                third["id"]: first["id"],
            },
            {first["id"]: second["id"], second["id"]: third["id"]},
            {first["id"]: liability["id"]},
        ]

        for parent_ids in invalid_parent_sets:
            def assign_parents(
                rows: list[list[str]],
                assignments: dict[str, str] = parent_ids,
            ) -> None:
                id_index = rows[0].index("id")
                parent_index = rows[0].index("parent_id")
                for row in rows[1:]:
                    if row[id_index] in assignments:
                        row[parent_index] = assignments[row[id_index]]

            tampered = rewrite_backup_tables(
                backup, {"Accounts": assign_parents}
            )
            with pytest.raises(StorageValidationError):
                self.storage.validate_backup_zip(tampered)

    def test_backup_validation_rejects_incompatible_category_parent(self) -> None:
        expense = self.storage.create_category("Travel", "Expense")
        income = self.storage.create_category("Sales", "Income")
        backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )

        def assign_incompatible_parent(rows: list[list[str]]) -> None:
            id_index = rows[0].index("id")
            parent_index = rows[0].index("parent_id")
            for row in rows[1:]:
                if row[id_index] == expense["id"]:
                    row[parent_index] = income["id"]

        tampered = rewrite_backup_tables(
            backup, {"Categories": assign_incompatible_parent}
        )

        with pytest.raises(StorageValidationError, match="same kind"):
            self.storage.validate_backup_zip(tampered)

    def test_restore_accepts_pre_mileage_backup(self) -> None:
        self.storage.create_account("Checking", "Bank")
        current_backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        version_2_backup = downgrade_backup(current_backup, 2)

        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        counts = target.restore_backup_zip(version_2_backup)

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
            nonblank_target.restore_backup_zip(version_2_backup)

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
        version_3_backup = downgrade_backup(current_backup, 3)

        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        target.restore_backup_zip(version_3_backup)

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
        self.storage.list_categories()
        assert worksheet.get_all_values.call_count == 1
        assert "Accounts" in self.storage._row_cache
        assert "Categories" in self.storage._row_cache

        self.storage.create_account("Checking", "Bank")
        assert "Accounts" not in self.storage._row_cache
        assert "Categories" in self.storage._row_cache
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

    def test_failed_append_preserves_the_confirmed_account_cache(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original_read = worksheet.get_all_values
        worksheet.get_all_values = Mock(wraps=original_read)
        self.storage.list_accounts(active_only=False)
        worksheet.append_row = Mock(
            side_effect=gspread.GSpreadException("definitive failure")
        )

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.create_account("Checking", "Bank")

        assert worksheet.get_all_values.call_count == 2
        assert "Accounts" in self.storage._row_cache
        assert self.storage.list_accounts(active_only=False) == []
        assert worksheet.get_all_values.call_count == 2

    def test_unconfirmed_retryable_append_never_reports_success(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        worksheet.append_row = Mock(side_effect=OSError("temporary failure"))

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.create_account("Checking", "Bank")

        assert worksheet.append_row.call_count == 4
        assert self.storage.list_accounts(active_only=False) == []
        assert "Accounts" in self.storage._row_cache

    def test_failed_batch_append_preserves_profile_caches(self) -> None:
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_sheet.append_rows = Mock(
            side_effect=gspread.GSpreadException("definitive failure")
        )

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.ensure_defaults()

        assert "Accounts" in self.storage._row_cache
        assert "Categories" in self.storage._row_cache
        assert self.storage.list_accounts(active_only=False) == []
        assert self.storage.list_categories() == []
        assert category_sheet.rows == [list(WORKSHEET_HEADERS["Categories"])]

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
