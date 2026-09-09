from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock


from tabula_rasa.receipt_recovery import (
    recover_receipts_from_synology,
)
from tabula_rasa.storage import (
    decode_receipt_references,
)


from tests.receipt_recovery._support import (
    backup_with_receipts,
    make_drive_file,
    make_reference,
)


def test_recovery_stops_when_state_never_converges() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
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
        make_drive_file(reference, file_id="newreceipt01"),
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
    assert 0 < storage.apply_receipt_recovery_plan.call_count <= 3


def test_recovery_rechecks_cross_transaction_conflicts_after_manual_edit() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
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
            row
            for row in worksheet.rows[1:]
            if row[id_index] == other_transaction["id"]
        )
        other_row[reference_index] = json.dumps([reference])
        return make_drive_file(reference), True

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
    worksheet.batch_update.assert_not_called()


def test_recovery_preserves_unrelated_manual_edits_before_batch_write() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    worksheet = target._workbook.sheets["Transactions"]
    description_index = worksheet.rows[0].index("description")

    def restore_after_manual_edit(**_kwargs: object) -> tuple[dict[str, object], bool]:
        worksheet.rows[1][description_index] = "Manually corrected description"
        return make_drive_file(reference, file_id="newreceipt01"), False

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


def test_recovery_confirms_batch_write_after_lost_response() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
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
        make_drive_file(reference, file_id="newreceipt01"),
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
    reference = make_reference(1, content)
    manual_reference = make_reference(99, b"manual")
    backup, target, _ = backup_with_receipts([reference])
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
        make_drive_file(reference, file_id="newreceipt01"),
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
