from __future__ import annotations

import csv
import io

from tabula_rasa.page_renderers.data_backup.exports import prepare_csv_exports
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TRANSACTION_COLUMNS = [
    "ID",
    "Date",
    "Type",
    "Account",
    "To account",
    "Category",
    "Payee",
    "Description",
    "Reference",
    "Amount",
    "Tags",
]

JOURNAL_COLUMNS = [
    "Entry ID",
    "Date",
    "Memo",
    "Posting ID",
    "Position",
    "Account type",
    "Account ID",
    "Account",
    "Debit",
    "Credit",
    "Payee",
    "Description",
]


def _csv_rows(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    return reader.fieldnames or [], list(reader)


def _storage_with_journal(*, target_name: str) -> GoogleSheetsStorage:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account(target_name, "Bank")
    category = storage.create_category(target_name, "Expense")
    payee = storage.create_payee(f"{target_name} vendor")
    storage.create_transaction(
        txn_date="2026-09-20",
        kind="Expense",
        amount="12.50",
        account_id=account["id"],
        category_id=category["id"],
    )
    storage.create_journal_entry(
        entry_id="shared-entry-id",
        txn_date="2026-09-21",
        description=f"{target_name} journal",
        postings=[
            {
                "id": "shared-posting-debit",
                "target_type": "category",
                "target_id": category["id"],
                "side": "Debit",
                "amount": "100.00",
                "payee_id": payee["id"],
                "description": "Materials",
            },
            {
                "id": "shared-posting-credit",
                "target_type": "account",
                "target_id": account["id"],
                "side": "Credit",
                "amount": "100.00",
                "payee_id": "",
                "description": "Cash paid",
            },
        ],
    )
    return storage


def test_prepare_csv_exports_preserves_transaction_contract_and_exports_every_journal_line() -> None:
    storage = _storage_with_journal(target_name="Clearing")

    exports = prepare_csv_exports(storage, accounts=storage.list_accounts(active_only=False), tags=storage.list_tags())
    transaction_columns, transactions = _csv_rows(exports["transactions"])
    journal_columns, postings = _csv_rows(exports["journals"])

    assert transaction_columns == TRANSACTION_COLUMNS
    assert len(transactions) == 1
    assert transactions[0]["Type"] == "Expense"
    assert transactions[0]["Amount"] == "12.5"

    assert journal_columns == JOURNAL_COLUMNS
    assert len(postings) == 2
    assert {row["Entry ID"] for row in postings} == {"shared-entry-id"}
    assert {row["Posting ID"] for row in postings} == {
        "shared-posting-debit",
        "shared-posting-credit",
    }
    assert [row["Position"] for row in postings] == ["1", "2"]
    assert all(bool(row["Debit"]) ^ bool(row["Credit"]) for row in postings)
    assert postings[0]["Debit"] == "100.00"
    assert postings[0]["Credit"] == ""
    assert postings[1]["Debit"] == ""
    assert postings[1]["Credit"] == "100.00"

    # Account and category deliberately share a display name. The typed target
    # ID and type keep the two postings unambiguous in the export.
    assert postings[0]["Account"] == postings[1]["Account"] == "Clearing"
    assert postings[0]["Account type"] == "category"
    assert postings[1]["Account type"] == "account"
    assert postings[0]["Account ID"] != postings[1]["Account ID"]
    assert postings[0]["Payee"] == "Clearing vendor"


def test_prepare_csv_exports_isolates_profiles_with_equal_journal_ids() -> None:
    north = _storage_with_journal(target_name="North Clearing")
    south = _storage_with_journal(target_name="South Clearing")

    north_rows = _csv_rows(prepare_csv_exports(north, accounts=north.list_accounts(active_only=False), tags=north.list_tags())["journals"])[1]
    south_rows = _csv_rows(prepare_csv_exports(south, accounts=south.list_accounts(active_only=False), tags=south.list_tags())["journals"])[1]

    assert [row["Entry ID"] for row in north_rows] == [
        "shared-entry-id",
        "shared-entry-id",
    ]
    assert [row["Posting ID"] for row in north_rows] == [
        "shared-posting-debit",
        "shared-posting-credit",
    ]
    assert [row["Entry ID"] for row in south_rows] == [
        "shared-entry-id",
        "shared-entry-id",
    ]
    assert [row["Posting ID"] for row in south_rows] == [
        "shared-posting-debit",
        "shared-posting-credit",
    ]
    assert {row["Account"] for row in north_rows} == {
        "North Clearing"
    }
    assert {row["Account"] for row in south_rows} == {
        "South Clearing"
    }
    assert {row["Payee"] for row in north_rows} == {"North Clearing vendor", ""}
    assert {row["Payee"] for row in south_rows} == {"South Clearing vendor", ""}
    assert not any("South" in value for row in north_rows for value in row.values())
    assert not any("North" in value for row in south_rows for value in row.values())
