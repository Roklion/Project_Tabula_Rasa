from ._support import (
    GoogleSheetsStorageTestCase,
    Mock,
    StorageNotFoundError,
    StorageValidationError,
    pytest,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_category_and_transaction_crud(self) -> None:
        source = self.storage.create_account("Checking", "Bank")
        destination = self.storage.create_account("Savings", "Bank")
        expense = self.storage.create_category("Software", "Expense")
        income = self.storage.create_category("Sales", "Income")
        vendor = self.storage.create_payee("Vendor")
        customer = self.storage.create_payee("Customer")

        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount="12.5",
            account_id=source["id"],
            category_id=expense["id"],
            payee_id=vendor["id"],
        )
        assert transaction["amount"] == "12.50"
        assert len(self.storage.list_transactions()) == 1

        edited = self.storage.edit_transaction(
            transaction["id"],
            kind="Income",
            amount=20,
            category_id=income["id"],
            payee_id=customer["id"],
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

    def test_csv_batch_import_reuses_tag_snapshot(self) -> None:
        self.storage.create_account("Checking", "Bank")
        self.storage.create_category("Sales", "Income")
        tags_sheet = self.workbook.sheets["Tags"]
        tags_sheet.get_all_values = Mock(wraps=tags_sheet.get_all_values)
        rows = [
            {
                "Date": f"2026-07-{index:02d}",
                "Type": "Income",
                "Amount": "10",
                "Account": "Checking",
                "Category": "Sales",
            }
            for index in range(1, 11)
        ]

        imported = self.storage.import_csv_transactions(rows)

        assert len(imported) == 10
        assert tags_sheet.get_all_values.call_count == 1
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

    def test_quickbooks_matches_existing_layer_two_references(self) -> None:
        account_parent = self.storage.create_account("Operating", "Bank")
        account_child = self.storage.create_account(
            "Checking",
            "Cash",
            parent_id=account_parent["id"],
        )
        category_parent = self.storage.create_category("Revenue", "Income")
        category_child = self.storage.create_category(
            "Consulting",
            "Income",
            parent_id=category_parent["id"],
        )
        rows = [
            {
                "Date": "07/01/2026",
                "Transaction Type": "Deposit",
                "Num": "1",
                "Name": "Client",
                "Memo/Description": "Invoice",
                "Account": "Checking",
                "Split": "Consulting",
                "Amount": "125.00",
            }
        ]

        preview = self.storage.preview_quickbooks_transactions(rows)
        imported = self.storage.import_quickbooks_transactions(rows)

        assert preview["errors"] == []
        assert preview["new_accounts"] == []
        assert preview["new_categories"] == []
        assert imported[0]["account_id"] == account_child["id"]
        assert imported[0]["category_id"] == category_child["id"]

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
        tags_sheet = self.workbook.sheets["Tags"]
        account_sheet.get_all_values = Mock(wraps=account_sheet.get_all_values)
        category_sheet.get_all_values = Mock(wraps=category_sheet.get_all_values)
        tags_sheet.get_all_values = Mock(wraps=tags_sheet.get_all_values)
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
        assert tags_sheet.get_all_values.call_count == 1
