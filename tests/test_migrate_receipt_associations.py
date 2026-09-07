from __future__ import annotations

import hashlib
from unittest.mock import Mock

from scripts.migrate_receipt_associations import migrate_receipt_associations
from tabula_rasa.storage import decode_receipt_references, GoogleSheetsStorage
from tests.fakes import FakeWorkbook


def _set_receipts_cell(
    storage: GoogleSheetsStorage,
    *,
    worksheet: str,
    record_id: str,
    value: str,
) -> None:
    sheet = storage._worksheet(worksheet)
    headers = storage._headers(worksheet)
    id_index = headers.index("id")
    receipt_index = headers.index("receipt_references")
    row = next(row for row in sheet.rows[1:] if row[id_index] == record_id)
    row[receipt_index] = value
    storage._invalidate(worksheet)


def _legacy_receipt(transaction_id: str, *, integrity: bool = True) -> dict:
    properties = {
        "tabulaRasaKind": "receipt",
        "tabulaRasaProfile": "north",
        "tabulaRasaTransaction": transaction_id,
    }
    if integrity:
        properties.update(
            {
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": hashlib.sha256(b"receipt").hexdigest(),
                "tabulaRasaOriginalName": "statement.pdf",
            }
        )
    return {
        "id": "receipt123456",
        "name": "statement.pdf",
        "mimeType": "application/pdf",
        "size": "7",
        "appProperties": properties,
    }


def _expense_inputs(storage: GoogleSheetsStorage) -> dict[str, str]:
    storage.ensure_defaults()
    return {
        "txn_date": "2026-09-07",
        "account_id": storage.list_accounts()[0]["id"],
        "category_id": next(
            category["id"]
            for category in storage.list_categories()
            if category["kind"] == "Expense"
        ),
    }


def test_migrates_drive_only_association_into_blank_current_column() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    transaction = storage.create_transaction(
        **_expense_inputs(storage),
        kind="Expense",
        amount="10",
    )
    _set_receipts_cell(
        storage,
        worksheet="Transactions",
        record_id=transaction["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_receipt(transaction["id"])]

    report = migrate_receipt_associations(
        storage,
        drive,
        profile_key="north",
        folder_id="north-folder",
    )

    assert report == {"associations_migrated": 1, "checksums_backfilled": 0}
    reference = decode_receipt_references(
        storage.list_transactions(_force_refresh=True)[0]["receipt_references"]
    )[0]
    assert reference["id"] == "receipt123456"
    drive.list_profile_receipts.assert_called_once_with(
        profile_key="north",
        folder_id="north-folder",
        _force_refresh=True,
    )


def test_migrates_mixed_use_association_through_source_pair() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    source = storage.create_mixed_use_expense(
        **_expense_inputs(storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    projection_id = source["linked_transaction_id"]
    _set_receipts_cell(
        storage,
        worksheet="Transactions",
        record_id=projection_id,
        value="",
    )
    _set_receipts_cell(
        storage,
        worksheet="MixedUseExpenses",
        record_id=source["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_receipt(projection_id)]

    migrate_receipt_associations(
        storage,
        drive,
        profile_key="north",
        folder_id="north-folder",
    )

    refreshed_source = storage.get_mixed_use_expense(source["id"])
    projection = next(
        transaction
        for transaction in storage.list_transactions(_force_refresh=True)
        if transaction["id"] == projection_id
    )
    assert refreshed_source["receipt_references"] == projection["receipt_references"]
    assert decode_receipt_references(projection["receipt_references"])[0]["id"] == (
        "receipt123456"
    )


def test_explicitly_empty_current_receipts_are_not_historical_candidates() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    transaction = storage.create_transaction(
        **_expense_inputs(storage),
        kind="Expense",
        amount="10",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_receipt(transaction["id"])]

    report = migrate_receipt_associations(
        storage,
        drive,
        profile_key="north",
        folder_id="north-folder",
    )

    assert report == {"associations_migrated": 0, "checksums_backfilled": 0}
    assert storage.list_transactions(_force_refresh=True)[0][
        "receipt_references"
    ] == "[]"


def test_missing_integrity_metadata_is_backfilled_only_in_migration_tool() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    transaction = storage.create_transaction(
        **_expense_inputs(storage),
        kind="Expense",
        amount="10",
    )
    _set_receipts_cell(
        storage,
        worksheet="Transactions",
        record_id=transaction["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_receipt(transaction["id"], integrity=False)
    ]
    drive.backfill_receipt_checksum.return_value = _legacy_receipt(
        transaction["id"]
    )

    report = migrate_receipt_associations(
        storage,
        drive,
        profile_key="north",
        folder_id="north-folder",
    )

    assert report == {"associations_migrated": 1, "checksums_backfilled": 1}
    drive.backfill_receipt_checksum.assert_called_once_with(
        profile_key="north",
        folder_id="north-folder",
        file_id="receipt123456",
    )
