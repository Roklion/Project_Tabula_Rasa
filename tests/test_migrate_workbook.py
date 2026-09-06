from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import gspread
import pytest

import scripts.migrate_workbook as migration_script
from scripts.migrate_workbook import (
    _backfill_mixed_use_source_tags,
    _append_columns,
    migrate_workbook,
)
from tabula_rasa.storage.google_sheets import (
    StorageInitializationError,
    StorageValidationError,
    PRE_MIXED_USE_WORKSHEET_HEADERS,
    VERSION_3_WORKSHEET_HEADERS,
    VERSION_7_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
    GoogleSheetsStorage,
    _looks_like_historical_workbook,
)
from tests.fakes import FakeWorkbook


def _append_record(workbook: FakeWorkbook, title: str, values: dict[str, str]) -> None:
    worksheet = workbook.sheets[title]
    row = [""] * len(worksheet.rows[0])
    for field, value in values.items():
        row[worksheet.rows[0].index(field)] = value
    worksheet.rows.append(row)


def test_migrates_standard_pre_mixed_layout_to_current_headers() -> None:
    workbook = FakeWorkbook(VERSION_7_WORKSHEET_HEADERS)

    result = migrate_workbook(workbook)

    assert result["source_tags"] == 0
    for title, headers in WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows[0] == list(headers)
    GoogleSheetsStorage(workbook)


def test_migrates_pre_receipt_v3_layout_to_current_headers() -> None:
    workbook = FakeWorkbook(VERSION_3_WORKSHEET_HEADERS)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense"},
    )
    _append_record(
        workbook,
        "Transactions",
        {
            "id": "transaction-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "payee": "Acme",
            "description": "Supplies",
            "reference": "ref-1",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    result = migrate_workbook(workbook)

    assert result["payees"] == 1
    transaction_headers = workbook.sheets["Transactions"].rows[0]
    assert set(transaction_headers) == set(WORKSHEET_HEADERS["Transactions"])
    transaction = dict(
        zip(transaction_headers, workbook.sheets["Transactions"].rows[1])
    )
    assert transaction["payee_id"]
    assert transaction["description"] == "Supplies"
    assert workbook.sheets["Payees"].rows[1][1] == "Acme"
    GoogleSheetsStorage(workbook)


def test_tag_backfill_rechecks_fresh_source_and_projection_before_writing() -> None:
    workbook = FakeWorkbook(WORKSHEET_HEADERS)
    source = workbook.sheets["MixedUseExpenses"]
    transaction = workbook.sheets["Transactions"]
    _append_record(
        workbook,
        "Transactions",
        {"id": "projection-1", "tag_ids": '["tag-old"]'},
    )
    _append_record(
        workbook,
        "MixedUseExpenses",
        {"id": "source-1", "linked_transaction_id": "projection-1"},
    )
    initial_source = source.get_all_values()
    initial_transaction = transaction.get_all_values()
    fresh_source = [list(row) for row in initial_source]
    fresh_transaction = [list(row) for row in initial_transaction]
    fresh_source[1][fresh_source[0].index("tag_ids")] = '["tag-new"]'
    fresh_transaction[1][fresh_transaction[0].index("tag_ids")] = '["tag-new"]'
    source.rows = fresh_source
    source.batch_update = Mock(wraps=source.batch_update)
    source.get_all_values = Mock(side_effect=[initial_source, fresh_source])
    transaction.get_all_values = Mock(
        side_effect=[initial_transaction, fresh_transaction]
    )

    result = _backfill_mixed_use_source_tags(workbook)

    assert result == 0
    assert source.rows[1][source.rows[0].index("tag_ids")] == '["tag-new"]'
    source.batch_update.assert_not_called()


def test_historical_detection_matches_headers_to_their_worksheet() -> None:
    values = {
        "Accounts": [list(VERSION_3_WORKSHEET_HEADERS["Categories"])],
        "Categories": [list(WORKSHEET_HEADERS["Categories"])],
    }

    assert not _looks_like_historical_workbook(values)


def test_empty_worksheet_not_in_historical_layout_is_not_historical() -> None:
    values = {
        "Accounts": [list(WORKSHEET_HEADERS["Accounts"])],
        "MixedUseExpenses": [[]],
    }

    assert not _looks_like_historical_workbook(values)


def test_historical_detection_handles_missing_mixed_use_tab() -> None:
    values = {
        title: [list(headers)]
        for title, headers in WORKSHEET_HEADERS.items()
        if title != "MixedUseExpenses"
    }

    assert not _looks_like_historical_workbook(values)


def test_migration_validates_hierarchy_before_reporting_success() -> None:
    workbook = FakeWorkbook(WORKSHEET_HEADERS)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "missing-parent",
        },
    )

    with pytest.raises(StorageValidationError, match="does not exist"):
        migrate_workbook(workbook)


