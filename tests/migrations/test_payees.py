from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts.migrate_payees import migrate_payee_rows, migrate_workbook
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tests.fakes import FakeWorkbook

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


def test_migration_persists_payee_normalization_before_noop_return() -> None:
    workbook = FakeWorkbook()
    payee_sheet = workbook.worksheet("Payees")
    payee_sheet.rows.append(["payee-1", "Existing vendor", "", "now"])
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
            "payee-1",
            "",
            "",
            "[]",
            "now",
        ]
    )
    transaction_sheet.update = Mock(wraps=transaction_sheet.update)  # type: ignore[method-assign]

    migrate_workbook(workbook)

    assert payee_sheet.rows[1][2] == "TRUE"
    transaction_sheet.update.assert_not_called()


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
