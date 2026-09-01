from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile

import pytest

from scripts.migrate_payees import migrate_payee_rows, migrate_workbook
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
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