def test_migration_validates_relationships_before_reporting_success() -> None:
    workbook = FakeWorkbook(WORKSHEET_HEADERS)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "",
        },
    )
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense", "parent_id": ""},
    )
    _append_record(
        workbook,
        "Transactions",
        {
            "id": "projection-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "source_type": "mixed_use_expense",
            "source_id": "missing-source",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    _append_record(
        workbook,
        "MixedUseExpenses",
        {
            "id": "source-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "total_expense": "100.00",
            "business_use_percentage": "50",
            "allocated_amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "allocation_rationale": "Rationale",
            "linked_transaction_id": "projection-1",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    with pytest.raises(StorageValidationError, match="unknown source"):
        migrate_workbook(workbook)


def test_migration_rejects_receipts_shared_by_transactions() -> None:
    workbook = FakeWorkbook()
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "",
        },
    )
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense", "parent_id": ""},
    )
    reference = {
        "id": "receipt123456",
        "name": "receipt.pdf",
        "receipt_id": "a" * 32,
        "original_filename": "receipt.pdf",
        "mime_type": "application/pdf",
        "byte_size": 7,
        "sha256": "b" * 64,
    }
    for transaction_id in ("transaction-1", "transaction-2"):
        _append_record(
            workbook,
            "Transactions",
            {
                "id": transaction_id,
                "txn_date": "2026-01-01",
                "kind": "Expense",
                "amount": "50.00",
                "account_id": "account-1",
                "category_id": "category-1",
                "receipt_references": json.dumps([reference]),
                "created_at": "2026-01-01T00:00:00Z",
            },
        )

    with pytest.raises(ValueError, match="receipt is referenced by more than one"):
        migrate_workbook(workbook)


def test_header_append_aborts_when_the_worksheet_changed() -> None:
    workbook = FakeWorkbook()
    worksheet = workbook.worksheet("Transactions")
    expected_headers = ["id", "txn_date"]
    before = worksheet.get_all_values()

    with pytest.raises(ValueError, match="headers changed during migration"):
        _append_columns(worksheet, expected_headers, ["receipt_references"])

    assert worksheet.get_all_values() == before


def test_header_append_rechecks_after_adding_columns() -> None:
    workbook = FakeWorkbook()
    worksheet = workbook.worksheet("Transactions")
    expected_headers = list(WORKSHEET_HEADERS["Transactions"])
    original_add_cols = worksheet.add_cols

    def add_cols_then_change(columns: int) -> None:
        original_add_cols(columns)
        worksheet.rows[0][0] = "changed"

    worksheet.add_cols = add_cols_then_change  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="headers changed during migration"):
        _append_columns(worksheet, expected_headers, ["extra"])


def test_header_append_restores_exact_capacity_after_shrink() -> None:
    workbook = FakeWorkbook()
    worksheet = workbook.worksheet("Transactions")
    expected_headers = list(WORKSHEET_HEADERS["Transactions"])
    worksheet.col_count = len(expected_headers) - 2

    updated = _append_columns(worksheet, expected_headers, ["extra"])

    assert updated == [*expected_headers, "extra"]
    assert worksheet.col_count == len(updated)

    column_count_after_abort = worksheet.col_count
    with pytest.raises(ValueError, match="headers changed during migration"):
        _append_columns(worksheet, expected_headers, ["extra"])
    assert worksheet.col_count == column_count_after_abort


