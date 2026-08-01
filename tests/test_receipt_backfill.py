from __future__ import annotations

import hashlib
from unittest.mock import Mock

from scripts.backfill_receipt_checksums import backfill_profile_receipts
from tabula_rasa.storage import GoogleSheetsStorage, decode_receipt_references
from tests.fakes import FakeWorkbook


def _legacy_drive_receipt(profile_key: str) -> dict[str, object]:
    return {
        "id": "receipt123456",
        "name": "statement.pdf",
        "mimeType": "application/pdf",
        "size": "7",
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
        },
    }


def _backfilled_drive_receipt(profile_key: str) -> dict[str, object]:
    receipt = _legacy_drive_receipt(profile_key)
    receipt["appProperties"] = {
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
    north_drive.list_profile_receipts.return_value = []

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
