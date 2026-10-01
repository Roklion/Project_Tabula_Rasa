from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

import json
import sys
from unittest.mock import Mock, call, patch

import gspread
import pytest

import scripts.migrate_workbook as migration_script
from scripts.migrate_workbook import migrate_workbook
from scripts.migrate_workbook import _reorder_columns
from tabula_rasa.storage.google_sheets import (
    StorageInitializationError,
    StorageValidationError,
    WORKSHEET_HEADERS,
    GoogleSheetsStorage,
)
from tabula_rasa.storage.google_sheets.validation import (
    _looks_like_historical_workbook,
)
from scripts.migration_schemas import (
    LEGACY_TAGS_WORKBOOK_HEADERS,
    VERSION_3_WORKSHEET_HEADERS,
    VERSION_7_WORKSHEET_HEADERS,
    VERSION_10_WORKSHEET_HEADERS,
    VERSION_11_WORKSHEET_HEADERS,
    VERSION_12_WORKSHEET_HEADERS,
)
from tests.fakes import FakeWorkbook, FakeWorksheet


def test_version_11_workbook_adds_empty_assets_sheet() -> None:
    workbook = FakeWorkbook(VERSION_11_WORKSHEET_HEADERS)

    migrate_workbook(workbook)

    assert workbook.sheets["Assets"].rows == [list(WORKSHEET_HEADERS["Assets"])]
    for title, headers in VERSION_11_WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows[0] == list(headers)


def test_version_12_workbook_adds_empty_journal_sheets() -> None:
    workbook = FakeWorkbook(VERSION_12_WORKSHEET_HEADERS)

    migrate_workbook(workbook)

    for title in ("JournalEntries", "JournalPostings"):
        assert workbook.sheets[title].rows == [list(WORKSHEET_HEADERS[title])]
    GoogleSheetsStorage(workbook)


def test_populated_version_12_is_recognized_as_historical() -> None:
    values = {
        title: [list(headers)] for title, headers in VERSION_12_WORKSHEET_HEADERS.items()
    }
    values["Accounts"].append(["account-1"])

    assert _looks_like_historical_workbook(values)


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


def test_migrates_prior_v10_layout_to_current_headers_and_empty_schedules() -> None:
    workbook = FakeWorkbook(VERSION_10_WORKSHEET_HEADERS)

    result = migrate_workbook(workbook)

    assert result["source_tags"] == 0
    for title, headers in WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows[0] == list(headers)
    assert workbook.sheets["RecurringSchedules"].rows == [
        list(WORKSHEET_HEADERS["RecurringSchedules"])
    ]
    GoogleSheetsStorage(workbook)


def test_migration_repairs_an_existing_blank_schedule_sheet() -> None:
    workbook = FakeWorkbook(VERSION_10_WORKSHEET_HEADERS)
    workbook.add_worksheet("RecurringSchedules", rows=1000, cols=len(WORKSHEET_HEADERS["RecurringSchedules"]))

    migrate_workbook(workbook)

    assert workbook.sheets["RecurringSchedules"].rows == [
        list(WORKSHEET_HEADERS["RecurringSchedules"])
    ]


def test_reorder_columns_fills_missing_expected_columns() -> None:
    worksheet = Mock()
    worksheet.get_all_values.return_value = [["name"], ["Office"]]

    assert _reorder_columns(worksheet, ["name"], ("id", "name")) == ["id", "name"]
    worksheet.update.assert_called_once_with(
        [["id", "name"], ["", "Office"]], range_name="A1", raw=True
    )
    worksheet.resize.assert_called_once_with(rows=2, cols=2)


def test_reorder_columns_expands_before_updating_a_small_worksheet() -> None:
    worksheet = Mock(row_count=1, col_count=1)
    worksheet.get_all_values.return_value = [["name"], ["Office"]]

    _reorder_columns(worksheet, ["name"], ("id", "name"))

    assert worksheet.resize.call_args_list == [call(rows=2, cols=2), call(rows=2, cols=2)]
    worksheet.update.assert_called_once_with(
        [["id", "name"], ["", "Office"]], range_name="A1", raw=True
    )


def test_reorder_columns_clears_trailing_worksheet_data() -> None:
    worksheet = FakeWorksheet("Legacy", ("name", "legacy"))
    worksheet.rows.append(["Office", "stale"])

    assert _reorder_columns(worksheet, ["name", "legacy"], ("id", "name")) == [
        "id", "name"
    ]
    assert worksheet.rows == [["id", "name"], ["", "Office"]]


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


