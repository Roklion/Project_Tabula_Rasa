from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import zipfile

import pytest

from scripts.recover_synology_receipts import validate_recovery_target
from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.google_drive import GoogleDriveConflictError
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.receipt_recovery import (
    ReceiptRecoveryError,
    recover_receipts_from_synology,
)
from tabula_rasa.storage import GoogleSheetsStorage, decode_receipt_references
from tests.fakes import FakeWorkbook


def _reference(index: int, content: bytes) -> dict[str, object]:
    return {
        "id": f"oldreceipt{index:02d}",
        "name": f"statement ({index}).pdf",
        "receipt_id": f"{index:x}" * 32,
        "original_filename": f"original-{index}.pdf",
        "mime_type": "application/pdf",
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _drive_file(
    reference: dict[str, object],
    *,
    file_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": file_id or reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": reference["receipt_id"],
            "tabulaRasaSha256": reference["sha256"],
            "tabulaRasaOriginalName": reference["original_filename"],
            "tabulaRasaOriginalFileId": reference["id"],
        },
    }


def _backup_with_receipts(
    references: list[dict[str, object]],
    *,
    unreferenced: list[dict[str, object]] | None = None,
) -> tuple[bytes, GoogleSheetsStorage, str]:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = source.create_account("Checking", "Bank")
    category = source.create_category("Sales", "Income")
    transaction = source.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    for reference in references:
        source.link_transaction_receipt(
            transaction["id"],
            reference=reference,
        )
    all_references = [*references, *(unreferenced or [])]
    manifest = build_receipt_manifest(
        "north",
        source.list_transactions(_force_refresh=True),
        [_drive_file(reference) for reference in all_references],
    )
    backup = source.export_backup_zip(manifest)
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    target.restore_backup_zip(backup)
    return backup, target, transaction["id"]


def test_recovery_restores_remaps_and_preserves_unreferenced_receipts() -> None:
    referenced_content = b"referenced receipt"
    unreferenced_content = b"unreferenced receipt"
    referenced = _reference(1, referenced_content)
    unreferenced = _reference(2, unreferenced_content)
    backup, target, transaction_id = _backup_with_receipts(
        [referenced],
        unreferenced=[unreferenced],
    )
    restored_referenced = _drive_file(referenced, file_id="newreceipt01")
    restored_unreferenced = _drive_file(unreferenced, file_id="newreceipt02")
    drive = Mock()
    drive.restore_receipt.side_effect = [
        (restored_referenced, False),
        (restored_unreferenced, False),
    ]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(referenced["name"])).write_bytes(referenced_content)
        (root / str(unreferenced["name"])).write_bytes(unreferenced_content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report == {
        "total": 2,
        "restored": 2,
        "reused": 0,
        "references_remapped": 1,
        "unreferenced_preserved": 1,
        "missing": 0,
        "corrupt": 0,
        "conflicts": 0,
        "errors": 0,
        "skipped": 0,
        "issues": [],
    }
    transaction = next(
        item
        for item in target.list_transactions(_force_refresh=True)
        if item["id"] == transaction_id
    )
    references = decode_receipt_references(transaction["receipt_references"])
    assert [reference["id"] for reference in references] == ["newreceipt01"]
    assert all(reference["id"] != "newreceipt02" for reference in references)


def test_recovery_retry_reuses_file_and_repairs_reference_idempotently() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    restored_file = _drive_file(reference, file_id="newreceipt01")
    drive = Mock()
    drive.restore_receipt.side_effect = [
        (restored_file, False),
        (restored_file, True),
    ]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        first = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )
        second = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert first["restored"] == 1
    assert second["reused"] == 1
    assert second["references_remapped"] == 0
    references = decode_receipt_references(
        target.list_transactions(_force_refresh=True)[0]["receipt_references"]
    )
    assert [item["id"] for item in references] == ["newreceipt01"]


