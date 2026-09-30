from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant
from ._support import (
    GoogleSheetsStorageTestCase,
    Credentials,
    FakeWorkbook,
    GoogleSheetsStorage,
    Mock,
    StorageUnavailableError,
    StorageValidationError,
    WORKSHEET_HEADERS,
    account_balances,
    gspread,
    patch,
    pytest,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_accounts_sheet_without_classification_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Accounts"] = tuple(
            header for header in headers["Accounts"] if header != "classification"
        )
        with pytest.raises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_current_mixed_use_schema_mismatch_is_not_migrated(self) -> None:
        workbook = FakeWorkbook()

        def add_row(title: str, values: dict[str, str]) -> None:
            row = [""] * len(WORKSHEET_HEADERS[title])
            for field, value in values.items():
                row[WORKSHEET_HEADERS[title].index(field)] = value
            workbook.sheets[title].rows.append(row)

        add_row(
            "Accounts",
            {
                "id": "account-1",
                "name": "Checking",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "0.00",
                "active": "TRUE",
                "created_at": "2026-09-01T00:00:00Z",
            },
        )
        add_row(
            "Categories",
            {
                "id": "category-1",
                "name": "Office",
                "kind": "Expense",
            },
        )
        add_row(
            "Transactions",
            {
                "id": "transaction-1",
                "txn_date": "2026-09-01",
                "kind": "Expense",
                "amount": "50.00",
                "account_id": "account-1",
                "category_id": "category-1",
                "description": "Office\nAllocation rationale: Measured use",
                "source_type": "mixed_use_expense",
                "source_id": "source-1",
                "tag_ids": '["tag-1"]',
                "created_at": "2026-09-01T00:00:00Z",
            },
        )
        add_row(
            "MixedUseExpenses",
            {
                "id": "source-1",
                "txn_date": "2026-09-01",
                "kind": "Expense",
                "total_expense": "100.00",
                "business_use_percentage": "50.00",
                "allocated_amount": "50.00",
                "account_id": "account-1",
                "category_id": "category-1",
                "description": "Office",
                "allocation_rationale": "Measured use",
                "linked_transaction_id": "transaction-1",
                "created_at": "2026-09-01T00:00:00Z",
            },
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
            pytest.raises(StorageValidationError, match="tags do not match"),
        ):
            storage = GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                }
            )
            storage.list_mixed_use_expenses()

        source_sheet = workbook.sheets["MixedUseExpenses"]
        source_tag_index = source_sheet.rows[0].index("tag_ids")
        assert source_sheet.rows[1][source_tag_index] == ""

    def test_list_records_normalizes_legacy_whitespace_for_edit_lookup(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Sales", "Income")
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_row = next(
            row for row in account_sheet.rows[1:] if row[0] == account["id"]
        )
        category_row = next(
            row for row in category_sheet.rows[1:] if row[0] == category["id"]
        )
        account_row[account_sheet.rows[0].index("id")] = f" {account['id']} "
        account_row[account_sheet.rows[0].index("name")] = " Checking "
        category_row[category_sheet.rows[0].index("id")] = f" {category['id']} "
        category_row[category_sheet.rows[0].index("name")] = " Sales "
        category_row[category_sheet.rows[0].index("kind")] = " Income "

        listed_account = self.storage.list_accounts(
            active_only=False, _force_refresh=True
        )[0]
        listed_category = self.storage.list_categories(_force_refresh=True)[0]

        assert listed_account["id"] == account["id"]
        assert listed_account["name"] == "Checking"
        assert listed_category["id"] == category["id"]
        assert listed_category["name"] == "Sales"
        assert listed_category["kind"] == "Income"
        assert self.storage.edit_account(listed_account["id"], name="Renamed")[
            "name"
        ] == "Renamed"
        assert self.storage.edit_category(listed_category["id"], name="Renamed sales")[
            "name"
        ] == "Renamed sales"

    def test_list_transactions_normalizes_account_references_for_balances(self) -> None:
        source = self.storage.create_account("Checking", "Bank")
        destination = self.storage.create_account("Savings", "Bank")
        transfer = self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Transfer",
            amount=25,
            account_id=source["id"],
            to_account_id=destination["id"],
        )
        account_sheet = self.workbook.sheets["Accounts"]
        transaction_sheet = self.workbook.sheets["Transactions"]
        for account_id in (source["id"], destination["id"]):
            account_row = next(
                row for row in account_sheet.rows[1:] if row[0] == account_id
            )
            account_row[account_sheet.rows[0].index("id")] = f" {account_id} "
        transaction_row = next(
            row for row in transaction_sheet.rows[1:] if row[0] == transfer["id"]
        )
        transaction_row[transaction_sheet.rows[0].index("account_id")] = (
            f" {source['id']} "
        )
        transaction_row[transaction_sheet.rows[0].index("to_account_id")] = (
            f" {destination['id']} "
        )

        accounts = self.storage.list_accounts(active_only=False, _force_refresh=True)
        transactions = self.storage.list_transactions(_force_refresh=True)

        assert transactions[0]["account_id"] == source["id"]
        assert transactions[0]["to_account_id"] == destination["id"]
        balances = {
            account["id"]: account["balance"]
            for account in account_balances(accounts, transactions)
        }
        assert balances == {source["id"]: -25.0, destination["id"]: 25.0}

    def test_list_hierarchy_records_normalizes_parent_ids_and_category_kind(
        self,
    ) -> None:
        account_parent = self.storage.create_account("Operating", "Bank")
        account_child = self.storage.create_account(
            "Reserve", "Cash", parent_id=account_parent["id"]
        )
        category_parent = self.storage.create_category("Travel", "Expense")
        category_child = self.storage.create_category(
            "Flights", "Expense", parent_id=category_parent["id"]
        )
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_row = next(
            row for row in account_sheet.rows[1:] if row[0] == account_child["id"]
        )
        category_row = next(
            row for row in category_sheet.rows[1:] if row[0] == category_child["id"]
        )
        account_row[account_sheet.rows[0].index("parent_id")] = (
            f" {account_parent['id']} "
        )
        category_row[category_sheet.rows[0].index("parent_id")] = (
            f" {category_parent['id']} "
        )
        category_row[category_sheet.rows[0].index("kind")] = " expense "

        accounts = self.storage.list_accounts(active_only=False, _force_refresh=True)
        categories = self.storage.list_categories(_force_refresh=True)

        assert next(item for item in accounts if item["id"] == account_child["id"])[
            "parent_id"
        ] == account_parent["id"]
        listed_category = next(
            item for item in categories if item["id"] == category_child["id"]
        )
        assert listed_category["parent_id"] == category_parent["id"]
        assert listed_category["kind"] == "Expense"

    def test_list_records_rejects_ids_that_collide_after_normalization(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        duplicate_account = self.storage.create_account("Savings", "Bank")
        account_sheet = self.workbook.sheets["Accounts"]
        duplicate_account_row = next(
            row
            for row in account_sheet.rows[1:]
            if row[0] == duplicate_account["id"]
        )
        duplicate_account_row[account_sheet.rows[0].index("id")] = (
            f" {account['id']} "
        )
        with pytest.raises(StorageValidationError, match="unique"):
            self.storage.list_accounts(active_only=False, _force_refresh=True)

        category = self.storage.create_category("Office", "Expense")
        duplicate_category = self.storage.create_category("Travel", "Expense")
        category_sheet = self.workbook.sheets["Categories"]
        duplicate_category_row = next(
            row
            for row in category_sheet.rows[1:]
            if row[0] == duplicate_category["id"]
        )
        duplicate_category_row[category_sheet.rows[0].index("id")] = (
            f" {category['id']} "
        )
        with pytest.raises(StorageValidationError, match="unique"):
            self.storage.list_categories(_force_refresh=True)

    def test_list_transactions_normalizes_category_and_date(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.sheets["Transactions"]
        row = next(item for item in worksheet.rows[1:] if item[0] == transaction["id"])
        row[worksheet.rows[0].index("txn_date")] = " 2026-08-01 "
        row[worksheet.rows[0].index("category_id")] = f" {category['id']} "

        listed = self.storage.list_transactions(
            start="2026-08-01", end="2026-08-01", _force_refresh=True
        )

        assert listed[0]["txn_date"] == "2026-08-01"
        assert listed[0]["category_id"] == category["id"]

    @pytest.mark.parametrize("value", ["", "not-a-date"])
    def test_list_transactions_rejects_invalid_dates(self, value: str) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
        )
        worksheet = self.workbook.sheets["Transactions"]
        row = next(item for item in worksheet.rows[1:] if item[0] == transaction["id"])
        row[worksheet.rows[0].index("txn_date")] = value

        with pytest.raises(StorageValidationError, match="Date"):
            self.storage.list_transactions(_force_refresh=True)

    def test_missing_header_is_rejected(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Categories"] = ("id", "name")
        with pytest.raises(StorageValidationError):
            GoogleSheetsStorage(FakeWorkbook(headers))

    @pytest.mark.parametrize(
        ("title", "missing_header"),
        [("Payees", "active"), ("Transactions", "category_id")],
    )
    def test_current_schema_rejects_missing_required_headers(
        self, title: str, missing_header: str
    ) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers[title] = tuple(
            header for header in headers[title] if header != missing_header
        )

        with pytest.raises(StorageValidationError, match="is missing headers"):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_current_schema_rejects_blank_header(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Payees"] = ("id", "name", "active", "")

        with pytest.raises(StorageValidationError, match="blank header"):
            GoogleSheetsStorage(FakeWorkbook(headers))

    def test_current_schema_rejects_duplicate_header(self) -> None:
        headers = dict(WORKSHEET_HEADERS)
        headers["Payees"] = ("id", "name", "active", "active")

        with pytest.raises(StorageValidationError, match="duplicate headers"):
            GoogleSheetsStorage(FakeWorkbook(headers))

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

        assert account_sheet.update.call_count == 2
        assert "Accounts" not in self.storage._row_cache
        cached_child = next(
            item
            for item in self.storage.list_accounts(active_only=False)
            if item["id"] == child["id"]
        )
        assert cached_child["parent_id"] == first["id"]
