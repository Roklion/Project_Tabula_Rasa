from ._support import (
    GoogleSheetsStorageTestCase,
    Mock,
    StorageConflictError,
    StorageValidationError,
    pytest,
    suggested_account_classification,
    suggested_account_type,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

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

    def test_unknown_account_type_is_rejected(self) -> None:
        with pytest.raises(StorageValidationError):
            self.storage.create_account(
                "Old loan",
                "Loan",
                -100,
                classification="Liability",
            )
