from __future__ import annotations

from unittest.mock import Mock, patch

import gspread
import pytest

from scripts.migrate_workbook import migrate_workbook
from tabula_rasa.storage.google_sheets import (
    StorageInitializationError,
    VERSION_7_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
    GoogleSheetsStorage,
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
        pytest.raises(StorageInitializationError, match="migrate_workbook.py"),
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
