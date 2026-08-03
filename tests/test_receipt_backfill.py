from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest

from tabula_rasa.receipt_backfill import (
    ReceiptPreparationError,
    backfill_profile_receipts,
    prepare_backup_receipt_manifest,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    StorageUnavailableError,
)
from tests.fakes import FakeWorkbook


def _set_raw_receipt_references(
    workbook: FakeWorkbook,
    *,
    transaction_id: str,
    value: str,
) -> None:
    worksheet = workbook.worksheet("Transactions")
    headers = worksheet.rows[0]
    id_index = headers.index("id")
    references_index = headers.index("receipt_references")
    row = next(
        item for item in worksheet.rows[1:] if item[id_index] == transaction_id
    )
    row[references_index] = value


def _legacy_drive_receipt(
    profile_key: str,
    *,
    transaction_id: str = "",
) -> dict[str, object]:
    properties = {
        "tabulaRasaKind": "receipt",
        "tabulaRasaProfile": profile_key,
    }
    if transaction_id:
        properties["tabulaRasaTransaction"] = transaction_id
    receipt: dict[str, object] = {
        "id": "receipt123456",
        "name": "statement.pdf",
        "mimeType": "application/pdf",
        "size": "7",
        "appProperties": properties,
    }
    return receipt


def _backfilled_drive_receipt(
    profile_key: str,
    *,
    transaction_id: str = "",
) -> dict[str, object]:
    receipt = _legacy_drive_receipt(
        profile_key,
        transaction_id=transaction_id,
    )
    properties = receipt["appProperties"]
    assert isinstance(properties, dict)
    receipt["appProperties"] = {
        **properties,
        "tabulaRasaKind": "receipt",
        "tabulaRasaProfile": profile_key,
        "tabulaRasaReceiptId": "a" * 32,
        "tabulaRasaSha256": hashlib.sha256(b"receipt").hexdigest(),
        "tabulaRasaOriginalName": "statement.pdf",
    }
    return receipt


def test_backfill_updates_drive_and_active_transaction_reference() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Transfer",
        amount=10,
        account_id=account["id"],
        to_account_id=storage.create_account("Savings", "Bank")["id"],
    )
    storage.link_transaction_receipt(
        transaction["id"],
        file_id="receipt123456",
        name="statement.pdf",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_drive_receipt("north")]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt("north")

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report == {
        "examined": 1,
        "drive_backfilled": 1,
        "references_updated": 1,
        "errors": [],
    }
    drive.backfill_receipt_checksum.assert_called_once_with(
        profile_key="north",
        folder_id="folder123456",
        file_id="receipt123456",
    )
    reference = decode_receipt_references(
        storage.list_transactions(_force_refresh=True)[0]["receipt_references"]
    )[0]
    assert reference["receipt_id"] == "a" * 32
    assert reference["sha256"] == hashlib.sha256(b"receipt").hexdigest()


def test_backfill_migrates_a_drive_only_transaction_association() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=storage.create_category("Sales", "Income")["id"],
    )
    _set_raw_receipt_references(
        workbook,
        transaction_id=transaction["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=transaction["id"])
    ]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt(
        "north",
        transaction_id=transaction["id"],
    )

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report == {
        "examined": 1,
        "drive_backfilled": 1,
        "references_updated": 1,
        "errors": [],
    }
    current = storage.list_transactions(_force_refresh=True)[0]
    reference = decode_receipt_references(current["receipt_references"])[0]
    assert reference["id"] == "receipt123456"
    assert reference["receipt_id"] == "a" * 32


def test_backfill_does_not_override_a_concurrent_explicit_unlink() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=storage.create_category("Sales", "Income")["id"],
    )
    _set_raw_receipt_references(
        workbook,
        transaction_id=transaction["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=transaction["id"])
    ]

    def unlink_before_initialization(**_scope: str) -> dict[str, object]:
        storage.set_transaction_receipt_references(transaction["id"], [])
        return _backfilled_drive_receipt(
            "north",
            transaction_id=transaction["id"],
        )

    drive.backfill_receipt_checksum.side_effect = unlink_before_initialization

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert current["receipt_references"] == "[]"
    assert report["references_updated"] == 0
    assert len(report["errors"]) == 1


def test_backfill_respects_an_explicitly_empty_reference_list() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=storage.create_category("Sales", "Income")["id"],
    )
    storage.set_transaction_receipt_references(transaction["id"], [])
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=transaction["id"])
    ]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt(
        "north",
        transaction_id=transaction["id"],
    )

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert current["receipt_references"] == "[]"
    assert report["drive_backfilled"] == 1
    assert report["references_updated"] == 0