def test_recovery_reuses_original_drive_file_without_remapping() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    drive = Mock()
    drive.restore_receipt.return_value = (_drive_file(reference), True)
    target.remap_transaction_receipt = Mock()

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["reused"] == 1
    assert report["references_remapped"] == 0
    assert report["errors"] == 0
    assert report["skipped"] == 0
    target.remap_transaction_receipt.assert_not_called()


def test_recovery_preserves_conflict_check_before_skipping_reused_file() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    accounts = target.list_accounts(_force_refresh=True)
    categories = target.list_categories(_force_refresh=True)
    other_transaction = target.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=accounts[0]["id"],
        category_id=categories[0]["id"],
    )
    target.set_transaction_receipt_references(
        other_transaction["id"],
        [reference],
    )
    drive = Mock()
    drive.restore_receipt.return_value = (_drive_file(reference), True)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["reused"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert report["issues"][0]["status"] == "errors"
    assert transaction_id != other_transaction["id"]


def test_recovery_repairs_stale_live_reference_when_original_file_is_reused() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    stale_reference = {**reference, "id": "stale-recovered-id"}
    target.remap_transaction_receipt(
        transaction_id,
        old_file_id=str(reference["id"]),
        reference=stale_reference,
    )
    drive = Mock()
    drive.restore_receipt.return_value = (_drive_file(reference), True)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["reused"] == 1
    assert report["references_remapped"] == 1
    assert report["errors"] == 0
    current = target.list_transactions(_force_refresh=True)[0]
    references = decode_receipt_references(current["receipt_references"])
    assert [item["id"] for item in references] == [str(reference["id"])]


def test_recovery_remaps_legacy_reference_when_original_file_is_reused() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    target.link_transaction_receipt(
        transaction_id,
        file_id=str(reference["id"]),
        name=str(reference["name"]),
    )
    drive = Mock()
    drive.restore_receipt.return_value = (_drive_file(reference), True)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["reused"] == 1
    assert report["references_remapped"] == 1
    assert report["errors"] == 0


def test_recovery_refreshes_transaction_before_skipping_reused_file() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    initial_transactions = target.list_transactions(_force_refresh=True)
    stale_reference = {**reference, "id": "stale-recovered-id"}
    stale_transaction = {
        **initial_transactions[0],
        "receipt_references": json.dumps([stale_reference]),
    }
    storage = Mock(wraps=target)
    storage.list_transactions.side_effect = [
        initial_transactions,
        [stale_transaction],
    ]
    storage.remap_transaction_receipt.side_effect = (
        target.remap_transaction_receipt
    )
    drive = Mock()
    drive.restore_receipt.return_value = (_drive_file(reference), True)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=storage,
            drive=drive,
        )

    assert report["reused"] == 1
    assert report["references_remapped"] == 1
    storage.remap_transaction_receipt.assert_called_once()


def test_recovery_removes_old_reference_when_confirmed_reference_is_also_present() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    target.remap_transaction_receipt(
        transaction_id,
        old_file_id=str(reference["id"]),
        reference={**reference, "id": "newreceipt01"},
    )
    target.link_transaction_receipt(
        transaction_id,
        file_id=str(reference["id"]),
        name=str(reference["name"]),
    )
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        True,
    )

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["reused"] == 1
    assert report["references_remapped"] == 1
    current = target.list_transactions(_force_refresh=True)[0]
    references = decode_receipt_references(current["receipt_references"])
    assert [item["id"] for item in references] == ["newreceipt01"]


def test_recovery_keeps_cache_when_remap_returns_no_transaction() -> None:
    first = _reference(1, b"first")
    second = _reference(2, b"second")
    backup, target, _ = _backup_with_receipts([first, second])
    target.remap_transaction_receipt = Mock(return_value=None)
    drive = Mock()
    drive.restore_receipt.side_effect = [
        (_drive_file(first, file_id="newreceipt01"), False),
        (_drive_file(second, file_id="newreceipt02"), False),
    ]

    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(first["name"])).write_bytes(b"first")
        (root / str(second["name"])).write_bytes(b"second")

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["restored"] == 2
    assert report["references_remapped"] == 2
    assert report["errors"] == 0
    assert target.remap_transaction_receipt.call_count == 2


