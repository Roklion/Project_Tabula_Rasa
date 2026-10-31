from __future__ import annotations
from tests.sheets_fixtures import account as fixture_account, category as fixture_category, mixed as fixture_mixed, mixed_row as fixture_mixed_row, payee as fixture_payee, receipts as fixture_receipts, transaction as fixture_transaction

import hashlib
from unittest.mock import Mock

import pytest

from tabula_rasa.receipt_backfill import (
    ReceiptPreparationError,
    prepare_backup_receipt_manifest,
    prepare_profile_receipts,
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
    worksheet_title: str = "Transactions",
    transaction_id: str,
    value: str,
) -> None:
    worksheet = workbook.worksheet(worksheet_title)
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


def test_preparation_updates_drive_and_active_transaction_reference(
    storage: GoogleSheetsStorage,
) -> None:
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Transfer",
        amount=10,
        account_id=account["id"],
        to_account_id=fixture_account(storage, "Savings", "Bank")["id"],
    )
    fixture_receipts(storage,
        transaction["id"],
        file_id="receipt123456",
        name="statement.pdf",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_drive_receipt("north")]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt("north")

    report = prepare_profile_receipts(
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


def test_preparation_routes_mixed_use_receipt_remaps_through_source_api(
    storage: GoogleSheetsStorage,
) -> None:
    storage.ensure_defaults()
    payee = fixture_payee(storage, "Mixed-use vendor")
    source = fixture_mixed(storage,
        txn_date="2026-07-31",
        account_id=storage.list_accounts(active_only=False)[0]["id"],
        category_id=next(
            category
            for category in storage.list_categories()
            if category["kind"] == "Expense"
        )["id"],
        payee_id=payee["id"],
        description="Shared service",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    fixture_receipts(storage, storage._find_row("MixedUseExpenses", source['id']).values["linked_transaction_id"], references=[{'id': 'receipt123456', 'name': 'old-name.pdf'}])
    drive = Mock()
    drive.list_profile_receipts.return_value = [_backfilled_drive_receipt("north")]
    mixed_remap = Mock(wraps=storage.remap_mixed_use_receipt)
    generic_remap = Mock(wraps=storage.remap_transaction_receipt)
    storage.remap_mixed_use_receipt = mixed_remap  # type: ignore[method-assign]
    storage.remap_transaction_receipt = generic_remap  # type: ignore[method-assign]

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report["references_updated"] == 1
    mixed_remap.assert_called_once()
    assert mixed_remap.call_args.args == (source["id"],)
    assert mixed_remap.call_args.kwargs["old_file_id"] == "receipt123456"
    assert mixed_remap.call_args.kwargs["reference"]["id"] == "receipt123456"
    assert mixed_remap.call_args.kwargs["reference"]["receipt_id"] == "a" * 32
    generic_remap.assert_not_called()
    assert fixture_mixed_row(storage, source["id"])["receipt_references"]


def test_preparation_does_not_migrate_a_drive_only_transaction_association() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _delay: None)
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=fixture_category(storage, "Sales", "Income")["id"],
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

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report == {
        "examined": 1,
        "drive_backfilled": 1,
        "references_updated": 0,
        "errors": [],
    }
    current = storage.list_transactions(_force_refresh=True)[0]
    assert current["receipt_references"] == ""


def test_preparation_does_not_migrate_drive_only_mixed_use_association(
    storage: GoogleSheetsStorage,
) -> None:
    storage.ensure_defaults()
    payee = fixture_payee(storage, "Mixed-use vendor")
    source = fixture_mixed(storage,
        txn_date="2026-07-31",
        account_id=storage.list_accounts(active_only=False)[0]["id"],
        category_id=next(
            category
            for category in storage.list_categories()
            if category["kind"] == "Expense"
        )["id"],
        payee_id=payee["id"],
        description="Shared service",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    projection_id = source["linked_transaction_id"]
    _set_raw_receipt_references(
        storage._workbook,
        transaction_id=projection_id,
        value="",
    )
    _set_raw_receipt_references(
        storage._workbook,
        worksheet_title="MixedUseExpenses",
        transaction_id=source["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=projection_id)
    ]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt(
        "north",
        transaction_id=projection_id,
    )

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report == {
        "examined": 1,
        "drive_backfilled": 1,
        "references_updated": 0,
        "errors": [],
    }
    for worksheet_title, record_id in (
        ("Transactions", projection_id),
        ("MixedUseExpenses", source["id"]),
    ):
        worksheet = storage._workbook.worksheet(worksheet_title)
        headers = worksheet.rows[0]
        row = next(item for item in worksheet.rows[1:] if item[0] == record_id)
        assert row[headers.index("receipt_references")] == ""


def test_preparation_does_not_overwrite_concurrent_mixed_use_receipt_change(
    storage: GoogleSheetsStorage,
) -> None:
    storage.ensure_defaults()
    payee = fixture_payee(storage, "Mixed-use vendor")
    source = fixture_mixed(storage,
        txn_date="2026-07-31",
        account_id=storage.list_accounts(active_only=False)[0]["id"],
        category_id=next(
            category
            for category in storage.list_categories()
            if category["kind"] == "Expense"
        )["id"],
        payee_id=payee["id"],
        description="Shared service",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    projection_id = source["linked_transaction_id"]
    _set_raw_receipt_references(
        storage._workbook,
        transaction_id=projection_id,
        value="",
    )
    _set_raw_receipt_references(
        storage._workbook,
        worksheet_title="MixedUseExpenses",
        transaction_id=source["id"],
        value="",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=projection_id)
    ]

    def unlink_before_initialization(**_scope: str) -> dict[str, object]:
        fixture_receipts(storage, storage._find_row("MixedUseExpenses", source['id']).values["linked_transaction_id"], references=[])
        return _backfilled_drive_receipt(
            "north",
            transaction_id=projection_id,
        )

    drive.backfill_receipt_checksum.side_effect = unlink_before_initialization

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    assert report["references_updated"] == 0
    assert report["errors"] == []
    assert fixture_mixed_row(storage, source["id"])[
        "receipt_references"
    ] == "[]"
    assert next(
        transaction
        for transaction in storage.list_transactions(_force_refresh=True)
        if transaction["id"] == projection_id
    )["receipt_references"] == "[]"


def test_preparation_does_not_override_a_concurrent_explicit_unlink() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _delay: None)
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=fixture_category(storage, "Sales", "Income")["id"],
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
        fixture_receipts(storage, transaction['id'], references=[])
        return _backfilled_drive_receipt(
            "north",
            transaction_id=transaction["id"],
        )

    drive.backfill_receipt_checksum.side_effect = unlink_before_initialization

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert current["receipt_references"] == "[]"
    assert report["references_updated"] == 0
    assert report["errors"] == []


def test_preparation_respects_an_explicitly_empty_reference_list() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=fixture_category(storage, "Sales", "Income")["id"],
    )
    fixture_receipts(storage, transaction['id'], references=[])
    drive = Mock()
    drive.list_profile_receipts.return_value = [
        _legacy_drive_receipt("north", transaction_id=transaction["id"])
    ]
    drive.backfill_receipt_checksum.return_value = _backfilled_drive_receipt(
        "north",
        transaction_id=transaction["id"],
    )

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="folder123456",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert current["receipt_references"] == "[]"
    assert report["drive_backfilled"] == 1
    assert report["references_updated"] == 0


def test_preparation_does_not_touch_another_profile_storage() -> None:
    north_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    south_storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    south_account = fixture_account(south_storage, "Checking", "Bank")
    south_transaction = fixture_transaction(south_storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=south_account["id"],
        category_id=fixture_category(south_storage, "Sales", "Income")["id"],
    )
    fixture_receipts(south_storage,
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

    prepare_profile_receipts(
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


def test_preparation_does_not_download_receipts_with_valid_integrity_metadata() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    drive = Mock()
    drive.list_profile_receipts.return_value = [_backfilled_drive_receipt("north")]

    report = prepare_profile_receipts(
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


def test_preparation_does_not_restore_a_concurrently_unlinked_reference() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=fixture_category(storage, "Sales", "Income")["id"],
    )
    fixture_receipts(storage,
        transaction["id"],
        file_id="receipt123456",
        name="statement.pdf",
    )
    drive = Mock()
    drive.list_profile_receipts.return_value = [_legacy_drive_receipt("north")]

    def unlink_before_backfill(**_scope: str) -> dict[str, object]:
        fixture_receipts(storage, transaction['id'], references=[])
        return _backfilled_drive_receipt("north")

    drive.backfill_receipt_checksum.side_effect = unlink_before_backfill

    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key="north",
        folder_id="northfolder123",
    )

    current = storage.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"]) == []
    assert report["references_updated"] == 0
    assert len(report["errors"]) == 1


def test_preparation_reports_reference_failure_and_remains_resumable() -> None:
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

    report = prepare_profile_receipts(
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
    account = fixture_account(storage, "Checking", "Bank")
    transaction = fixture_transaction(storage,
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=fixture_category(storage, "Sales", "Income")["id"],
    )
    fixture_receipts(storage, transaction['id'], references=[{'id': 'receipt123456', 'name': 'old-name.pdf', 'receipt_id': 'a' * 32, 'sha256': hashlib.sha256(b'receipt').hexdigest(), 'original_filename': 'statement.pdf', 'mime_type': 'application/pdf', 'byte_size': 7}])
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
