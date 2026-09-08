from ._support import (
    Credentials,
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    Mock,
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
    WORKSHEET_HEADERS,
    account_balances,
    gspread,
    json,
    patch,
    pytest,
    suggested_account_classification,
    suggested_account_type,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

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

    def test_tags_are_profile_local_and_deduplicated_by_normalized_name(self) -> None:
        first = self.storage.create_tag("  Client   Visit ")
        duplicate = self.storage.create_tag("client visit")

        assert duplicate["id"] == first["id"]
        assert duplicate["name"] == "Client   Visit"
        assert self.storage.list_tags()[0]["name"] == "Client   Visit"

        inactive = self.storage.create_tag("Internal", active=False)
        assert self.storage.list_tags(active_only=True) == [first]
        reactivated = self.storage.create_tag(" internal ")
        assert reactivated["id"] == inactive["id"]
        assert reactivated["active"] == "TRUE"

        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        other_tag = other.create_tag("client visit")
        assert other_tag["id"] != first["id"]

    def test_transaction_and_mileage_tags_round_trip_and_resolve_names(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        first = self.storage.create_tag("Client")
        second = self.storage.create_tag("Follow-up")
        transaction = self.storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[second["id"], first["id"]],
        )
        mileage = self.storage.create_mileage_trip(
            trip_date="2026-09-01",
            miles=4.5,
            start_location="Office",
            destination="Client",
            business_purpose="Visit",
            tag_ids=[first["id"], second["id"]],
        )

        assert transaction["tag_ids"] == json.dumps(
            sorted([first["id"], second["id"]]), separators=(",", ":")
        )
        listed_transaction = self.storage.list_transactions()[0]
        listed_mileage = self.storage.list_mileage_trips()[0]
        assert listed_transaction["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_transaction["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_transaction["tag_ids"]
        ]
        assert listed_mileage["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_mileage["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_mileage["tag_ids"]
        ]

        edited = self.storage.edit_transaction(transaction["id"], tag_ids=[first["id"]])
        edited_mileage = self.storage.edit_mileage_trip(
            mileage["id"], tag_ids=[second["id"]]
        )
        assert edited["tag_ids"] == json.dumps([first["id"]], separators=(",", ":"))
        assert edited_mileage["tag_ids"] == json.dumps(
            [second["id"]], separators=(",", ":")
        )

    @pytest.mark.parametrize("value", ["not-json", "{}", "[1]", '["tag", "tag"]'])
    def test_tag_ids_reject_invalid_payloads(self, value: str) -> None:
        with pytest.raises(StorageValidationError):
            self.storage._prepare_mileage_trip(
                {
                    "trip_date": "2026-09-01",
                    "miles": 1,
                    "start_location": "A",
                    "destination": "B",
                    "business_purpose": "C",
                    "tag_ids": value,
                }
            )

    def test_tag_ids_reject_unknown_references(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                tag_ids=["missing-tag"],
            )

    def test_invalid_tag_does_not_persist_new_payee(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")

        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                new_payee_name="Orphan payee",
                tag_ids=["missing-tag"],
            )

        assert self.storage.list_payees() == []
        assert self.storage.list_transactions() == []

    def test_invalid_mileage_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_trip(
                trip_date="2026-09-01",
                miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []

    def test_invalid_round_trip_return_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_round_trip(
                trip_date="2026-09-01",
                miles=1,
                return_miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []
        assert self.storage.list_mileage_trips() == []

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
                    "gcp_service_account": {"type": "service_account"},
                }
            )
            storage.list_mixed_use_expenses()

        source_sheet = workbook.sheets["MixedUseExpenses"]
        source_tag_index = source_sheet.rows[0].index("tag_ids")
        assert source_sheet.rows[1][source_tag_index] == ""

    @pytest.mark.parametrize("field", ["id", "name"])
    def test_list_accounts_rejects_missing_required_display_fields(
        self, field: str
    ) -> None:
        account = self.storage.create_account("Checking", "Bank")
        worksheet = self.workbook.sheets["Accounts"]
        field_index = worksheet.rows[0].index(field)
        account_row = next(
            row for row in worksheet.rows[1:] if row[0] == account["id"]
        )
        account_row[field_index] = ""

        with pytest.raises(StorageValidationError, match="required"):
            self.storage.list_accounts(active_only=False, _force_refresh=True)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("id", "", "required"),
            ("name", "", "required"),
            ("kind", "Legacy", "must be Income or Expense"),
        ],
    )
    def test_list_categories_rejects_invalid_display_fields(
        self, field: str, value: str, message: str
    ) -> None:
        category = self.storage.create_category("Sales", "Income")
        worksheet = self.workbook.sheets["Categories"]
        field_index = worksheet.rows[0].index(field)
        category_row = next(
            row for row in worksheet.rows[1:] if row[0] == category["id"]
        )
        category_row[field_index] = value

        with pytest.raises(StorageValidationError, match=message):
            self.storage.list_categories(_force_refresh=True)

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

    def test_default_seed_does_not_recreate_renamed_defaults(self) -> None:
        self.storage.ensure_defaults()
        checking = next(
            account
            for account in self.storage.list_accounts(active_only=False)
            if account["name"] == "Checking"
        )
        sales = next(
            category
            for category in self.storage.list_categories()
            if category["name"] == "Sales"
        )
        checking_created_at = checking["created_at"]

        self.storage.edit_account(
            checking["id"],
            name="Owner's Equity",
            type="Equity",
            classification="Equity",
        )
        self.storage.edit_category(
            sales["id"], name="Renamed sales", kind="Income"
        )

        assert self.storage.ensure_defaults() == {
            "accounts": 0,
            "categories": 0,
        }
        accounts = self.storage.list_accounts(active_only=False)
        categories = self.storage.list_categories()
        assert [account for account in accounts if account["name"] == "Checking"] == []
        assert [
            account for account in accounts if account["id"] == checking["id"]
        ][0]["name"] == "Owner's Equity"
        assert [
            account for account in accounts if account["id"] == checking["id"]
        ][0]["created_at"] == checking_created_at
        assert [category for category in categories if category["name"] == "Sales"] == []
        assert [
            category for category in categories if category["id"] == sales["id"]
        ][0]["name"] == "Renamed sales"

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

        assert account_sheet.update.call_count == 2
        assert "Accounts" not in self.storage._row_cache
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

    def test_delete_category_requires_no_transactions_or_children(self) -> None:
        unused = self.storage.create_category("Unused", "Expense")
        self.storage.delete_category(unused["id"])
        assert self.storage.list_categories() == []

        parent = self.storage.create_category("Parent", "Expense")
        child = self.storage.create_category(
            "Child", "Expense", parent_id=parent["id"]
        )
        with pytest.raises(StorageConflictError, match="child categories"):
            self.storage.delete_category(parent["id"])

        account = self.storage.create_account("Checking", "Bank")
        referenced = self.storage.create_category("Referenced", "Expense")
        self.storage.create_transaction(
            txn_date="2026-08-01",
            kind="Expense",
            amount=25,
            account_id=account["id"],
            category_id=referenced["id"],
        )
        with pytest.raises(StorageConflictError, match="transactions"):
            self.storage.delete_category(referenced["id"])
        with pytest.raises(StorageConflictError, match="transactions"):
            self.storage.delete_category(f"  {referenced['id']}  ")
        assert {item["id"] for item in self.storage.list_categories()} == {
            parent["id"],
            child["id"],
            referenced["id"],
        }

    def test_delete_category_rechecks_mixed_use_sources_after_retry(
        self,
    ) -> None:
        category = self.storage.create_category("Referenced mixed-use", "Expense")
        source_headers = self.storage._headers("MixedUseExpenses")
        source_row = [""] * len(source_headers)
        source_row[source_headers.index("id")] = "source-119"
        source_row[source_headers.index("category_id")] = category["id"]
        source_sheet = self.workbook.sheets["MixedUseExpenses"]
        category_sheet = self.workbook.sheets["Categories"]
        original_delete = category_sheet.delete_rows
        injected = False

        def inject_source_then_timeout(row_number: int) -> None:
            nonlocal injected
            if not injected:
                injected = True
                source_sheet.append_row(source_row)
                raise OSError("response lost before category deletion")
            original_delete(row_number)

        category_sheet.delete_rows = inject_source_then_timeout

        with pytest.raises(StorageConflictError, match="mixed-use expenses"):
            self.storage.delete_category(category["id"])

        assert self.storage.list_categories() == [category]

    def test_edit_category_rechecks_mixed_use_sources_during_retry(
        self,
    ) -> None:
        category = self.storage.create_category("Editable mixed-use", "Expense")
        source_headers = self.storage._headers("MixedUseExpenses")
        source_row = [""] * len(source_headers)
        source_row[source_headers.index("id")] = "source-edit-119"
        source_row[source_headers.index("category_id")] = category["id"]
        source_sheet = self.workbook.sheets["MixedUseExpenses"]
        category_sheet = self.workbook.sheets["Categories"]
        original_batch_update = category_sheet.batch_update
        injected = False

        def inject_source_then_timeout(
            data: list[dict[str, object]], **kwargs: object
        ) -> None:
            nonlocal injected
            if not injected:
                injected = True
                source_sheet.append_row(source_row)
                raise OSError("response lost before category update")
            original_batch_update(data, **kwargs)

        category_sheet.batch_update = inject_source_then_timeout

        with pytest.raises(StorageConflictError, match="mixed-use expense"):
            self.storage.edit_category(category["id"], kind="Income")

        assert self.storage.list_categories() == [category]

    def test_edit_category_refreshes_row_after_mixed_use_guard(self) -> None:
        category = self.storage.create_category("Editable mixed-use", "Expense")
        category_sheet = self.workbook.sheets["Categories"]
        original_snapshot = self.storage._raw_mixed_use_snapshot
        injected = False

        def inject_category_before_guard() -> object:
            nonlocal injected
            if not injected:
                injected = True
                category_sheet.rows.insert(
                    1,
                    [
                        "inserted-category",
                        "Inserted category",
                        "Expense",
                        "",
                    ],
                )
                self.storage._invalidate("Categories")
            return original_snapshot()

        self.storage._raw_mixed_use_snapshot = inject_category_before_guard  # type: ignore[method-assign]
        edited = self.storage.edit_category(category["id"], kind="Income")

        assert edited["kind"] == "Income"
        assert next(
            item
            for item in self.storage.list_categories()
            if item["id"] == category["id"]
        )["kind"] == "Income"
        assert next(
            item
            for item in self.storage.list_categories()
            if item["id"] == "inserted-category"
        )["kind"] == "Expense"

    def test_delete_category_refreshes_row_after_mixed_use_guard(self) -> None:
        category = self.storage.create_category("Unused", "Expense")
        category_sheet = self.workbook.sheets["Categories"]
        original_rows = self.storage._rows
        mixed_use_reads = 0

        def inject_category_during_guard(
            title: str, *, force_refresh: bool = False
        ) -> list[object]:
            nonlocal mixed_use_reads
            if title == "MixedUseExpenses" and force_refresh:
                mixed_use_reads += 1
                if mixed_use_reads == 2:
                    category_sheet.rows.insert(
                        1,
                        [
                            "inserted-category",
                            "Inserted category",
                            "Expense",
                            "",
                        ],
                    )
                    self.storage._invalidate("Categories")
            return original_rows(title, force_refresh=force_refresh)

        self.storage._rows = inject_category_during_guard  # type: ignore[method-assign]
        self.storage.delete_category(category["id"])

        assert next(
            item
            for item in self.storage.list_categories()
            if item["id"] == "inserted-category"
        )["name"] == "Inserted category"
        assert all(
            item["id"] != category["id"]
            for item in self.storage.list_categories()
        )

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
