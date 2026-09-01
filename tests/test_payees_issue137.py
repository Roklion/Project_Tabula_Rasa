from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
import zipfile
from collections.abc import Callable
from unittest.mock import Mock

import pytest

from scripts.migrate_payees import migrate_payee_rows, migrate_workbook
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageValidationError,
)
from tests.fakes import FakeWorkbook


def _legacy_backup(storage: GoogleSheetsStorage, payee_name: str) -> bytes:
    transactions = storage.list_transactions(_force_refresh=True)
    backup = storage.export_backup_zip(
        build_receipt_manifest("test", transactions, [])
    )
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(contents["manifest.json"])
    transaction_rows = list(
        csv.reader(io.StringIO(contents["Transactions.csv"].decode("utf-8")))
    )
    headers = transaction_rows[0]
    payee_id_index = headers.index("payee_id")
    headers[payee_id_index] = "payee"
    for row in transaction_rows[1:]:
        row[payee_id_index] = payee_name
    csv_buffer = io.StringIO(newline="")
    csv.writer(csv_buffer, lineterminator="\n").writerows(transaction_rows)
    contents["Transactions.csv"] = csv_buffer.getvalue().encode("utf-8")
    manifest["format_version"] = 6
    manifest["worksheet_headers"]["Transactions"] = headers
    manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
        contents["Transactions.csv"]
    ).hexdigest()
    manifest["worksheet_headers"].pop("Payees")
    manifest["row_counts"].pop("Payees")
    manifest["sha256"].pop("Payees.csv")
    contents.pop("Payees.csv")
    contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in contents.items():
            destination.writestr(name, content)
    return output.getvalue()


def test_payees_are_normalized_and_transactions_store_references() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    first = storage.create_payee("  Acme   Supplies ")
    second = storage.create_payee("acme supplies")

    assert second["id"] == first["id"]
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=first["id"],
    )

    assert transaction["payee_id"] == first["id"]
    assert storage.list_transactions()[0]["payee"] == "Acme   Supplies"


def test_edit_normalizes_unchanged_padded_inactive_payee_reference() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Vendor")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
    )
    storage.edit_payee(payee["id"], active=False)
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[1][payee_index] = f"  {payee['id']}  "

    updated = storage.edit_transaction(transaction["id"], description="Updated")

    assert updated["payee_id"] == payee["id"]
    assert updated["description"] == "Updated"


def test_edit_normalizes_unchanged_padded_inactive_account_reference() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    storage.edit_account(account["id"], active=False)
    transaction_sheet = workbook.worksheet("Transactions")
    account_index = transaction_sheet.rows[0].index("account_id")
    transaction_sheet.rows[1][account_index] = f"  {account['id']}  "

    updated = storage.edit_transaction(transaction["id"], description="Updated")

    assert updated["account_id"] == account["id"]
    assert updated["description"] == "Updated"


def test_edit_normalizes_unchanged_padded_inactive_transfer_destination() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    source = storage.create_account("Checking", "Bank")
    destination = storage.create_account("Savings", "Bank")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Transfer",
        amount=10,
        account_id=source["id"],
        to_account_id=destination["id"],
    )
    storage.edit_account(destination["id"], active=False)
    transaction_sheet = workbook.worksheet("Transactions")
    destination_index = transaction_sheet.rows[0].index("to_account_id")
    transaction_sheet.rows[1][destination_index] = f"  {destination['id']}  "

    updated = storage.edit_transaction(transaction["id"], description="Updated")

    assert updated["to_account_id"] == destination["id"]
    assert updated["description"] == "Updated"


def test_edit_preserves_unchanged_inactive_transaction_references() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Vendor")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
    )
    storage.edit_account(account["id"], active=False)
    storage.edit_payee(payee["id"], active=False)

    updated = storage.edit_transaction(transaction["id"], description="Updated")

    assert updated["account_id"] == account["id"]
    assert updated["payee_id"] == payee["id"]
    assert updated["description"] == "Updated"


