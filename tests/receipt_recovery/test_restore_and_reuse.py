from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock


from tabula_rasa.receipt_recovery import (
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


def test_recovery_restores_remaps_and_preserves_unreferenced_receipts() -> None:
    referenced_content = b"referenced receipt"
    unreferenced_content = b"unreferenced receipt"
    referenced = make_reference(1, referenced_content)
    unreferenced = make_reference(2, unreferenced_content)
    backup, target, transaction_id = backup_with_receipts(
        [referenced],
        unreferenced=[unreferenced],
    )
    restored_referenced = make_drive_file(referenced, file_id="newreceipt01")
    restored_unreferenced = make_drive_file(unreferenced, file_id="newreceipt02")
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
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    restored_file = make_drive_file(reference, file_id="newreceipt01")
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
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    drive = Mock()
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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


def test_mixed_use_receipt_recovery_updates_source_and_projection() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    old_reference = make_reference(1, b"receipt")
    source = storage.create_mixed_use_expense(
        txn_date="2026-07-31",
        total_expense="100.00",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        description="Shared office",
        allocation_rationale="Measured use",
        receipt_references=[old_reference],
    )
    transaction_id = source["linked_transaction_id"]
    expected_transactions = storage.list_transactions(_force_refresh=True)
    new_reference = {**old_reference, "id": "newreceipt01"}

    applied, _ = storage.apply_receipt_recovery_plan(
        expected_transactions,
        {transaction_id: [new_reference]},
    )

    assert applied is True
    assert (
        decode_receipt_references(
            storage.list_transactions(_force_refresh=True)[0]["receipt_references"]
        )[0]["id"]
        == "newreceipt01"
    )
    assert (
        decode_receipt_references(
            storage.list_mixed_use_expenses()[0]["receipt_references"]
        )[0]["id"]
        == "newreceipt01"
    )


def test_mixed_use_receipt_mutation_apis_update_source_and_projection() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    source = storage.create_mixed_use_expense(
        txn_date="2026-07-31",
        total_expense="100.00",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        description="Shared office",
        allocation_rationale="Measured use",
    )
    first = make_reference(1, b"first receipt")
    second = make_reference(2, b"second receipt")

    storage.set_mixed_use_receipt_references(
        source["id"], [first], expected_source=source
    )
    refreshed_source = storage.get_mixed_use_expense(source["id"])
    storage.link_mixed_use_receipt(
        source["id"], reference=second, expected_source=refreshed_source
    )
    refreshed_source = storage.get_mixed_use_expense(source["id"])
    storage.remap_mixed_use_receipt(
        source["id"],
        old_file_id=str(first["id"]),
        reference=second,
        expected_source=refreshed_source,
    )
    refreshed_source = storage.get_mixed_use_expense(source["id"])
    storage.unlink_mixed_use_receipt(
        source["id"], file_id=str(second["id"]), expected_source=refreshed_source
    )

    assert (
        decode_receipt_references(
            storage.list_transactions(_force_refresh=True)[0]["receipt_references"]
        )
        == []
    )
    assert (
        decode_receipt_references(
            storage.list_mixed_use_expenses()[0]["receipt_references"]
        )
        == []
    )


def test_recovery_preserves_conflict_check_before_skipping_reused_file() -> None:
    content = b"receipt"
    reference = make_reference(1, content)
    backup, target, transaction_id = backup_with_receipts([reference])
    accounts = target.list_accounts(_force_refresh=True)
    categories = target.list_categories(_force_refresh=True)
    other_transaction = target.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=accounts[0]["id"],
        category_id=categories[0]["id"],
    )
    # Seed the deliberately invalid duplicate-reference state directly.  The
    # public setter now correctly rejects creating this conflict.
    transaction_sheet = target._workbook.worksheet("Transactions")
    headers = transaction_sheet.rows[0]
    receipt_column = headers.index("receipt_references")
    id_column = headers.index("id")
    other_row = next(
        row
        for row in transaction_sheet.rows[1:]
        if row[id_column] == other_transaction["id"]
    )
    other_row[receipt_column] = json.dumps([reference], separators=(",", ":"))
    target._invalidate("Transactions")
    drive = Mock()
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
    storage = Mock(wraps=target)
    storage.apply_receipt_recovery_plan.side_effect = StorageError(
        "Receipt recovery found duplicate live transaction IDs."
    )
    drive = Mock()
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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
    reference = make_reference(1, content)
    backup, target, _ = backup_with_receipts([reference])
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
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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
    reference = make_reference(1, content)
    backup, target, transaction_id = backup_with_receipts([reference])
    stale_reference = {**reference, "id": "stale-recovered-id"}
    target.remap_transaction_receipt(
        transaction_id,
        old_file_id=str(reference["id"]),
        reference=stale_reference,
    )
    drive = Mock()
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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
    reference = make_reference(1, content)
    backup, target, transaction_id = backup_with_receipts([reference])
    target.link_transaction_receipt(
        transaction_id,
        file_id=str(reference["id"]),
        name=str(reference["name"]),
    )
    drive = Mock()
    drive.restore_receipt.return_value = (make_drive_file(reference), True)

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
