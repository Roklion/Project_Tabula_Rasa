from ._support import (
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    Mock,
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
    pytest,
)

class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def _bulk_transaction_fixture(self) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        replacement = self.storage.create_category("Travel", "Expense")
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
        return first, second, replacement

    def test_bulk_mutation_rejects_empty_selection(self) -> None:
        with pytest.raises(StorageValidationError, match="No transactions selected"):
            self.storage.bulk_delete_transactions(
                [],
                expected_transactions=[],
            )

    def test_bulk_mutations_accept_listed_tag_ids_in_freshness_checks(self) -> None:
        first, _, replacement = self._bulk_transaction_fixture()
        tag = self.storage.create_tag("Project")
        self.storage.edit_transaction(first["id"], tag_ids=[tag["id"]])
        expected = [
            item
            for item in self.storage.list_transactions(_force_refresh=True)
            if item["id"] == first["id"]
        ]

        category_result = self.storage.bulk_change_transaction_category(
            [first["id"]],
            expected_transactions=expected,
            category_id=replacement["id"],
        )
        assert category_result == {"status": "fully_applied", "count": "1"}

        expected = [
            item
            for item in self.storage.list_transactions(_force_refresh=True)
            if item["id"] == first["id"]
        ]
        delete_result = self.storage.bulk_delete_transactions(
            [first["id"]],
            expected_transactions=expected,
        )
        assert delete_result == {"status": "fully_applied", "count": "1"}

    def test_payee_activation_retries_when_batch_update_is_not_applied(self) -> None:
        delays: list[float] = []
        storage = GoogleSheetsStorage(
            self.workbook,
            retry_attempts=2,
            retry_base_delay_seconds=0.25,
            sleeper=delays.append,
        )
        payee = storage.create_payee("Vendor", active=False)
        worksheet = self.workbook.sheets["Payees"]
        original_batch_update = worksheet.batch_update
        calls = 0

        def fail_once(data: list[dict[str, object]], **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("temporary failure")
            original_batch_update(data, **kwargs)

        worksheet.batch_update = Mock(side_effect=fail_once)

        result = storage._ensure_payee_names(["Vendor"])

        assert result[payee["id"]]["active"] == "TRUE"
        assert calls == 2
        assert delays == [0.25]

    def test_bulk_category_change_skips_rows_already_in_target_category(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        transaction_sheet = self.workbook.sheets["Transactions"]
        category_index = transaction_sheet.rows[0].index("category_id")
        transaction_sheet.rows[1][category_index] = replacement["id"]
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        result = self.storage.bulk_change_transaction_category(
            [first["id"], second["id"]],
            expected_transactions=expected,
            category_id=replacement["id"],
        )

        assert result == {"status": "fully_applied", "count": "1"}
        categories = {
            item["id"]: item["category_id"]
            for item in self.storage.list_transactions()
        }
        assert categories[first["id"]] == replacement["id"]
        assert categories[second["id"]] == replacement["id"]

    def test_bulk_category_change_updates_all_pending_rows_in_one_batch(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        workbook_batch = Mock(wraps=self.workbook.batch_update)
        self.workbook.batch_update = workbook_batch

        result = self.storage.bulk_change_transaction_category(
            [first["id"], second["id"]],
            expected_transactions=expected,
            category_id=replacement["id"],
        )

        assert result == {"status": "fully_applied", "count": "2"}
        assert workbook_batch.call_count == 1
        categories = {
            item["id"]: item["category_id"]
            for item in self.storage.list_transactions()
        }
        assert categories[first["id"]] == replacement["id"]
        assert categories[second["id"]] == replacement["id"]

    def test_bulk_category_change_ignores_unrelated_concurrent_edit(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        original_batch = self.workbook.batch_update

        def apply_category_then_edit(body: dict[str, object]) -> None:
            original_batch(body)
            self.workbook.sheets["Transactions"].rows[1][7] = "Collaborator edit"

        self.workbook.batch_update = apply_category_then_edit

        result = self.storage.bulk_change_transaction_category(
            [first["id"], second["id"]],
            expected_transactions=expected,
            category_id=replacement["id"],
        )

        assert result == {"status": "fully_applied", "count": "2"}

    def test_bulk_delete_resolves_fresh_rows_after_row_order_changes(self) -> None:
        first, second, _ = self._bulk_transaction_fixture()
        unrelated = self.storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=3,
            account_id=first["account_id"],
            category_id=first["category_id"],
        )
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        transaction_sheet = self.workbook.sheets["Transactions"]
        transaction_sheet.rows[1], transaction_sheet.rows[2] = (
            transaction_sheet.rows[2],
            transaction_sheet.rows[1],
        )
        result = self.storage.bulk_delete_transactions(
            [first["id"], second["id"]],
            expected_transactions=expected,
        )

        assert result == {"status": "fully_applied", "count": "2"}
        assert [item["id"] for item in self.storage.list_transactions()] == [
            unrelated["id"]
        ]

    def test_bulk_mutation_rejects_changed_complete_selection(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        expected = self.storage.list_transactions(_force_refresh=True)
        transaction_sheet = self.workbook.sheets["Transactions"]
        description_index = transaction_sheet.rows[0].index("description")
        first_row = next(row for row in transaction_sheet.rows if row[0] == first["id"])
        first_row[description_index] = "Changed elsewhere"

        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.bulk_change_transaction_category(
                [first["id"], second["id"]],
                expected_transactions=expected,
                category_id=replacement["id"],
            )

    def test_bulk_category_change_normalizes_transaction_ids(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]

        result = self.storage.bulk_change_transaction_category(
            [f" {first['id']} ", f"{second['id']} "],
            expected_transactions=expected,
            category_id=replacement["id"],
        )

        assert result == {"status": "fully_applied", "count": "2"}

    def test_uncertain_bulk_category_response_is_confirmed_without_retry(
        self,
    ) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        expected = self.storage.list_transactions(_force_refresh=True)
        original_batch = self.workbook.batch_update

        def commit_then_timeout(body: dict[str, object]) -> None:
            original_batch(body)
            raise OSError("response lost after commit")

        self.workbook.batch_update = Mock(side_effect=commit_then_timeout)

        result = self.storage.bulk_change_transaction_category(
            [first["id"], second["id"]],
            expected_transactions=expected,
            category_id=replacement["id"],
        )

        assert result == {"status": "fully_applied", "count": "2"}
        assert self.workbook.batch_update.call_count == 1

    def test_uncertain_bulk_category_ignores_unselected_rows(self) -> None:
        first, second, replacement = self._bulk_transaction_fixture()
        unrelated = self.storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=3,
            account_id=first["account_id"],
            category_id=first["category_id"],
        )
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        self.workbook.batch_update = Mock(
            side_effect=OSError("temporary response lost before commit")
        )

        with pytest.raises(StorageUnavailableError, match="could not confirm"):
            self.storage.bulk_change_transaction_category(
                [first["id"], second["id"]],
                expected_transactions=expected,
                category_id=replacement["id"],
            )

        assert self.workbook.batch_update.call_count == 2
        assert unrelated["id"] in {
            transaction["id"] for transaction in self.storage.list_transactions()
        }

    def test_uncertain_bulk_delete_ignores_unselected_rows(self) -> None:
        first, second, _ = self._bulk_transaction_fixture()
        unrelated = self.storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=3,
            account_id=first["account_id"],
            category_id=first["category_id"],
        )
        expected = [
            transaction
            for transaction in self.storage.list_transactions(_force_refresh=True)
            if transaction["id"] in {first["id"], second["id"]}
        ]
        self.workbook.batch_update = Mock(
            side_effect=OSError("temporary response lost before commit")
        )

        with pytest.raises(StorageUnavailableError, match="could not confirm"):
            self.storage.bulk_delete_transactions(
                [first["id"], second["id"]],
                expected_transactions=expected,
            )

        assert self.workbook.batch_update.call_count == 2
        assert {
            transaction["id"] for transaction in self.storage.list_transactions()
        } == {first["id"], second["id"], unrelated["id"]}

    def test_uncertain_bulk_delete_partial_state_is_actionable(
        self,
    ) -> None:
        first, second, _ = self._bulk_transaction_fixture()
        expected = self.storage.list_transactions(_force_refresh=True)
        original_batch = self.workbook.batch_update

        def partially_apply_then_timeout(body: dict[str, object]) -> None:
            original_batch({"requests": body["requests"][:1]})
            raise OSError("response lost after partial application")

        self.workbook.batch_update = Mock(side_effect=partially_apply_then_timeout)

        with pytest.raises(StorageUnavailableError, match="could not confirm") as raised:
            self.storage.bulk_delete_transactions(
                [first["id"], second["id"]],
                expected_transactions=expected,
            )

        assert raised.value.retryable is False
        assert self.workbook.batch_update.call_count == 1

    def test_bulk_mutations_are_isolated_between_profile_storages(self) -> None:
        north = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        south = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        north_account = north.create_account("Checking", "Bank")
        north_category = north.create_category("Office", "Expense")
        south_account = south.create_account("Checking", "Bank")
        south_category = south.create_category("Office", "Expense")
        north_transaction = north.create_transaction(
            txn_date="2026-07-18",
            kind="Expense",
            amount=1,
            account_id=north_account["id"],
            category_id=north_category["id"],
        )
        south_transaction = south.create_transaction(
            txn_date="2026-07-18",
            kind="Expense",
            amount=2,
            account_id=south_account["id"],
            category_id=south_category["id"],
        )
        expected = north.list_transactions(_force_refresh=True)

        north.bulk_delete_transactions(
            [north_transaction["id"]],
            expected_transactions=expected,
        )

        assert north.list_transactions() == []
        assert [item["id"] for item in south.list_transactions()] == [
            south_transaction["id"]
        ]

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