def test_ensuring_payees_batches_reactivation_writes() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    first = storage.create_payee("First vendor")
    second = storage.create_payee("Second vendor")
    storage.edit_payee(first["id"], active=False)
    storage.edit_payee(second["id"], active=False)
    payee_sheet = workbook.worksheet("Payees")
    original_batch_update = payee_sheet.batch_update
    payee_sheet.batch_update = Mock(wraps=original_batch_update)  # type: ignore[method-assign]

    storage._ensure_payee_names(["First vendor", "Second vendor"])

    assert payee_sheet.batch_update.call_count == 1
    assert {item["id"] for item in storage.list_payees()} == {
        first["id"],
        second["id"],
    }


def test_ensuring_payees_reactivates_ids_with_storage_whitespace() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    payee = storage.create_payee("Vendor")
    storage.edit_payee(payee["id"], active=False)
    payee_row = workbook.worksheet("Payees").rows[1]
    payee_row[0] = f"  {payee['id']}  "

    ensured = storage._ensure_payee_names(["Vendor"])

    assert ensured[payee["id"]]["active"] == "TRUE"
    assert storage.list_payees()[0]["active"] == "TRUE"


def test_list_transactions_rejects_unknown_payee_references() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    transaction_sheet = workbook.worksheet("Transactions")
    payee_id_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[1][payee_id_index] = "missing-payee"

    with pytest.raises(StorageValidationError, match="Payee does not exist"):
        storage.list_transactions(_force_refresh=True)


def test_migration_deduplicates_legacy_payee_text() -> None:
    payees, transactions = migrate_payee_rows(
        [
            {"id": "one", "payee": "Acme Supplies"},
            {"id": "two", "payee": " acme   supplies "},
            {"id": "three", "payee": ""},
        ]
    )

    assert [item["name"] for item in payees] == ["Acme Supplies"]
    assert transactions[0]["payee_id"] == transactions[1]["payee_id"]
    assert transactions[2]["payee_id"] == ""


def test_migration_preserves_falsy_non_payee_values() -> None:
    _, transactions = migrate_payee_rows(
        [{"id": "one", "payee": "", "amount": 0, "reference": False}]
    )

    assert transactions == [
        {"id": "one", "payee_id": "", "amount": "0", "reference": "False"}
    ]


def test_migration_uses_supported_raw_append_option() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "Legacy vendor",
            "",
            "",
            "",
            "now",
        ]
    )
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.append_rows = Mock(wraps=payee_sheet.append_rows)

    migrate_workbook(workbook)

    assert payee_sheet.append_rows.call_args.kwargs == {
        "value_input_option": "RAW"
    }


def test_migration_accepts_short_existing_payee_rows() -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows.append(["existing-id", "Existing vendor"])
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "Existing vendor",
            "",
            "",
            "",
            "now",
        ]
    )

    result = migrate_workbook(workbook)

    assert result == {"payees": 0, "transactions": 1}
    assert transaction_sheet.rows[1][payee_index] == "existing-id"
    assert payee_sheet.rows[1] == ["existing-id", "Existing vendor", "TRUE", ""]
    assert GoogleSheetsStorage(workbook).list_payees()[0]["active"] == "TRUE"


def test_migration_rejects_existing_payee_without_id_before_transaction_write() -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows.append(["", "Broken vendor", "TRUE", ""])
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "Broken vendor",
            "",
            "",
            "",
            "now",
        ]
    )
    original_transactions = [list(row) for row in transaction_sheet.rows]

    with pytest.raises(StorageValidationError, match="Payee ID is required"):
        migrate_workbook(workbook)

    assert transaction_sheet.rows == original_transactions


def test_migration_rejects_payees_worksheet_missing_required_headers() -> None:
    workbook = FakeWorkbook()
    workbook.worksheet("Payees").rows[0] = ["id", "name", "created_at"]

    with pytest.raises(ValueError, match="missing required headers: active"):
        migrate_workbook(workbook)


def test_migration_rejects_payees_worksheet_missing_created_at() -> None:
    workbook = FakeWorkbook()
    workbook.worksheet("Payees").rows[0] = ["id", "name", "active"]

    with pytest.raises(ValueError, match="missing required headers: created_at"):
        migrate_workbook(workbook)


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        (["id", "name", "active", ""], "blank header"),
        (["id", "name", "active", "active"], "duplicate headers"),
    ],
)
def test_migration_rejects_malformed_payees_headers(
    headers: list[str], message: str
) -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows[0] = headers
    payee_sheet.rows.append(["existing-id", "Existing vendor", "", ""])
    original_payees = [list(row) for row in payee_sheet.rows]
    transaction_sheet = workbook.worksheet("Transactions")
    original_transactions = [list(row) for row in transaction_sheet.rows]

    with pytest.raises(ValueError, match=message):
        migrate_workbook(workbook)

    assert payee_sheet.rows == original_payees
    assert transaction_sheet.rows == original_transactions


