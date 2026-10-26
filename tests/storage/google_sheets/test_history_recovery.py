"""Rich final-format recovery preserves frozen history without generation APIs."""
import json

import pytest

from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage, StorageConflictError
from tests.fakes import FakeWorkbook
from tests.migration_support import complete_plan, put
from tests.storage.google_sheets._support import TEST_RECEIPT_REFERENCE, drive_file_from_reference


def history_source(profile):
    _, values, _ = complete_plan(profile)
    ordinary = {**TEST_RECEIPT_REFERENCE, "id": "ordinaryreceipt123"}
    mixed = {**TEST_RECEIPT_REFERENCE, "id": "mixedreceipt123", "receipt_id": "c" * 32, "name": "mixed-receipt.pdf", "original_filename": "mixed-receipt.pdf"}
    for title, index, reference in (("Transactions", 1, mixed), ("MixedUseExpenses", 1, mixed), ("Transactions", 3, ordinary)):
        put(values, title, index, receipt_references=json.dumps([reference]))
    workbook = FakeWorkbook()
    for title, rows in values.items():
        workbook.sheets[title].rows = rows
    source = GoogleSheetsStorage(workbook)
    manifest = build_receipt_manifest(profile, source.list_transactions(_force_refresh=True), [
        drive_file_from_reference(reference, profile_key=profile) for reference in (ordinary, mixed)
    ])
    return source, manifest


@pytest.mark.parametrize("profile", ["north", "south"])
def test_format13_roundtrip_keeps_recurring_journal_asset_and_receipt_history(profile):
    source, manifest = history_source(profile)
    workbook = source._workbook
    archive = source.export_backup_zip(manifest)
    before = {title: sheet.get_all_values() for title, sheet in workbook.sheets.items()}
    target = GoogleSheetsStorage(FakeWorkbook())
    counts = target.restore_backup_zip(archive)
    assert source.validate_backup_zip(archive)["business_profile_key"] == profile
    assert counts["RecurringSchedules"] == 2
    assert counts["JournalPostings"] == 4
    assert counts["Assets"] == 1
    for title in before:
        assert target._workbook.sheets[title].rows == before[title]
    assert target.receipt_manifest_from_backup(archive)["business_profile_key"] == profile
    with pytest.raises(StorageConflictError, match="empty"):
        target.restore_backup_zip(archive)
    assert {title: sheet.get_all_values() for title, sheet in workbook.sheets.items()} == before


def test_backup_normalizes_stored_schedule_enums_without_mutating_source():
    source, manifest = history_source("north")
    sheet = source._workbook.sheets["RecurringSchedules"]
    fields = sheet.rows[0]
    for field, value in {"kind": " expense ", "source_kind": " transaction ",
                         "recurrence_unit": "months", "status": "PAUSED",
                         "account_id": " cash ", "category_id": " office "}.items():
        sheet.rows[1][fields.index(field)] = value
    before = sheet.get_all_values()
    archive = source.export_backup_zip(manifest)
    target = GoogleSheetsStorage(FakeWorkbook())
    target.restore_backup_zip(archive)
    schedule = target._find_row("RecurringSchedules", "schedule").values
    assert {key: schedule[key] for key in ("kind", "source_kind", "recurrence_unit", "status", "account_id", "category_id")} == {
        "kind": "Expense", "source_kind": "transaction", "recurrence_unit": "month",
        "status": "paused", "account_id": "cash", "category_id": "office",
    }
    assert sheet.get_all_values() == before


def test_backup_normalizes_mixed_schedule_allocation_before_final_validation():
    source, manifest = history_source("north")
    sheet = source._workbook.sheets["RecurringSchedules"]
    sheet.rows[2][sheet.rows[0].index("amount")] = "99.00"
    archive = source.export_backup_zip(manifest)
    target = GoogleSheetsStorage(FakeWorkbook())
    target.restore_backup_zip(archive)
    assert target._find_row("RecurringSchedules", "mixed-schedule").values["amount"] == "12.50"
    assert sheet.rows[2][sheet.rows[0].index("amount")] == "99.00"
