from ._support import (
    GoogleSheetsStorageTestCase,
    FakeWorkbook,
    GoogleSheetsStorage,
    Mock,
    StorageConflictError,
    StorageValidationError,
    pytest,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

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

    def test_edit_category_kind_rejects_recurring_schedule_references(self) -> None:
        category = self.storage.create_category("Referenced recurring", "Expense")
        account = self.storage.create_account("Checking", "Bank")
        result = self.storage.create_recurring_expense(
            schedule_id="kind-schedule",
            name="Scheduled expense",
            txn_date="2026-09-01",
            amount="10.00",
            account_id=account["id"],
            category_id=category["id"],
        )
        self.storage.delete_transaction(result["transaction"]["id"])

        with pytest.raises(StorageConflictError, match="recurring schedule"):
            self.storage.edit_category(category["id"], kind="Income")

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

    def test_delete_category_rejects_recurring_schedule_references(self) -> None:
        category = self.storage.create_category("Referenced recurring", "Expense")
        self.storage.create_account("Checking", "Bank")
        account = self.storage.list_accounts()[0]
        result = self.storage.create_recurring_expense(
            schedule_id="category-schedule",
            name="Scheduled expense",
            txn_date="2026-09-01",
            amount="10.00",
            account_id=account["id"],
            category_id=category["id"],
        )
        self.storage.delete_transaction(result["transaction"]["id"])

        with pytest.raises(StorageConflictError, match="recurring schedules"):
            self.storage.delete_category(category["id"])

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
