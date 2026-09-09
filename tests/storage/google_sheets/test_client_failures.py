from ._support import (
    Credentials,
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    Mock,
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
    StorageAuthenticationError,
    StorageInitializationError,
    StorageUnavailableError,
    StorageValidationError,
    StorageWorkbookAccessError,
    VERSION_5_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
    _mutation_guidance,
    gspread,
    patch,
    pytest,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_retry_refresh_failure_invalidates_and_normalizes_error(self) -> None:
        self.storage._row_cache["Transactions"] = []
        writes = 0

        def write() -> None:
            nonlocal writes
            writes += 1
            raise StorageUnavailableError("response lost", retryable=True)

        def refresh() -> None:
            raise StorageUnavailableError("refresh unavailable", retryable=True)

        with pytest.raises(StorageUnavailableError, match="could not confirm") as raised:
            self.storage._write_with_uncertain_readback(
                "transaction update",
                write,
                lambda: "unchanged",
                before_retry=refresh,
                invalidate=("Transactions",),
            )

        assert writes == 1
        assert raised.value.retryable is False
        assert "Transactions ledger" in str(raised.value)
        assert "Transactions" not in self.storage._row_cache

    def test_uncertain_write_does_not_retry_ambiguous_state(self) -> None:
        self.storage._row_cache["Transactions"] = []
        writes = 0

        def write() -> None:
            nonlocal writes
            writes += 1
            raise StorageUnavailableError("response lost", retryable=True)

        with pytest.raises(StorageUnavailableError, match="could not confirm") as raised:
            self.storage._write_with_uncertain_readback(
                "transaction update",
                write,
                lambda: "ambiguous",
                invalidate=("Transactions",),
            )

        assert writes == 1
        assert raised.value.retryable is False
        assert "Transactions" not in self.storage._row_cache

    def test_retry_backoff_precedes_refresh_callback(self) -> None:
        events: list[str] = []
        storage = GoogleSheetsStorage(
            self.workbook,
            sleeper=lambda _: events.append("backoff"),
        )
        writes = 0

        def write() -> None:
            nonlocal writes
            writes += 1
            events.append("write")
            if writes == 1:
                raise StorageUnavailableError("response lost", retryable=True)

        def refresh() -> None:
            events.append("refresh")

        storage._write_with_uncertain_readback(
            "transaction update", write, lambda: "unchanged", before_retry=refresh
        )

        assert events == ["write", "backoff", "refresh", "write"]

    def test_retry_refresh_unexpected_failure_still_invalidates_cache(self) -> None:
        self.storage._row_cache["Transactions"] = []

        def write() -> None:
            raise StorageUnavailableError("response lost", retryable=True)

        def refresh() -> None:
            raise KeyError("row disappeared")

        with pytest.raises(KeyError):
            self.storage._write_with_uncertain_readback(
                "transaction update",
                write,
                lambda: "unchanged",
                before_retry=refresh,
                invalidate=("Transactions",),
            )

        assert "Transactions" not in self.storage._row_cache

    def test_readback_unexpected_failure_still_invalidates_cache(self) -> None:
        self.storage._row_cache["Transactions"] = []

        def write() -> None:
            raise StorageUnavailableError("response lost", retryable=True)

        def readback() -> str:
            raise KeyError("unreadable response")

        with pytest.raises(KeyError):
            self.storage._write_with_uncertain_readback(
                "transaction update",
                write,
                readback,
                invalidate=("Transactions",),
            )

        assert "Transactions" not in self.storage._row_cache

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
        same_spreadsheet_storage = GoogleSheetsStorage(
            FakeWorkbook(), spreadsheet_id="given-spreadsheet-id"
        )
        assert (
            storage._workbook_locks is same_spreadsheet_storage._workbook_locks
        )
        assert workbook.worksheets.call_count == 1
        assert workbook.sheets["Accounts"].get_all_values.call_count == 1
        assert workbook.sheets["Accounts"].row_values.call_count == 0
        assert workbook.sheets["Sheet1"].rows == [[]]
        for title, headers in WORKSHEET_HEADERS.items():
            assert workbook.sheets[title].rows == [list(headers)]

    def test_profile_storage_rejects_null_spreadsheet_id(self) -> None:
        with pytest.raises(
            StorageAuthenticationError,
            match="Profile Google settings are incomplete or malformed",
        ):
            GoogleSheetsStorage.from_secrets(
                {
                    "spreadsheet_id": None,
                    "gcp_service_account": {"type": "service_account"},
                }
            )

    def test_read_only_profile_storage_validates_without_mutating_workbook(
        self,
    ) -> None:
        workbook = FakeWorkbook()
        google_client = Mock()
        google_client.open_by_key.return_value = workbook
        for worksheet in workbook.sheets.values():
            worksheet.update = Mock()
            worksheet.add_cols = Mock()
            worksheet.append_row = Mock()
            worksheet.append_rows = Mock()

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ) as from_service_account_info,
            patch.object(gspread, "authorize", return_value=google_client),
        ):
            storage = GoogleSheetsStorage.from_secrets_read_only(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        assert storage.workbook_title == workbook.title
        from_service_account_info.assert_called_once_with(
            {"type": "service_account"}, scopes=[SHEETS_READONLY_SCOPE]
        )
        for worksheet in workbook.sheets.values():
            worksheet.update.assert_not_called()
            worksheet.add_cols.assert_not_called()
            worksheet.append_row.assert_not_called()
            worksheet.append_rows.assert_not_called()

    def test_read_only_profile_storage_rejects_legacy_headers_without_migration(
        self,
    ) -> None:
        workbook = FakeWorkbook(VERSION_5_WORKSHEET_HEADERS)
        google_client = Mock()
        google_client.open_by_key.return_value = workbook
        for worksheet in workbook.sheets.values():
            worksheet.update = Mock()
            worksheet.add_cols = Mock()

        with (
            patch.object(
                Credentials,
                "from_service_account_info",
                return_value=object(),
            ),
            patch.object(gspread, "authorize", return_value=google_client),
            pytest.raises(StorageValidationError, match="missing worksheets"),
        ):
            GoogleSheetsStorage.from_secrets_read_only(
                {
                    "spreadsheet_id": "given-spreadsheet-id",
                    "gcp_service_account": {"type": "service_account"},
                }
            )

        for worksheet in workbook.sheets.values():
            worksheet.update.assert_not_called()
            worksheet.add_cols.assert_not_called()

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
                match="validation could not finish",
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

    def test_batch_replace_retargets_rows_after_uncertain_row_shift(self) -> None:
        account = self.storage.create_account("Retry target", "Bank")
        row = self.storage._find_row("Accounts", account["id"])
        worksheet = self.workbook.sheets["Accounts"]
        original_batch_update = worksheet.batch_update
        calls = 0

        def insert_row_then_fail(
            data: list[dict[str, object]], **kwargs: object
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                worksheet.rows.insert(1, list(worksheet.rows[1]))
                worksheet.rows[1][0] = "inserted-before-retry"
                raise OSError("temporary response lost")
            original_batch_update(data, **kwargs)

        worksheet.batch_update = insert_row_then_fail  # type: ignore[method-assign]
        try:
            self.storage._replace_rows(
                "Accounts", [(row, {**row.values, "name": "Retry target updated"})]
            )
        finally:
            worksheet.batch_update = original_batch_update  # type: ignore[method-assign]

        rows = self.storage._rows("Accounts", force_refresh=True)
        assert (
            next(item for item in rows if item.values["id"] == account["id"])
            .values["name"]
            == "Retry target updated"
        )
        assert rows[0].values["id"] == "inserted-before-retry"

    def test_batch_replace_stops_when_target_changes_after_uncertain_response(
        self,
    ) -> None:
        account = self.storage.create_account("Retry conflict", "Bank")
        row = self.storage._find_row("Accounts", account["id"])
        worksheet = self.workbook.sheets["Accounts"]
        original_batch_update = worksheet.batch_update
        name_index = worksheet.rows[0].index("name")

        def change_then_timeout(
            data: list[dict[str, object]], **kwargs: object
        ) -> None:
            del data, kwargs
            worksheet.rows[row.row_number - 1][name_index] = "Changed elsewhere"
            raise OSError("temporary response lost")

        batch_update = Mock(side_effect=change_then_timeout)
        worksheet.batch_update = batch_update
        try:
            with pytest.raises(StorageUnavailableError, match="could not confirm"):
                self.storage._replace_rows(
                    "Accounts", [(row, {**row.values, "name": "Retry conflict updated"})]
                )
        finally:
            worksheet.batch_update = original_batch_update  # type: ignore[method-assign]

        assert batch_update.call_count == 1
        assert worksheet.rows[row.row_number - 1][name_index] == "Changed elsewhere"

    def test_batch_replace_stops_on_duplicate_id_in_uncertain_readback(self) -> None:
        account = self.storage.create_account("Duplicate readback", "Bank")
        row = self.storage._find_row("Accounts", account["id"])
        worksheet = self.workbook.sheets["Accounts"]
        original_batch_update = worksheet.batch_update
        calls = 0

        def duplicate_then_timeout(
            data: list[dict[str, object]], **kwargs: object
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                worksheet.rows.append(list(worksheet.rows[1]))
                raise OSError("temporary response lost")
            original_batch_update(data, **kwargs)

        batch_update = Mock(side_effect=duplicate_then_timeout)
        worksheet.batch_update = batch_update
        try:
            with pytest.raises(StorageUnavailableError, match="could not confirm"):
                self.storage._replace_rows(
                    "Accounts", [(row, {**row.values, "name": "Should not retry"})]
                )
        finally:
            worksheet.batch_update = original_batch_update  # type: ignore[method-assign]

        assert calls == 1

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

    def test_failed_append_invalidates_cache(self) -> None:
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
        assert "Accounts" not in self.storage._row_cache
        assert self.storage.list_accounts(active_only=False) == []
        assert worksheet.get_all_values.call_count == 3

    def test_unconfirmed_retryable_append_never_reports_success(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        worksheet.append_row = Mock(side_effect=OSError("temporary failure"))

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.create_account("Checking", "Bank")

        assert worksheet.append_row.call_count == 2
        assert "Accounts" not in self.storage._row_cache
        assert self.storage.list_accounts(active_only=False) == []

    def test_append_is_not_replayed_when_confirmation_read_fails(self) -> None:
        worksheet = self.workbook.sheets["Accounts"]
        original_append_row = worksheet.append_row
        original_rows = self.storage._rows
        calls = 0

        def append_then_lose_response(
            values: list[str], **kwargs: object
        ) -> None:
            nonlocal calls
            calls += 1
            original_append_row(values, **kwargs)
            raise OSError("response lost after append")

        def rows_unavailable_after_append(
            title: str, *, force_refresh: bool = False
        ) -> list[object]:
            if title == "Accounts" and force_refresh:
                raise StorageUnavailableError(
                    "confirmation read unavailable", retryable=True
                )
            return original_rows(title, force_refresh=force_refresh)

        worksheet.append_row = append_then_lose_response  # type: ignore[method-assign]
        self.storage._rows = rows_unavailable_after_append  # type: ignore[method-assign]
        self.storage._retry_attempts = 2

        try:
            with pytest.raises(StorageUnavailableError, match="could not confirm"):
                self.storage._append("Accounts", {"id": "ambiguous-append"})
        finally:
            self.storage._rows = original_rows  # type: ignore[method-assign]
            worksheet.append_row = original_append_row  # type: ignore[method-assign]

        assert calls == 1
        assert len(self.storage._rows("Accounts", force_refresh=True)) == 1

    def test_failed_batch_append_invalidates_caches(self) -> None:
        account_sheet = self.workbook.sheets["Accounts"]
        category_sheet = self.workbook.sheets["Categories"]
        account_sheet.append_rows = Mock(
            side_effect=gspread.GSpreadException("definitive failure")
        )

        with pytest.raises(StorageUnavailableError, match="no success"):
            self.storage.ensure_defaults()

        assert "Accounts" not in self.storage._row_cache
        assert "Categories" in self.storage._row_cache
        assert self.storage.list_accounts(active_only=False) == []
        assert self.storage.list_categories() == []
        assert category_sheet.rows == [list(WORKSHEET_HEADERS["Categories"])]


@pytest.mark.parametrize(
    ("operation", "inspection_area"),
    [
        ("mixed-use deletion", "Mixed-use expenses"),
        ("transaction deletion", "Transactions ledger"),
        ("payee merge", "Payee management"),
        ("tag removal", "Tag management"),
        ("category deletion", "Categories and the Transactions ledger"),
        ("account update", "Accounts and the Transactions, Mileage, and MixedUseExpenses tables"),
        ("Mileage batch update", "Mileage log"),
    ],
)
def test_mutation_guidance_names_operation_inspection_area(
    operation: str, inspection_area: str
) -> None:
    guidance = _mutation_guidance(operation)

    assert inspection_area in guidance
    assert "inspect" in guidance.casefold()