@pytest.mark.parametrize(
    ("header_change", "message"),
    [
        (lambda headers: headers.__setitem__(1, ""), "blank header"),
        (lambda headers: headers.__setitem__(1, headers[0]), "duplicate headers"),
        (
            lambda headers: headers.append("payee"),
            "exactly one payee",
        ),
    ],
)
def test_migration_rejects_malformed_transaction_headers(
    header_change: Callable[[list[str]], None], message: str
) -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    headers = list(transaction_sheet.rows[0])
    header_change(headers)
    transaction_sheet.rows[0] = headers
    original_transactions = [list(row) for row in transaction_sheet.rows]
    payee_sheet = workbook.worksheet("Payees")
    original_payees = [list(row) for row in payee_sheet.rows]

    with pytest.raises(ValueError, match=message):
        migrate_workbook(workbook)

    assert transaction_sheet.rows == original_transactions
    assert payee_sheet.rows == original_payees


def test_migration_rejects_dangling_uuid_payee_id() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "123e4567-e89b-12d3-a456-426614174000",
            "",
            "",
            "",
            "now",
        ]
    )
    original_transactions = [list(row) for row in transaction_sheet.rows]
    payee_sheet = workbook.worksheet("Payees")
    original_payees = [list(row) for row in payee_sheet.rows]

    with pytest.raises(ValueError, match="unknown payee_id"):
        migrate_workbook(workbook)

    assert transaction_sheet.rows == original_transactions
    assert payee_sheet.rows == original_payees


def test_migration_rejects_dangling_non_uuid_payee_id() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "vendor-1",
            "",
            "",
            "",
            "now",
        ]
    )
    original_transactions = [list(row) for row in transaction_sheet.rows]
    payee_sheet = workbook.worksheet("Payees")
    original_payees = [list(row) for row in payee_sheet.rows]

    with pytest.raises(ValueError, match="unknown payee_id"):
        migrate_workbook(workbook)

    assert transaction_sheet.rows == original_transactions
    assert payee_sheet.rows == original_payees


def test_legacy_restore_accepts_extra_payee_headers() -> None:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = source.create_account("Checking", "Bank")
    category = source.create_category("Office", "Expense")
    source.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    target_workbook = FakeWorkbook()
    target_workbook.worksheet("Payees").rows[0].append("notes")
    target = GoogleSheetsStorage(target_workbook, sleeper=lambda _: None)

    counts = target.restore_backup_zip(_legacy_backup(source, "Legacy vendor"))

    assert counts["Transactions"] == 1
    assert target_workbook.worksheet("Payees").rows == [
        ["id", "name", "active", "created_at", "notes"]
    ]


def test_migration_appends_payees_in_existing_header_order() -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows[0] = ["name", "id", "active", "created_at", "notes"]
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "New vendor",
            "",
            "",
            "",
            "now",
        ]
    )

    migrate_workbook(workbook)

    stored = dict(zip(payee_sheet.rows[0], payee_sheet.rows[1]))
    assert stored["name"] == "New vendor"
    assert stored["id"]
    assert stored["active"] == "TRUE"
    assert stored["created_at"]
    assert stored["notes"] == ""
    assert transaction_sheet.rows[1][payee_index] == stored["id"]


def test_migration_normalizes_existing_payee_id_before_detecting_additions() -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows.append(["  existing-id  ", "Existing vendor", "TRUE", ""])
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        [
            "txn",
            "2026-09-01",
            "Expense",
            "10.00",
            "account",
            "",
            "category",
            "Existing vendor",
            "",
            "",
            "",
            "now",
        ]
    )

    result = migrate_workbook(workbook)

    assert result == {"payees": 0, "transactions": 1}
    assert len(payee_sheet.rows) == 2
    assert transaction_sheet.rows[1][payee_index] == "existing-id"


def test_migration_accepts_empty_transactions_worksheet() -> None:
    workbook = FakeWorkbook()
    workbook.worksheet("Transactions").rows.clear()

    assert migrate_workbook(workbook) == {"payees": 0, "transactions": 0}