def test_missing_and_corrupt_files_do_not_block_other_valid_receipts() -> None:
    contents = [b"missing", b"corrupt", b"valid"]
    references = [
        _reference(index, content)
        for index, content in enumerate(contents, start=1)
    ]
    backup, target, _ = _backup_with_receipts(references)
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(references[2], file_id="newreceipt03"),
        False,
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(references[1]["name"])).write_bytes(b"xxxxxxx")
        (root / str(references[2]["name"])).write_bytes(contents[2])

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["missing"] == 1
    assert report["corrupt"] == 1
    assert report["restored"] == 1
    assert report["references_remapped"] == 1
    assert report["skipped"] == 2
    drive.restore_receipt.assert_called_once()


def test_profile_and_transaction_preflight_happen_before_drive_changes() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    drive = Mock()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(reference["name"])).write_bytes(content)
        with pytest.raises(ReceiptRecoveryError, match="different business profile"):
            recover_receipts_from_synology(
                backup,
                root,
                profile_key="south",
                folder_id="southfolder123",
                storage=target,
                drive=drive,
            )
        empty_target = GoogleSheetsStorage(
            FakeWorkbook(), sleeper=lambda _delay: None
        )
        with pytest.raises(ReceiptRecoveryError, match="transaction"):
            recover_receipts_from_synology(
                backup,
                root,
                profile_key="north",
                folder_id="northfolder123",
                storage=empty_target,
                drive=drive,
            )

    drive.restore_receipt.assert_not_called()


def test_recovery_reports_drive_conflict_and_continues() -> None:
    first_content = b"first"
    second_content = b"second"
    first = _reference(1, first_content)
    second = _reference(2, second_content)
    backup, target, _ = _backup_with_receipts([first, second])
    drive = Mock()
    drive.restore_receipt.side_effect = [
        GoogleDriveConflictError("conflict"),
        (_drive_file(second, file_id="newreceipt02"), False),
    ]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / str(first["name"])).write_bytes(first_content)
        (root / str(second["name"])).write_bytes(second_content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert report["conflicts"] == 1
    assert report["restored"] == 1
    assert report["references_remapped"] == 1
    assert report["skipped"] == 1


def test_recovery_identifies_pre_manifest_v4_as_ledger_only() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    ledger_only = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
        ledger_only, "w"
    ) as destination:
        ledger_manifest = json.loads(source.read("manifest.json"))
        ledger_manifest["format_version"] = 4
        ledger_manifest["sha256"].pop("receipts.json")
        for name in source.namelist():
            if name == "receipts.json":
                continue
            destination.writestr(
                name,
                json.dumps(ledger_manifest).encode("utf-8")
                if name == "manifest.json"
                else source.read(name),
            )
    drive = Mock()
    with TemporaryDirectory() as directory, pytest.raises(
        ReceiptRecoveryError,
        match="ledger-only",
    ):
        recover_receipts_from_synology(
            ledger_only.getvalue(),
            Path(directory),
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    drive.restore_receipt.assert_not_called()


def test_recovery_command_refuses_every_profiles_live_workbook() -> None:
    profiles = load_business_profiles(
        {
            "business_profiles": {
                "north": {
                    "spreadsheet_id": "north-live-sheet",
                    "gcp_service_account": {},
                },
                "south": {
                    "spreadsheet_id": "south-live-sheet",
                    "gcp_service_account": {},
                },
            }
        }
    )

    with pytest.raises(ValueError, match="configured live workbook"):
        validate_recovery_target(profiles, "north-live-sheet")
    with pytest.raises(ValueError, match="configured live workbook"):
        validate_recovery_target(profiles, "south-live-sheet")

    assert (
        validate_recovery_target(profiles, "restored-sheet-456")
        == "restored-sheet-456"
    )
