from __future__ import annotations

from scripts.migrate_payees import migrate_payee_rows, migrate_workbook
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


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