def test_backfill_does_not_touch_another_profile_storage() -> None:
    north_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    south_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    south_account = south_storage.create_account("Checking", "Bank")
    south_transaction = south_storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=south_account["id"],
        category_id=south_storage.create_category("Sales", "Income")["id"],
    )
    south_storage.link_transaction_receipt(
        south_transaction["id"],
        file_id="receipt123456",
        name="south.pdf",
    )
    north_drive = Mock()
    north_drive.list_profile_receipts.return_value = [
        _backfilled_drive_receipt(
            "north",
            transaction_id=south_transaction["id"],
        )
    ]

    backfill_profile_receipts(
        north_storage,
        north_drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    south_reference = decode_receipt_references(
        south_storage.list_transactions(_force_refresh=True)[0][
            "receipt_references"
        ]
    )[0]
    assert south_reference == {"id": "receipt123456", "name": "south.pdf"}


def test_backfill_does_not_download_receipts_with_valid_integrity_metadata() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    drive = Mock()
    drive.list_profile_receipts.return_value = [_backfilled_drive_receipt("north")]

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    assert report == {
        "examined": 1,
        "drive_backfilled": 0,
        "references_updated": 0,
        "errors": [],
    }
    drive.backfill_receipt_checksum.assert_not_called()


def test_backfill_does_not_restore_a_concurrently_unlinked_reference() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=storage.create_category("Sales", "Income")["id"],
    )
    storage.link_transaction_receipt(
        transaction["id"],
        file_id="receipt123456",
        name="statement.pdf",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_drive_receipt("north")]

    def unlink_before_backfill(**_scope: str) -> dict[str, object]:
        storage.unlink_transaction_receipt(
            transaction["id"],
            file_id="receipt123456",
        )
        return _backfilled_drive_receipt("north")

    drive.backfill_receipt_checksum.side_effect = unlink_before_backfill

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"]) == []
    assert report["references_updated"] == 0
    assert len(report["errors"]) == 1


def test_backfill_reports_reference_failure_and_remains_resumable() -> None:
    reference = _backfilled_drive_receipt("north")
    storage = Mock()
    storage.list_transactions.return_value = [
        {
            "id": "transaction-1",
            "receipt_references": (
                '[{"id":"receipt123456","name":"statement.pdf"}]'
            ),
        }
    ]
    storage.remap_transaction_receipt.side_effect = StorageUnavailableError(
        "temporary Sheets failure"
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [reference]

    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    assert report["drive_backfilled"] == 0
    assert report["references_updated"] == 0
    assert len(report["errors"]) == 1
    storage.remap_transaction_receipt.assert_called_once()
    call = storage.remap_transaction_receipt.call_args
    assert call.args == ("transaction-1",)
    assert call.kwargs["old_file_id"] == "receipt123456"
    assert call.kwargs["reference"]["receipt_id"] == "a" * 32


def test_preparation_reconciles_filename_and_returns_fresh_manifest() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=storage.create_category("Sales", "Income")["id"],
    )
    storage.set_transaction_receipt_references(
        transaction["id"],
        [
            {
                "id": "receipt123456",
                "name": "old-name.pdf",
                "receipt_id": "a" * 32,
                "sha256": hashlib.sha256(b"receipt").hexdigest(),
                "original_filename": "statement.pdf",
                "mime_type": "application/pdf",
                "byte_size": 7,
            }
        ],
    )
    receipt = _backfilled_drive_receipt("north")
    receipt["name"] = "renamed-in-drive.pdf"
    drive = Mock()
    drive.list_profile_receipts.return_value = [receipt]

    manifest = prepare_backup_receipt_manifest(
        storage,
        drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"])[0]["name"] == (
        "renamed-in-drive.pdf"
    )
    assert manifest["receipts"][0]["stored_filename"] == "renamed-in-drive.pdf"
    drive.backfill_receipt_checksum.assert_not_called()
    assert drive.list_profile_receipts.call_count == 2


def test_preparation_aborts_backup_manifest_after_partial_failure() -> None:
    storage = Mock()
    storage.list_transactions.return_value = [
        {
            "id": "transaction-1",
            "receipt_references": '[{"id":"receipt123456","name":"old.pdf"}]',
        }
    ]
    storage.remap_transaction_receipt.side_effect = StorageUnavailableError(
        "temporary Sheets failure"
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_backfilled_drive_receipt("north")]

    with pytest.raises(ReceiptPreparationError, match="no backup was created"):
        prepare_backup_receipt_manifest(
            storage,
            drive,
            profile_key="north",
            folder_id="northfolder123",
        )

    assert drive.list_profile_receipts.call_count == 1