def test_migration_clears_custom_provenance_column_collision() -> None:
    headers = dict(PRE_MIXED_USE_WORKSHEET_HEADERS)
    headers["Transactions"] = (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "source_type",
    )
    workbook = FakeWorkbook(headers)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "",
        },
    )
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense", "parent_id": ""},
    )
    _append_record(
        workbook,
        "Transactions",
        {
            "id": "transaction-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "source_type": "legacy custom value",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    migrate_workbook(workbook)

    transaction_sheet = workbook.worksheet("Transactions")
    assert transaction_sheet.rows[1][transaction_sheet.rows[0].index("source_type")] == ""
    assert transaction_sheet.rows[0] == list(WORKSHEET_HEADERS["Transactions"])
    GoogleSheetsStorage(workbook)


def test_migration_rejects_orphaned_provenance_without_source_sheet() -> None:
    headers = dict(PRE_MIXED_USE_WORKSHEET_HEADERS)
    headers["Transactions"] = (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "source_type",
        "source_id",
    )
    workbook = FakeWorkbook(headers)
    _append_record(
        workbook,
        "Transactions",
        {"source_type": "mixed_use_expense", "source_id": "source-1"},
    )

    with pytest.raises(StorageValidationError, match="MixedUseExpenses worksheet"):
        migrate_workbook(workbook)


def test_marker_header_update_aborts_when_the_worksheet_changed() -> None:
    headers = dict(WORKSHEET_HEADERS)
    headers["MixedUseExpenses"] = tuple(
        "tag_ids__migration_pending" if header == "tag_ids" else header
        for header in headers["MixedUseExpenses"]
    )
    workbook = FakeWorkbook(headers)
    mixed = workbook.worksheet("MixedUseExpenses")
    mixed.row_values = Mock(wraps=mixed.row_values)  # type: ignore[method-assign]
    mixed.row_values.return_value = list(WORKSHEET_HEADERS["MixedUseExpenses"])
    before = mixed.get_all_values()

    with pytest.raises(ValueError, match="headers changed during migration"):
        migrate_workbook(workbook)

    assert mixed.get_all_values() == before


def test_marker_header_update_uses_original_header_snapshot() -> None:
    headers = dict(WORKSHEET_HEADERS)
    headers["MixedUseExpenses"] = tuple(
        "tag_ids__migration_pending" if header == "tag_ids" else header
        for header in headers["MixedUseExpenses"]
    )
    workbook = FakeWorkbook(headers)

    migrate_workbook(workbook)

    assert workbook.worksheet("MixedUseExpenses").rows[0] == list(
        WORKSHEET_HEADERS["MixedUseExpenses"]
    )


def test_v9_migration_backfills_source_tags_from_linked_projection() -> None:
    headers = dict(WORKSHEET_HEADERS)
    headers["MixedUseExpenses"] = tuple(
        header
        for header in headers["MixedUseExpenses"]
        if header != "tag_ids"
    )
    workbook = FakeWorkbook(headers)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "",
        },
    )
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense", "parent_id": ""},
    )
    _append_record(
        workbook,
        "Tags",
        {
            "id": "tag-1",
            "name": "Business",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    _append_record(
        workbook,
        "Transactions",
        {
            "id": "projection-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "receipt_references": "",
            "source_type": "mixed_use_expense",
            "source_id": "source-1",
            "tag_ids": '["tag-1"]',
            "description": "Allocation rationale: Rationale",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    _append_record(
        workbook,
        "MixedUseExpenses",
        {
            "id": "source-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "total_expense": "100.00",
            "business_use_percentage": "50",
            "allocated_amount": "50.00",
            "account_id": "account-1",
            "category_id": "category-1",
            "receipt_references": "",
            "allocation_rationale": "Rationale",
            "linked_transaction_id": "projection-1",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    result = migrate_workbook(workbook)

    assert result["source_tags"] == 1
    source = workbook.sheets["MixedUseExpenses"]
    assert source.rows[0][-1] == "tag_ids"
    assert source.rows[1][-1] == '["tag-1"]'
    GoogleSheetsStorage(workbook)


def test_populated_legacy_startup_is_read_only_and_actionable() -> None:
    workbook = FakeWorkbook(VERSION_7_WORKSHEET_HEADERS)
    _append_record(workbook, "Accounts", {"id": "account-1", "name": "Checking"})
    before = {title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()}
    for worksheet in workbook.sheets.values():
        worksheet.add_cols = Mock(wraps=worksheet.add_cols)
        worksheet.update = Mock(wraps=worksheet.update)
    client = Mock()
    client.open_by_key.return_value = workbook

    with (
        patch("tabula_rasa.storage.google_sheets.Credentials.from_service_account_info", return_value=object()),
        patch.object(gspread, "authorize", return_value=client),
        pytest.raises(
            StorageInitializationError,
            match=r"migrate_workbook\.py --profile PROFILE_KEY",
        ),
    ):
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "sheet-1", "gcp_service_account": {"type": "service_account"}}
        )

    assert before == {
        title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()
    }
    for worksheet in workbook.sheets.values():
        worksheet.add_cols.assert_not_called()
        worksheet.update.assert_not_called()


def test_populated_v9_startup_is_read_only_and_actionable() -> None:
    headers = dict(WORKSHEET_HEADERS)
    headers["MixedUseExpenses"] = tuple(
        header
        for header in headers["MixedUseExpenses"]
        if header != "tag_ids"
    )
    workbook = FakeWorkbook(headers)
    _append_record(
        workbook,
        "Accounts",
        {
            "id": "account-1",
            "name": "Checking",
            "type": "Bank",
            "classification": "Asset",
            "opening_balance": "0.00",
            "active": "TRUE",
            "created_at": "2026-01-01T00:00:00Z",
            "parent_id": "",
        },
    )
    before = {title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()}
    for worksheet in workbook.sheets.values():
        worksheet.add_cols = Mock(wraps=worksheet.add_cols)
        worksheet.update = Mock(wraps=worksheet.update)
        worksheet.append_rows = Mock(wraps=worksheet.append_rows)
    client = Mock()
    client.open_by_key.return_value = workbook

    with (
        patch("tabula_rasa.storage.google_sheets.Credentials.from_service_account_info", return_value=object()),
        patch.object(gspread, "authorize", return_value=client),
        pytest.raises(
            StorageInitializationError,
            match=r"migrate_workbook\.py --profile PROFILE_KEY",
        ),
    ):
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "sheet-1", "gcp_service_account": {"type": "service_account"}}
        )

    assert before == {
        title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()
    }
    for worksheet in workbook.sheets.values():
        worksheet.add_cols.assert_not_called()
        worksheet.update.assert_not_called()
        worksheet.append_rows.assert_not_called()


def test_partial_blank_startup_resumes_current_headers() -> None:
    workbook = FakeWorkbook()
    for worksheet in workbook.sheets.values():
        worksheet.rows = []
    workbook.sheets["Accounts"].rows = [list(WORKSHEET_HEADERS["Accounts"])]
    client = Mock()
    client.open_by_key.return_value = workbook

    with (
        patch(
            "tabula_rasa.storage.google_sheets.Credentials.from_service_account_info",
            return_value=object(),
        ),
        patch("tabula_rasa.storage.google_sheets.gspread.authorize", return_value=client),
    ):
        GoogleSheetsStorage.from_secrets(
            {
                "spreadsheet_id": "sheet-1",
                "gcp_service_account": {"type": "service_account"},
            }
        )

    for title, headers in WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows == [list(headers)]


def test_migration_validates_transaction_domains_before_success() -> None:
    workbook = FakeWorkbook()
    _append_record(
        workbook,
        "Categories",
        {"id": "category-1", "name": "Office", "kind": "Expense"},
    )
    _append_record(
        workbook,
        "Transactions",
        {
            "id": "transaction-1",
            "txn_date": "2026-01-01",
            "kind": "Expense",
            "amount": "50.00",
            "account_id": "missing-account",
            "category_id": "category-1",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    with pytest.raises(StorageValidationError, match="Source account does not exist"):
        migrate_workbook(workbook)


def test_migration_validates_mileage_domains_before_success() -> None:
    workbook = FakeWorkbook()
    _append_record(
        workbook,
        "Mileage",
        {
            "id": "mileage-1",
            "trip_date": "not-a-date",
            "miles": "10.0",
            "start_location": "Office",
            "destination": "Client",
            "business_purpose": "Visit",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    with pytest.raises(StorageValidationError, match="Date must use"):
        migrate_workbook(workbook)


def test_migration_rejects_duplicate_mileage_ids_before_success() -> None:
    workbook = FakeWorkbook()
    for _ in range(2):
        _append_record(
            workbook,
            "Mileage",
            {
                "id": "mileage-1",
                "trip_date": "2026-01-01",
                "miles": "10.0",
                "start_location": "Office",
                "destination": "Client",
                "business_purpose": "Visit",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )

    with pytest.raises(StorageValidationError, match="Mileage IDs must be unique"):
        migrate_workbook(workbook)


def test_migration_resumes_partial_blank_initialization() -> None:
    workbook = FakeWorkbook()
    for worksheet in workbook.sheets.values():
        worksheet.rows = []
    workbook.sheets["Accounts"].rows = [list(WORKSHEET_HEADERS["Accounts"])]

    result = migrate_workbook(workbook)

    assert result == {"worksheets": len(WORKSHEET_HEADERS), "source_tags": 0}
    for title, headers in WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows == [list(headers)]


def test_migration_rejects_missing_core_tab_before_creating_any_tab() -> None:
    workbook = FakeWorkbook(VERSION_7_WORKSHEET_HEADERS)
    del workbook.sheets["Transactions"]
    _append_record(workbook, "Accounts", {"id": "account-1", "name": "Checking"})
    before = {title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()}
    workbook.add_worksheet = Mock(wraps=workbook.add_worksheet)
    for worksheet in workbook.sheets.values():
        worksheet.update = Mock(wraps=worksheet.update)

    with pytest.raises(ValueError, match="missing core worksheets: Transactions"):
        migrate_workbook(workbook)

    assert before == {
        title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()
    }
    workbook.add_worksheet.assert_not_called()
    for worksheet in workbook.sheets.values():
        worksheet.update.assert_not_called()


def test_cli_profile_selection_isolated_to_selected_workbook() -> None:
    document = {"business_profiles": {"north": {}, "south": {}}}
    south_secrets = {
        "spreadsheet_id": "south-sheet",
        "gcp_service_account": {"client_email": "south@example.invalid"},
    }
    client = Mock()
    workbook = FakeWorkbook()
    client.open_by_key.return_value = workbook

    with (
        patch.object(migration_script, "load_business_profile_document", return_value=document),
        patch.object(
            migration_script,
            "select_profile_secrets",
            side_effect=lambda selected_document, profile: (
                south_secrets
                if selected_document is document and profile == "south"
                else AssertionError(f"unexpected profile: {profile}")
            ),
        ) as select_profile,
        patch.object(migration_script.Credentials, "from_service_account_info", return_value=object()) as credentials,
        patch.object(gspread, "authorize", return_value=client),
        patch.object(migration_script, "migrate_workbook", return_value={}),
        patch.object(
            sys,
            "argv",
            ["migrate_workbook.py", "--secrets", "profiles.toml", "--profile", "south"],
        ),
    ):
        migration_script.main()

    select_profile.assert_called_once_with(document, "south")
    credentials.assert_called_once_with(
        south_secrets["gcp_service_account"], scopes=[migration_script.SHEETS_SCOPE]
    )
    client.open_by_key.assert_called_once_with("south-sheet")


def test_cli_candidate_workbook_uses_explicit_service_account_file() -> None:
    credential_file = Path("service-account.json")
    credential_info = {"client_email": "candidate@example.invalid"}
    client = Mock()
    workbook = FakeWorkbook()
    client.open_by_key.return_value = workbook

    with (
        patch.object(
            migration_script.Credentials,
            "from_service_account_info",
            return_value=object(),
        ) as credentials,
        patch.object(gspread, "authorize", return_value=client),
        patch.object(migration_script, "migrate_workbook", return_value={}) as migrate,
        patch.object(
            Path,
            "read_text",
            return_value=json.dumps(credential_info),
        ) as read_text,
        patch.object(
            sys,
            "argv",
            [
                "migrate_workbook.py",
                "--spreadsheet-id",
                "candidate-sheet",
                "--service-account-file",
                str(credential_file),
            ],
        ),
    ):
        migration_script.main()

    credentials.assert_called_once_with(
        credential_info, scopes=[migration_script.SHEETS_SCOPE]
    )
    read_text.assert_called_once_with(encoding="utf-8")
    client.open_by_key.assert_called_once_with("candidate-sheet")
    migrate.assert_called_once_with(workbook)


def test_cli_reports_expected_migration_errors() -> None:
    with (
        patch.object(
            migration_script,
            "load_business_profile_document",
            return_value={"business_profiles": {"test": {}}},
        ),
        patch.object(
            migration_script,
            "select_profile_secrets",
            return_value={
                "spreadsheet_id": "sheet-1",
                "gcp_service_account": {"client_email": "test@example.invalid"},
            },
        ),
        patch.object(
            migration_script.Credentials,
            "from_service_account_info",
            side_effect=ValueError("invalid credential"),
        ),
        patch.object(
            sys,
            "argv",
            ["migrate_workbook.py", "--profile", "test"],
        ),
        pytest.raises(SystemExit, match="Workbook migration failed: invalid credential"),
    ):
        migration_script.main()


def test_migration_preflights_malformed_tabs_before_writing() -> None:
    headers = dict(VERSION_7_WORKSHEET_HEADERS)
    headers["Accounts"] = ("id", "name")
    workbook = FakeWorkbook(headers)
    before = {title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()}

    with pytest.raises(ValueError, match="recognized standard layout"):
        migrate_workbook(workbook)

    assert before == {
        title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()
    }