def test_historical_detection_tolerates_empty_mixed_use_values() -> None:
    values = {"MixedUseExpenses": None}

    assert not _looks_like_historical_workbook(values)


def test_historical_detection_handles_missing_mixed_use_tab() -> None:
    values = {
        title: [list(headers)]
        for title, headers in WORKSHEET_HEADERS.items()
        if title != "MixedUseExpenses"
    }

    assert not _looks_like_historical_workbook(values)


def test_historical_detection_handles_interrupted_tag_migration() -> None:
    values = {
        title: [list(headers)]
        for title, headers in LEGACY_TAGS_WORKBOOK_HEADERS.items()
    }

    assert _looks_like_historical_workbook(values)


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
    assert source.rows[0] == list(WORKSHEET_HEADERS["MixedUseExpenses"])
    assert source.rows[1][source.rows[0].index("tag_ids")] == '["tag-1"]'
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
        patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials", return_value=object()),
        patch.object(gspread, "authorize", return_value=client),
        pytest.raises(
            StorageInitializationError,
            match=r"migrate_workbook\.py --profile PROFILE_KEY",
        ),
    ):
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "sheet-1", "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG}
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
        patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials", return_value=object()),
        patch.object(gspread, "authorize", return_value=client),
        pytest.raises(
            StorageInitializationError,
            match=r"migrate_workbook\.py --profile PROFILE_KEY",
        ),
    ):
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "sheet-1", "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG}
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
            "tabula_rasa.storage.google_sheets.client.profile_google_credentials",
            return_value=object(),
        ),
        patch("tabula_rasa.storage.google_sheets.gspread.authorize", return_value=client),
    ):
        GoogleSheetsStorage.from_secrets(
            {
                "spreadsheet_id": "sheet-1",
                "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
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
        "google_drive": google_grant('south@example.invalid'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
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
        patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials", return_value=object()) as credentials,
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
        south_secrets
    )
    client.open_by_key.assert_called_once_with("south-sheet")




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
                "google_drive": google_grant('test@example.invalid'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
            },
        ),
        patch(
            "tabula_rasa.storage.google_sheets.client.profile_google_credentials",
            side_effect=ValueError("invalid credential"),
        ),
        patch.object(
            sys,
            "argv",
            ["migrate_workbook.py", "--profile", "test"],
        ),
        pytest.raises(SystemExit, match="Workbook migration failed. Confirm Google OAuth access"),
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


def test_migration_preflights_malformed_recurring_schedules_before_writing() -> None:
    headers = dict(VERSION_11_WORKSHEET_HEADERS)
    headers["RecurringSchedules"] = tuple(
        header
        for header in headers["RecurringSchedules"]
        if header != "recurrence_unit"
    )
    workbook = FakeWorkbook(headers)
    before = {
        title: worksheet.get_all_values()
        for title, worksheet in workbook.sheets.items()
    }

    with pytest.raises(ValueError, match="recognized standard layout"):
        migrate_workbook(workbook)

    assert "Assets" not in workbook.sheets
    assert before == {
        title: worksheet.get_all_values() for title, worksheet in workbook.sheets.items()
    }


@pytest.mark.parametrize("target", ["north-ledger-123", "south-ledger-123", "candidate-ledger-123"])
def test_cli_override_refuses_all_live_ledgers_and_preserves_profile_grant(target):
    document = {
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        "business_profiles": {
            "north": {"name": "North", "spreadsheet_id": "north-ledger-123",
                      "google_drive": google_grant("same@example.test", "north-token")},
            "south": {"name": "South", "spreadsheet_id": "south-ledger-123",
                      "google_drive": google_grant("same@example.test", "south-token")},
        },
    }
    with (
        patch.object(migration_script, "load_business_profile_document", return_value=document),
        patch.object(GoogleSheetsStorage, "_open_workbook_from_secrets") as open_workbook,
        patch.object(migration_script, "migrate_workbook", return_value={}) as migrate,
        patch.object(sys, "argv", ["migrate_workbook.py", "--profile", "north",
                                   "--spreadsheet-id", target]),
    ):
        if target != "candidate-ledger-123":
            with pytest.raises(SystemExit) as error:
                migration_script.main()
            assert error.value.code == 2
            open_workbook.assert_not_called()
            migrate.assert_not_called()
        else:
            migration_script.main()
            assert open_workbook.call_args.args[0]["spreadsheet_id"] == target
            assert open_workbook.call_args.args[0]["google_drive"]["refresh_token"] == "north-token"
            migrate.assert_called_once_with(open_workbook.return_value)