def test_migration_resumes_after_header_write_failure() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        ["txn", "2026-09-01", "Expense", "10.00", "account", "", "category", "Legacy vendor", "", "", "", "now"]
    )
    original_update = transaction_sheet.update

    def fail_first_transaction_row(
        values: list[list[str]], range_name: str, **kwargs: object
    ) -> None:
        if range_name == "A1" and len(values) > 1:
            original_update(values[:1], range_name, **kwargs)
            raise OSError("simulated interrupted migration")
        original_update(values, range_name, **kwargs)

    transaction_sheet.update = fail_first_transaction_row  # type: ignore[method-assign]
    with pytest.raises(OSError, match="interrupted"):
        migrate_workbook(workbook)

    transaction_sheet.update = original_update  # type: ignore[method-assign]
    result = migrate_workbook(workbook)

    assert result == {"payees": 0, "transactions": 1}
    assert transaction_sheet.rows[1][payee_index]
    assert workbook.worksheet("Payees").rows[1][1] == "Legacy vendor"
    assert migrate_workbook(workbook) == {"payees": 0, "transactions": 0}


def test_migration_resumes_after_partial_payee_append() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.extend(
        [
            ["one", "2026-09-01", "Expense", "10.00", "account", "", "category", "First vendor", "", "", "", "now"],
            ["two", "2026-09-02", "Expense", "11.00", "account", "", "category", "Second vendor", "", "", "", "now"],
        ]
    )
    payee_sheet = workbook.worksheet("Payees")
    original_append = payee_sheet.append_rows

    def append_first_then_fail(
        values: list[list[str]], **kwargs: object
    ) -> None:
        original_append(values[:1], **kwargs)
        raise OSError("simulated interrupted payee append")

    payee_sheet.append_rows = append_first_then_fail  # type: ignore[method-assign]
    with pytest.raises(OSError, match="payee append"):
        migrate_workbook(workbook)

    payee_sheet.append_rows = original_append  # type: ignore[method-assign]
    result = migrate_workbook(workbook)

    assert result == {"payees": 1, "transactions": 2}
    assert {row[1] for row in payee_sheet.rows[1:]} == {
        "First vendor",
        "Second vendor",
    }
    assert transaction_sheet.rows[0][payee_index] == "payee_id"
    assert all(transaction_sheet.rows[index][payee_index] for index in (1, 2))


def test_migration_initializes_an_empty_payees_worksheet() -> None:
    workbook = FakeWorkbook()
    workbook.sheets["Payees"].rows = []
    transaction_sheet = workbook.worksheet("Transactions")
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        ["txn", "2026-09-01", "Expense", "10.00", "account", "", "category", "Legacy vendor", "", "", "", "now"]
    )

    result = migrate_workbook(workbook)

    assert result == {"payees": 1, "transactions": 1}
    assert workbook.worksheet("Payees").rows[0] == list(
        ("id", "name", "active", "created_at")
    )


def test_legacy_backup_maps_only_to_existing_payees() -> None:
    workbook = FakeWorkbook()
    transaction_sheet = workbook.sheets["Transactions"]
    payee_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[0][payee_index] = "payee"
    transaction_sheet.rows.append(
        ["txn", "2026-09-01", "Expense", "10.00", "account", "", "category", "Acme Supplies", "", "", "", "now"]
    )
    result = migrate_workbook(workbook)

    assert result["payees"] == 1
    assert transaction_sheet.rows[0][payee_index] == "payee_id"
    assert transaction_sheet.rows[1][payee_index]


def test_transactions_reject_arbitrary_payee_text_after_migration() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    with pytest.raises(StorageValidationError, match="stored payee"):
        storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            payee="Free text must not persist",
        )

    assert storage.list_transactions() == []


def test_invalid_transaction_does_not_create_new_payee() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    with pytest.raises(StorageValidationError, match="greater than zero"):
        storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=0,
            account_id=account["id"],
            category_id=category["id"],
            new_payee_name="Should not be created",
        )

    assert storage.list_payees() == []


