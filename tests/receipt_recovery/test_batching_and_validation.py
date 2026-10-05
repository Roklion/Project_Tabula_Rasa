from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

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


from tests.receipt_recovery._support import (
    backup_with_receipts,
    make_drive_file,
    make_reference,
)


def test_recovery_removes_old_reference_when_confirmed_reference_is_also_present() -> (
    None
):
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, transaction_id = backup_with_receipts([reference])
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
        make_drive_file(reference, file_id="newreceipt01"),
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
    first = make_reference(1, b"first")
    second = make_reference(2, b"second")
    backup, target, _ = backup_with_receipts([first, second])
    worksheet = target._workbook.sheets["Transactions"]
    worksheet.batch_update = Mock(wraps=worksheet.batch_update)
    drive = Mock()
    drive.restore_receipt.side_effect = [
        (make_drive_file(first, file_id="newreceipt01"), False),
        (make_drive_file(second, file_id="newreceipt02"), False),
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
    worksheet.batch_update.assert_called_once()


def test_recovery_rejects_duplicate_ids_added_after_preflight() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]

    def restore_after_duplicate(**_kwargs: object) -> tuple[dict[str, object], bool]:
        worksheet.rows.append(list(worksheet.rows[1]))
        return make_drive_file(reference), True

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


def test_recovery_batching_remains_isolated_between_profiles() -> None:
    north_content = b"north receipt"
    south_content = b"south receipt"
    north_reference = make_reference(1, north_content)
    south_reference = make_reference(2, south_content)
    north_backup, north_target, _ = backup_with_receipts(
        [north_reference],
        profile_key="north",
    )
    south_backup, south_target, _ = backup_with_receipts(
        [south_reference],
        profile_key="south",
    )
    north_drive = Mock()
    north_drive.restore_receipt.return_value = (
        make_drive_file(
            north_reference,
            file_id="northreceipt01",
            profile_key="north",
        ),
        False,
    )
    south_drive = Mock()
    south_drive.restore_receipt.return_value = (
        make_drive_file(
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
        (north_root / str(north_reference["name"])).write_bytes(north_content)
        (south_root / str(south_reference["name"])).write_bytes(south_content)
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
    assert (
        decode_receipt_references(north_current["receipt_references"])[0]["id"]
        == "northreceipt01"
    )
    assert (
        decode_receipt_references(south_current["receipt_references"])[0]["id"]
        == "southreceipt01"
    )
    north_drive.restore_receipt.assert_called_once()
    south_drive.restore_receipt.assert_called_once()


def test_missing_and_corrupt_files_do_not_block_other_valid_receipts() -> None:
    contents = [b"missing", b"corrupt", b"valid"]
    references = [
        make_reference(index, content)
        for index, content in enumerate(contents, start=1)
    ]
    backup, target, _ = backup_with_receipts(references)
    drive = Mock()
    drive.restore_receipt.return_value = (
        make_drive_file(references[2], file_id="newreceipt03"),
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
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
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
        empty_target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
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
    first = make_reference(1, first_content)
    second = make_reference(2, second_content)
    backup, target, _ = backup_with_receipts([first, second])
    drive = Mock()
    drive.restore_receipt.side_effect = [
        GoogleDriveConflictError("conflict"),
        (make_drive_file(second, file_id="newreceipt02"), False),
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


def test_recovery_rejects_pre_manifest_v4_until_migrated() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    ledger_only = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(backup)) as source,
        zipfile.ZipFile(ledger_only, "w") as destination,
    ):
        ledger_manifest = json.loads(source.read("manifest.json"))
        ledger_manifest["format_version"] = 4
        ledger_manifest["sha256"].pop("receipts.json")
        ledger_manifest["sha256"].pop("MixedUseExpenses.csv", None)
        ledger_manifest["row_counts"].pop("MixedUseExpenses", None)
        ledger_manifest["worksheet_headers"].pop("MixedUseExpenses", None)
        transaction_rows = list(
            csv.reader(io.StringIO(source.read("Transactions.csv").decode("utf-8")))
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
            if name in {"receipts.json", "MixedUseExpenses.csv", "Tags.csv"}:
                continue
            destination.writestr(
                name,
                json.dumps(ledger_manifest).encode("utf-8")
                if name == "manifest.json"
                else (
                    transaction_bytes
                    if name == "Transactions.csv"
                    else (mileage_bytes if name == "Mileage.csv" else source.read(name))
                ),
            )
    drive = Mock()
    with (
        TemporaryDirectory() as directory,
        pytest.raises(
            StorageError,
            match="Only backup format 13",
        ),
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
                    "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                },
                "south": {
                    "spreadsheet_id": "south-live-sheet",
                    "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
                },
            }
        }
    )

    with pytest.raises(ValueError, match="configured live workbook"):
        validate_recovery_target(profiles, "north-live-sheet")
    with pytest.raises(ValueError, match="configured live workbook"):
        validate_recovery_target(profiles, "south-live-sheet")

    assert (
        validate_recovery_target(profiles, "restored-sheet-456") == "restored-sheet-456"
    )
