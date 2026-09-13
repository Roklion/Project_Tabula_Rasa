import csv

from ._support import (
    BACKUP_FORMAT_VERSION,
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    ReceiptManifestError,
    StorageConflictError,
    StorageValidationError,
    TEST_RECEIPT_REFERENCE,
    WORKSHEET_HEADERS,
    backup_receipt_manifest,
    build_receipt_manifest,
    decode_receipt_references,
    drive_file_from_reference,
    general_ledger_rows,
    hashlib,
    io,
    json,
    patch,
    pytest,
    rewrite_backup_tables,
    zipfile,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

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
                "Payees.csv",
                "Transactions.csv",
                "Mileage.csv",
                "MixedUseExpenses.csv",
                "RecurringSchedules.csv",
                "Tags.csv",
                "Assets.csv",
                "manifest.json",
                "receipts.json",
            }
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["row_counts"]["Accounts"] == 1
            assert manifest["row_counts"]["Payees"] == 0
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

    def test_backup_serializes_normalized_recurring_schedule_enums(self) -> None:
        self.storage.ensure_defaults()
        account = self.storage.list_accounts()[0]
        category = self.storage.list_categories(kind="Expense")[0]
        payee = self.storage.create_payee("Noncanonical vendor")
        schedule = self.storage.create_recurring_schedule(
            schedule_id="noncanonical-export",
            name="Noncanonical export",
            txn_date="2026-07-31",
            recurrence_unit="month",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
        )
        row = self.storage._find_row("RecurringSchedules", schedule["id"])
        changed = dict(row.values)
        changed.update({
            "kind": " expense ",
            "source_kind": " transaction ",
            "recurrence_unit": "months",
            "status": "ACTIVE",
            "account_id": f" {account['id']} ",
            "category_id": f" {category['id']} ",
            "payee_id": f" {payee['id']} ",
        })
        self.storage._replace_row("RecurringSchedules", row, changed)

        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            schedules = list(csv.DictReader(io.StringIO(archive.read("RecurringSchedules.csv").decode())))
        assert schedules[0]["kind"] == "Expense"
        assert schedules[0]["recurrence_unit"] == "month"
        assert schedules[0]["status"] == "active"
        assert schedules[0]["account_id"] == account["id"]
        assert schedules[0]["category_id"] == category["id"]
        assert schedules[0]["payee_id"] == payee["id"]
        assert self.storage.validate_backup_zip(backup)["format_version"] == BACKUP_FORMAT_VERSION

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

    def test_backup_validation_normalizes_padded_payee_ids(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        payee = self.storage.create_payee("Vendor")
        self.storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            payee_id=payee["id"],
        )
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        def pad_payee_id(rows: list[list[str]]) -> None:
            payee_id_index = rows[0].index("id")
            rows[1][payee_id_index] = f"  {payee['id']}  "

        padded_backup = rewrite_backup_tables(backup, {"Payees": pad_payee_id})

        validated = self.storage.validate_backup_zip(padded_backup)
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        target.restore_backup_zip(padded_backup)

        assert validated["format_version"] == BACKUP_FORMAT_VERSION
        assert target.list_payees()[0]["id"] == payee["id"]
        assert target.list_transactions()[0]["payee_id"] == payee["id"]

    def test_backup_rejects_invalid_payee_records(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        payee = storage.create_payee("Valid vendor")
        backup = storage.export_backup_zip(
            build_receipt_manifest("test", storage.list_transactions(), [])
        )
        contents: dict[str, bytes]
        with zipfile.ZipFile(io.BytesIO(backup)) as source:
            contents = {name: source.read(name) for name in source.namelist()}
        payee_rows = list(csv.reader(io.StringIO(contents["Payees.csv"].decode())))
        payee_rows[1][1] = ""
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(payee_rows)
        contents["Payees.csv"] = csv_buffer.getvalue().encode()
        manifest = json.loads(contents["manifest.json"])
        manifest["sha256"]["Payees.csv"] = hashlib.sha256(
            contents["Payees.csv"]
        ).hexdigest()
        contents["manifest.json"] = json.dumps(manifest).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as destination:
            for name, content in contents.items():
                destination.writestr(name, content)

        with pytest.raises(StorageValidationError, match="Payee name"):
            GoogleSheetsStorage.validate_backup_zip(output.getvalue())
        assert payee["name"] == "Valid vendor"

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
        payee = self.storage.create_payee("Customer")
        transaction = self.storage.create_transaction(
            txn_date="2026-07-19",
            kind="Income",
            amount=25,
            account_id=account["id"],
            category_id=category["id"],
            payee_id=payee["id"],
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
            "Payees": 1,
            "Transactions": 1,
            "Mileage": 1,
            "Tags": 0,
            "RecurringSchedules": 0,
            "Assets": 0,
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

    def test_backup_round_trips_mixed_recurring_source_kind(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        result = self.storage.create_recurring_mixed_use_expense(
            schedule_id="mixed-backup-schedule",
            name="Shared office",
            txn_date="2026-09-01",
            recurrence_unit="month",
            recurrence_interval=1,
            total_expense="100.00",
            business_use_percentage="50",
            account_id=account["id"],
            category_id=category["id"],
            allocation_rationale="Workspace",
        )
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        restored_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        restored_storage.restore_backup_zip(backup)
        schedule = restored_storage.get_recurring_schedule("mixed-backup-schedule")
        source = restored_storage.get_mixed_use_expense(result["source"]["id"])
        projection = next(
            item
            for item in restored_storage.list_transactions()
            if item["id"] == result["transaction"]["id"]
        )
        assert schedule["source_kind"] == "mixed_use"
        assert source["recurring_source_kind"] == "mixed_use"
        assert projection["recurring_source_kind"] == "mixed_use"

    def test_backup_canonicalizes_mixed_recurring_allocation(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        self.storage.create_recurring_mixed_use_expense(
            schedule_id="mixed-canonical-backup",
            name="Shared office",
            txn_date="2026-09-01",
            recurrence_unit="month",
            recurrence_interval=1,
            total_expense="100.00",
            business_use_percentage="50",
            account_id=account["id"],
            category_id=category["id"],
            allocation_rationale="Workspace",
        )
        row = self.storage._find_row(
            "RecurringSchedules", "mixed-canonical-backup"
        )
        corrupted = dict(row.values)
        corrupted["amount"] = "99.00"
        self.storage._replace_row("RecurringSchedules", row, corrupted)

        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            schedules = list(
                csv.DictReader(
                    io.StringIO(
                        archive.read("RecurringSchedules.csv").decode("utf-8")
                    )
                )
            )
        assert schedules[0]["amount"] == "50.00"
        assert self.storage.validate_backup_zip(backup)["format_version"] == (
            BACKUP_FORMAT_VERSION
        )

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

    def test_backup_validation_rejects_malformed_transaction_receipts(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        self.storage.create_transaction(
            txn_date="2026-09-01", kind="Expense", amount="10.00",
            account_id=account["id"], category_id=category["id"],
        )
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        def corrupt_receipts(rows: list[list[str]]) -> None:
            rows[1][rows[0].index("receipt_references")] = "not-json"

        tampered = rewrite_backup_tables(backup, {"Transactions": corrupt_receipts})
        with pytest.raises(StorageValidationError, match="receipt"):
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

    def test_restore_refuses_legacy_backup_before_writing(self) -> None:
        self.storage.create_account("Checking", "Bank")
        backup = rewrite_backup_tables(
            self.storage.export_backup_zip(backup_receipt_manifest(self.storage)),
            {},
            format_version=5,
        )
        target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with pytest.raises(StorageValidationError, match="migrate_legacy_backup"):
            target.restore_backup_zip(backup)
        assert target.list_accounts(active_only=False) == []

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
