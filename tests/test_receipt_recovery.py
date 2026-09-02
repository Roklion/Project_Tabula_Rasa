from __future__ import annotations

import csv
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
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
    decode_receipt_references,
)
from tests.fakes import FakeWorkbook


def _reference(index: int, content: bytes) -> dict[str, object]:
    return {
        "id": f"oldreceipt{index:02d}",
        "name": f"statement ({index}).pdf",
        "receipt_id": hashlib.sha256(
            f"receipt-{index}".encode("utf-8")
        ).hexdigest()[:32],
        "original_filename": f"original-{index}.pdf",
        "mime_type": "application/pdf",
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _drive_file(
    reference: dict[str, object],
    *,
    file_id: str | None = None,
    profile_key: str = "north",
) -> dict[str, object]:
    return {
        "id": file_id or reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
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
    profile_key: str = "north",
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
        profile_key,
        source.list_transactions(_force_refresh=True),
        [
            _drive_file(reference, profile_key=profile_key)
            for reference in all_references
        ],
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


def test_recovery_rejects_duplicate_ids_in_refreshed_transactions() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    storage = Mock(wraps=target)
    storage.apply_receipt_recovery_plan.side_effect = StorageError(
        "Receipt recovery found duplicate live transaction IDs."
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

    assert report["reused"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert report["issues"][0]["status"] == "errors"


def test_recovery_handles_null_receipt_reference_cells_without_crashing() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    initial_transactions = target.list_transactions(_force_refresh=True)
    null_transactions = [
        {**initial_transactions[0], "receipt_references": None},
        {"id": "other-transaction", "receipt_references": None},
    ]
    storage = Mock(wraps=target)
    storage.list_transactions.return_value = initial_transactions
    storage.apply_receipt_recovery_plan.side_effect = [
        (False, null_transactions),
        (True, null_transactions),
    ]
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

    assert report["errors"] == 1
    assert report["references_remapped"] == 0
    assert storage.apply_receipt_recovery_plan.call_count == 2


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


def test_recovery_retries_when_manual_edit_invalidates_cached_noop() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, transaction_id = _backup_with_receipts([reference])
    stale_reference = {**reference, "id": "stale-recovered-id"}
    worksheet = target._workbook.sheets["Transactions"]
    reference_index = worksheet.rows[0].index("receipt_references")

    def restore_after_manual_edit(**_kwargs: object) -> tuple[dict[str, object], bool]:
        worksheet.rows[1][reference_index] = json.dumps([stale_reference])
        return _drive_file(reference), True

    original_apply = target.apply_receipt_recovery_plan
    target.apply_receipt_recovery_plan = Mock(wraps=original_apply)
    drive = Mock()
    drive.restore_receipt.side_effect = restore_after_manual_edit

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
    assert target.apply_receipt_recovery_plan.call_count == 2
    current = target.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"])[0][
        "id"
    ] == str(reference["id"])


def test_recovery_stops_after_three_unstable_reconciliation_attempts() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    initial_transactions = target.list_transactions(_force_refresh=True)
    storage = Mock(wraps=target)
    storage.list_transactions.return_value = initial_transactions
    storage.apply_receipt_recovery_plan.side_effect = [
        (False, initial_transactions),
        (False, initial_transactions),
        (False, initial_transactions),
    ]
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
    )

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

    assert report["restored"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert storage.apply_receipt_recovery_plan.call_count == 3


def test_recovery_rechecks_cross_transaction_conflicts_after_manual_edit() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    accounts = target.list_accounts(_force_refresh=True)
    categories = target.list_categories(_force_refresh=True)
    other_transaction = target.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=accounts[0]["id"],
        category_id=categories[0]["id"],
    )
    worksheet = target._workbook.sheets["Transactions"]
    id_index = worksheet.rows[0].index("id")
    reference_index = worksheet.rows[0].index("receipt_references")

    def restore_after_manual_edit(**_kwargs: object) -> tuple[dict[str, object], bool]:
        other_row = next(
            row for row in worksheet.rows[1:] if row[id_index] == other_transaction["id"]
        )
        other_row[reference_index] = json.dumps([reference])
        return _drive_file(reference), True

    original_apply = target.apply_receipt_recovery_plan
    target.apply_receipt_recovery_plan = Mock(wraps=original_apply)
    worksheet.batch_update = Mock(wraps=worksheet.batch_update)
    drive = Mock()
    drive.restore_receipt.side_effect = restore_after_manual_edit

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
    assert target.apply_receipt_recovery_plan.call_count == 2
    worksheet.batch_update.assert_not_called()


def test_recovery_rejects_duplicate_ids_added_after_preflight() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]

    def restore_after_duplicate(**_kwargs: object) -> tuple[dict[str, object], bool]:
        worksheet.rows.append(list(worksheet.rows[1]))
        return _drive_file(reference), True

    worksheet.batch_update = Mock(wraps=worksheet.batch_update)
    drive = Mock()
    drive.restore_receipt.side_effect = restore_after_duplicate

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
    worksheet.batch_update.assert_not_called()


def test_recovery_preserves_unrelated_manual_edits_before_batch_write() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    description_index = worksheet.rows[0].index("description")

    def restore_after_manual_edit(**_kwargs: object) -> tuple[dict[str, object], bool]:
        worksheet.rows[1][description_index] = "Manually corrected description"
        return _drive_file(reference, file_id="newreceipt01"), False

    drive = Mock()
    drive.restore_receipt.side_effect = restore_after_manual_edit

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

    assert report["restored"] == 1
    assert report["references_remapped"] == 1
    current = target.list_transactions(_force_refresh=True)[0]
    assert current["description"] == "Manually corrected description"


def test_recovery_reports_unconfirmed_batch_write_failure() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    worksheet.batch_update = Mock(side_effect=OSError("temporary failure"))
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
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

    assert report["restored"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert worksheet.batch_update.call_count == 3
    current = target.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"])[0][
        "id"
    ] == str(reference["id"])


def test_recovery_confirms_batch_write_after_lost_response() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    original_batch_update = worksheet.batch_update

    def commit_then_timeout(
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        original_batch_update(data, **kwargs)
        raise OSError("response lost after commit")

    worksheet.batch_update = Mock(side_effect=commit_then_timeout)
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
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

    assert report["restored"] == 1
    assert report["references_remapped"] == 1
    assert report["errors"] == 0
    assert worksheet.batch_update.call_count == 1


def test_recovery_preserves_manual_edit_after_lost_batch_response() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    manual_reference = _reference(99, b"manual")
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    original_batch_update = worksheet.batch_update
    reference_index = worksheet.rows[0].index("receipt_references")

    def commit_then_edit_then_timeout(
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        original_batch_update(data, **kwargs)
        worksheet.rows[1][reference_index] = json.dumps([manual_reference])
        raise OSError("response lost after commit and manual edit")

    worksheet.batch_update = Mock(side_effect=commit_then_edit_then_timeout)
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
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

    assert report["restored"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert worksheet.batch_update.call_count == 1
    current = target.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(current["receipt_references"]) == [
        manual_reference
    ]


def test_recovery_does_not_confirm_lost_write_after_transaction_delete() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    original_batch_update = worksheet.batch_update

    def commit_then_delete_then_timeout(
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        original_batch_update(data, **kwargs)
        worksheet.rows.pop(1)
        raise OSError("response lost after transaction deletion")

    worksheet.batch_update = Mock(side_effect=commit_then_delete_then_timeout)
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
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

    assert report["restored"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert worksheet.batch_update.call_count == 1


def test_recovery_rejects_duplicate_id_during_lost_write_readback() -> None:
    content = b"receipt"
    reference = _reference(1, content)
    backup, target, _ = _backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    reference_index = worksheet.rows[0].index("receipt_references")
    duplicate_reference = {**reference, "id": "newreceipt01"}

    def append_duplicate_then_timeout(
        _data: list[dict[str, object]],
        **_kwargs: object,
    ) -> None:
        duplicate_row = list(worksheet.rows[1])
        duplicate_row[reference_index] = json.dumps([duplicate_reference])
        worksheet.rows.append(duplicate_row)
        raise OSError("response lost before batch commit")

    worksheet.batch_update = Mock(side_effect=append_duplicate_then_timeout)
    drive = Mock()
    drive.restore_receipt.return_value = (
        _drive_file(reference, file_id="newreceipt01"),
        False,
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

    assert report["restored"] == 0
    assert report["references_remapped"] == 0
    assert report["errors"] == 1
    assert worksheet.batch_update.call_count == 1


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


def test_recovery_batches_multiple_receipts_into_one_reconciliation() -> None:
    first = _reference(1, b"first")
    second = _reference(2, b"second")
    backup, target, _ = _backup_with_receipts([first, second])
    original_apply = target.apply_receipt_recovery_plan
    target.apply_receipt_recovery_plan = Mock(
        wraps=original_apply
    )
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
    target.apply_receipt_recovery_plan.assert_called_once()


def test_recovery_uses_two_reads_and_one_write_for_realistic_receipt_count() -> None:
    receipt_count = 100
    contents = [f"receipt-{index}".encode() for index in range(1, receipt_count + 1)]
    references = [
        _reference(index, content)
        for index, content in enumerate(contents, start=1)
    ]
    backup, target, _ = _backup_with_receipts(references)
    worksheet = target._workbook.sheets["Transactions"]
    original_read = worksheet.get_all_values
    original_batch_update = worksheet.batch_update
    worksheet.get_all_values = Mock(wraps=original_read)
    worksheet.batch_update = Mock(wraps=original_batch_update)
    references_by_name = {
        str(reference["name"]): (index, reference)
        for index, reference in enumerate(references, start=1)
    }

    def restore_receipt(**kwargs: object) -> tuple[dict[str, object], bool]:
        index, reference = references_by_name[str(kwargs["stored_filename"])]
        return _drive_file(
            reference,
            file_id=f"newreceipt{index:03d}",
        ), False

    drive = Mock()
    drive.restore_receipt.side_effect = restore_receipt

    with TemporaryDirectory() as directory:
        root = Path(directory)
        for reference, content in zip(references, contents):
            (root / str(reference["name"])).write_bytes(content)

        report = recover_receipts_from_synology(
            backup,
            root,
            profile_key="north",
            folder_id="folder123456",
            storage=target,
            drive=drive,
        )

    assert not report["issues"], report["issues"]
    assert report["restored"] == receipt_count
    assert report["references_remapped"] == receipt_count
    assert report["errors"] == 0
    assert worksheet.get_all_values.call_count == 2
    worksheet.batch_update.assert_called_once()


def test_recovery_batching_remains_isolated_between_profiles() -> None:
    north_content = b"north receipt"
    south_content = b"south receipt"
    north_reference = _reference(1, north_content)
    south_reference = _reference(2, south_content)
    north_backup, north_target, _ = _backup_with_receipts(
        [north_reference],
        profile_key="north",
    )
    south_backup, south_target, _ = _backup_with_receipts(
        [south_reference],
        profile_key="south",
    )
    north_drive = Mock()
    north_drive.restore_receipt.return_value = (
        _drive_file(
            north_reference,
            file_id="northreceipt01",
            profile_key="north",
        ),
        False,
    )
    south_drive = Mock()
    south_drive.restore_receipt.return_value = (
        _drive_file(
            south_reference,
            file_id="southreceipt01",
            profile_key="south",
        ),
        False,
    )

    with TemporaryDirectory() as directory:
        root = Path(directory)
        north_root = root / "north"
        south_root = root / "south"
        north_root.mkdir()
        south_root.mkdir()
        (north_root / str(north_reference["name"])).write_bytes(
            north_content
        )
        (south_root / str(south_reference["name"])).write_bytes(
            south_content
        )
        untouched_south = south_target.list_transactions(_force_refresh=True)

        north_report = recover_receipts_from_synology(
            north_backup,
            north_root,
            profile_key="north",
            folder_id="northfolder123",
            storage=north_target,
            drive=north_drive,
        )

        assert south_target.list_transactions(_force_refresh=True) == untouched_south
        untouched_north = north_target.list_transactions(_force_refresh=True)

        south_report = recover_receipts_from_synology(
            south_backup,
            south_root,
            profile_key="south",
            folder_id="southfolder123",
            storage=south_target,
            drive=south_drive,
        )

    assert north_report["references_remapped"] == 1
    assert south_report["references_remapped"] == 1
    assert north_target.list_transactions(_force_refresh=True) == untouched_north
    north_current = north_target.list_transactions(_force_refresh=True)[0]
    south_current = south_target.list_transactions(_force_refresh=True)[0]
    assert decode_receipt_references(north_current["receipt_references"])[0][
        "id"
    ] == "northreceipt01"
    assert decode_receipt_references(south_current["receipt_references"])[0][
        "id"
    ] == "southreceipt01"
    north_drive.restore_receipt.assert_called_once()
    south_drive.restore_receipt.assert_called_once()


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
        transaction_rows = list(
            csv.reader(
                io.StringIO(source.read("Transactions.csv").decode("utf-8"))
            )
        )
        payee_id_index = transaction_rows[0].index("payee_id")
        transaction_rows[0][payee_id_index] = "payee"
        tag_ids_index = transaction_rows[0].index("tag_ids")
        transaction_rows = [
            [value for index, value in enumerate(row) if index != tag_ids_index]
            for row in transaction_rows
        ]
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(transaction_rows)
        transaction_bytes = csv_buffer.getvalue().encode("utf-8")
        mileage_rows = list(
            csv.reader(io.StringIO(source.read("Mileage.csv").decode("utf-8")))
        )
        mileage_tag_ids_index = mileage_rows[0].index("tag_ids")
        mileage_rows = [
            [value for index, value in enumerate(row) if index != mileage_tag_ids_index]
            for row in mileage_rows
        ]
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(mileage_rows)
        mileage_bytes = csv_buffer.getvalue().encode("utf-8")
        ledger_manifest["worksheet_headers"]["Transactions"] = transaction_rows[0]
        ledger_manifest["worksheet_headers"]["Mileage"] = mileage_rows[0]
        ledger_manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
            transaction_bytes
        ).hexdigest()
        ledger_manifest["sha256"]["Mileage.csv"] = hashlib.sha256(
            mileage_bytes
        ).hexdigest()
        ledger_manifest["worksheet_headers"].pop("Tags")
        ledger_manifest["row_counts"].pop("Tags")
        ledger_manifest["sha256"].pop("Tags.csv")
        for name in source.namelist():
            if name in {"receipts.json", "Tags.csv"}:
                continue
            destination.writestr(
                name,
                json.dumps(ledger_manifest).encode("utf-8")
                if name == "manifest.json"
                    else (
                        transaction_bytes
                        if name == "Transactions.csv"
                        else (
                            mileage_bytes
                            if name == "Mileage.csv"
                            else source.read(name)
                        )
                    ),
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