def test_quickbooks_import_batches_new_payee_writes() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    payee_sheet = storage._workbook.sheets["Payees"]
    payee_sheet.append_rows = Mock(wraps=payee_sheet.append_rows)

    rows = [
        {
            "Date": f"09/0{index}/2026",
            "Transaction Type": "Expense",
            "Num": str(index),
            "Name": f"Vendor {index}",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
        for index in range(1, 4)
    ]

    imported = storage.import_quickbooks_transactions(rows)

    assert len(imported) == 3
    assert payee_sheet.append_rows.call_count == 1
    assert {item["payee"] for item in imported} == {
        "Vendor 1",
        "Vendor 2",
        "Vendor 3",
    }


def test_quickbooks_import_reuses_canonical_payee_for_duplicates() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.create_payee("Acme Inc")
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme  Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
    ]

    assert len(storage.import_quickbooks_transactions(rows)) == 1
    assert storage.import_quickbooks_transactions(rows) == []
    assert len(storage.list_transactions()) == 1


def test_quickbooks_import_deduplicates_unseen_payee_variants() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        },
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme  Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        },
    ]

    preview = storage.preview_quickbooks_transactions(rows)

    assert len(preview["rows"]) == 1
    assert preview["duplicate_rows"] == [3]
    assert len(storage.import_quickbooks_transactions(rows)) == 1
    assert len(storage.list_payees()) == 1


def test_quickbooks_import_rejects_inactive_account_before_payee_write() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.edit_account(account["id"], active=False)
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Vendor",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
    ]

    preview = storage.preview_quickbooks_transactions(rows)

    assert preview["rows"] == []
    assert preview["errors"] == [
        "QuickBooks row 2: source account 'Checking' is inactive"
    ]
    with pytest.raises(StorageValidationError, match="source account.*inactive"):
        storage.import_quickbooks_transactions(rows)
    assert storage.list_payees() == []
    assert storage.list_transactions() == []


def test_concurrent_payee_creation_rechecks_inside_shared_lock() -> None:
    workbook = FakeWorkbook()
    first = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    second = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    payee_sheet = workbook.worksheet("Payees")
    original_append = payee_sheet.append_row
    append_started = threading.Event()
    release_append = threading.Event()

    def delayed_append(values: list[str], **kwargs: object) -> None:
        if not append_started.is_set():
            append_started.set()
            assert release_append.wait(timeout=2)
        original_append(values, **kwargs)

    payee_sheet.append_row = delayed_append  # type: ignore[method-assign]
    results: list[dict[str, str]] = []

    def create(storage: GoogleSheetsStorage) -> None:
        results.append(storage.create_payee("Concurrent vendor"))

    first_thread = threading.Thread(target=create, args=(first,))
    second_thread = threading.Thread(target=create, args=(second,))
    first_thread.start()
    assert append_started.wait(timeout=2)
    second_thread.start()
    release_append.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert len(results) == 2
    assert results[0]["id"] == results[1]["id"]
    assert len(workbook.worksheet("Payees").rows) == 2


def test_concurrent_payee_renames_recheck_inside_shared_lock() -> None:
    workbook = FakeWorkbook()
    first = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    second = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    first_payee = first.create_payee("First vendor")
    second_payee = second.create_payee("Second vendor")
    payee_sheet = workbook.worksheet("Payees")
    original_update = payee_sheet.update
    update_started = threading.Event()
    release_update = threading.Event()

    def delayed_update(
        values: list[list[str]], range_name: str, **kwargs: object
    ) -> None:
        if not update_started.is_set():
            update_started.set()
            assert release_update.wait(timeout=2)
        original_update(values, range_name, **kwargs)

    payee_sheet.update = delayed_update  # type: ignore[method-assign]
    renamed: list[dict[str, str]] = []
    errors: list[Exception] = []

    def rename(storage: GoogleSheetsStorage, payee_id: str) -> None:
        try:
            renamed.append(storage.edit_payee(payee_id, name="Merged vendor"))
        except Exception as error:  # pragma: no cover - assertion below checks the type
            errors.append(error)

    first_thread = threading.Thread(target=rename, args=(first, first_payee["id"]))
    second_thread = threading.Thread(target=rename, args=(second, second_payee["id"]))
    first_thread.start()
    assert update_started.wait(timeout=2)
    second_thread.start()
    release_update.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert len(renamed) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], StorageConflictError)
    assert len(workbook.worksheet("Payees").rows) == 3


def test_new_payee_transaction_uses_created_record_without_refresh() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    original_lookup = storage._payee_lookup
    storage._payee_lookup = Mock(wraps=original_lookup)

    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        new_payee_name="New vendor",
    )

    assert storage._payee_lookup.call_count == 1
    assert storage._payee_lookup.call_args.kwargs["force_refresh"] is False


def test_csv_import_validates_all_rows_before_creating_payees() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    rows = [
        {
            "Date": "2026-09-01",
            "Type": "Expense",
            "Account": "Checking",
            "Category": "Office",
            "Amount": "10.00",
            "Payee": "First vendor",
        },
        {
            "Date": "not-a-date",
            "Type": "Expense",
            "Account": "Checking",
            "Category": "Office",
            "Amount": "10.00",
            "Payee": "Second vendor",
        },
    ]

    with pytest.raises(StorageValidationError, match="Date"):
        storage.import_csv_transactions(rows)

    assert storage.list_transactions() == []
    assert storage.list_payees() == []
    assert account["name"] == "Checking"
    assert category["name"] == "Office"


def test_backup_rejects_invalid_payee_records() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    payee = storage.create_payee("Valid vendor")
    backup = storage.export_backup_zip(
        build_receipt_manifest("test", storage.list_transactions(), [])
    )
    contents: dict[str, bytes]
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    payee_rows = list(csv.reader(io.StringIO(contents["Payees.csv"].decode())))
    payee_rows[1][1] = ""
    csv_buffer = io.StringIO(newline="")
    csv.writer(csv_buffer, lineterminator="\n").writerows(payee_rows)
    contents["Payees.csv"] = csv_buffer.getvalue().encode()
    manifest = json.loads(contents["manifest.json"])
    manifest["sha256"]["Payees.csv"] = hashlib.sha256(
        contents["Payees.csv"]
    ).hexdigest()
    contents["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in contents.items():
            destination.writestr(name, content)

    with pytest.raises(StorageValidationError, match="Payee name"):
        GoogleSheetsStorage.validate_backup_zip(output.getvalue())
    assert payee["name"] == "Valid vendor"


def test_legacy_backup_maps_payee_text_to_existing_stored_value() -> None:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = source.create_account("Checking", "Bank")
    category = source.create_category("Office", "Expense")
    payee = source.create_payee("Acme Supplies")
    source.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
    )
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target_payee = target.create_payee(" acme   supplies ")

    counts = target.restore_backup_zip(_legacy_backup(source, "Acme Supplies"))

    assert counts["Transactions"] == 1
    assert target.list_transactions()[0]["payee_id"] == target_payee["id"]


def test_legacy_backup_drops_unmatched_payee_text() -> None:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = source.create_account("Checking", "Bank")
    category = source.create_category("Office", "Expense")
    payee = source.create_payee("Unknown vendor")
    source.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
    )
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.create_payee("Different vendor")

    target.restore_backup_zip(_legacy_backup(source, "Unknown vendor"))

    restored = target.list_transactions()[0]
    assert restored["payee_id"] == ""
    assert restored["payee"] == ""


def test_legacy_backup_without_transactions_preserves_existing_payees() -> None:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    backup = source.export_backup_zip(
        build_receipt_manifest("test", source.list_transactions(), [])
    )
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    transaction_rows = list(
        csv.reader(io.StringIO(contents["Transactions.csv"].decode("utf-8")))
    )
    payee_id_index = transaction_rows[0].index("payee_id")
    transaction_rows[0][payee_id_index] = "payee"
    csv_buffer = io.StringIO(newline="")
    csv.writer(csv_buffer, lineterminator="\n").writerows(transaction_rows)
    contents["Transactions.csv"] = csv_buffer.getvalue().encode("utf-8")
    manifest["format_version"] = 6
    manifest["worksheet_headers"]["Transactions"] = transaction_rows[0]
    manifest["worksheet_headers"].pop("Payees")
    manifest["row_counts"].pop("Payees")
    manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
        contents["Transactions.csv"]
    ).hexdigest()
    manifest["sha256"].pop("Payees.csv")
    contents.pop("Payees.csv")
    contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in contents.items():
            destination.writestr(name, content)

    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    existing = target.create_payee("Existing vendor")

    target.restore_backup_zip(output.getvalue())

    assert target.list_payees()[0]["id"] == existing["id"]
