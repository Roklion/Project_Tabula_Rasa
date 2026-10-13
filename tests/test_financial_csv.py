"""The retained CSV formats, accounting values and whole-entry grouping."""

import csv
from dataclasses import replace
from datetime import date
from decimal import Decimal
import io
from types import SimpleNamespace

import pytest

from tabula_rasa.application.financial_csv import financial_csv_exports, selected_ledger_csv
from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.application.reporting_contracts import (
    LedgerFilter, LedgerJournal, LedgerPosting, LedgerSnapshot, LedgerTransaction,
    ReportingAccount, ReportingCategory,
)
from tabula_rasa.errors import StorageNotFoundError
from tabula_rasa.ledger_records import LEDGER_COLUMNS
from tests.test_journal_exports import JOURNAL_COLUMNS, TRANSACTION_COLUMNS


def csv_rows(content):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    return reader.fieldnames, list(reader)


def financial_snapshot(name="Alpha"):
    return LedgerSnapshot(
        accounts=(ReportingAccount("parent", "Parent", "Bank", "Asset", Decimal("0"), True),
                  ReportingAccount("bank", name, "Bank", "Asset", Decimal("0"), False, "parent")),
        categories=(ReportingCategory("expense", "Materials", "Expense"),),
        transactions=(LedgerTransaction("simple", date(2026, 10, 1), "Expense", Decimal("12.50"), "bank",
            category_id="expense", payee="=Vendor", description="Memo, with\nnewline and \"quotes\"",
            reference="@reference", receipt_count=1, tags=("+Tag",)),
            LedgerTransaction("transfer", date(2026, 10, 2), "Transfer", Decimal("100.00"), "bank", "parent")),
        journals=(LedgerJournal("shared-journal", date(2026, 10, 3), (
            LedgerPosting("debit", "category", "expense", "Debit", Decimal("5.25"), 1, payee="-Vendor", description="Debit memo"),
            LedgerPosting("credit", "account", "bank", "Credit", Decimal("5.25"), 2, description="\t=Credit memo"),
        ), description=" =Journal"),),
    )


def query(snapshot, filters=LedgerFilter()):
    return ReportingService(SimpleNamespace(read_ledger=lambda **_: snapshot)).query_ledger(filters)


def test_full_csv_formats_preserve_transaction_scope_leaf_names_tags_and_posting_identity():
    exports = financial_csv_exports(financial_snapshot())
    columns, transactions = csv_rows(exports["transactions"])
    assert columns == TRANSACTION_COLUMNS
    assert [row["ID"] for row in transactions] == ["simple", "transfer"]
    assert transactions[0]["Amount"] == "12.50" and transactions[1]["Amount"] == "100.00"
    assert transactions[0]["Account"] == "Alpha"  # Full export retains leaf names, including inactive targets.
    assert transactions[1]["Type"] == "Transfer" and transactions[1]["Category"] == ""
    assert transactions[1]["To account"] == "Parent"
    assert transactions[0]["Description"] == 'Memo, with\nnewline and "quotes"'
    assert transactions[0]["Payee"] == "'=Vendor" and transactions[0]["Reference"] == "'@reference"
    assert transactions[0]["Tags"] == "'+Tag"
    columns, postings = csv_rows(exports["journals"])
    assert columns == JOURNAL_COLUMNS
    assert [row["Entry ID"] for row in postings] == ["shared-journal"] * 2
    assert [row["Posting ID"] for row in postings] == ["debit", "credit"]
    assert [row["Position"] for row in postings] == ["1", "2"]
    assert [(row["Debit"], row["Credit"]) for row in postings] == [("5.25", ""), ("", "5.25")]
    assert [row["Account type"] for row in postings] == ["category", "account"]
    assert [row["Account ID"] for row in postings] == ["expense", "bank"]
    assert postings[0]["Memo"] == "' =Journal" and postings[0]["Payee"] == "'-Vendor"
    assert postings[1]["Description"] == "'\t=Credit memo"


def test_selected_csv_preserves_visible_columns_order_and_complete_journal_group():
    columns, rows = csv_rows(selected_ledger_csv(query(financial_snapshot()), ["journal:shared-journal", "simple"]))
    expected = list(LEDGER_COLUMNS)
    expected[7:7] = ["Debit", "Credit"]
    assert columns == expected
    assert [row["Type"] for row in rows] == ["Journal", "↳ Posting", "↳ Posting", "Expense"]
    assert [row["ID"] for row in rows] == ["journal:shared-journal", "", "", "simple"]
    assert rows[0]["Amount"] == "5.25"
    assert rows[1]["Debit"] == "5.25" and rows[2]["Credit"] == "5.25"
    assert rows[1]["Amount"] == rows[2]["Amount"] == ""
    assert rows[2]["Account"] == "Parent › Alpha"
    assert rows[3]["Receipt"] == "📎" and rows[3]["Payee"] == "'=Vendor"
    assert rows[3]["Tags"] == "'+Tag"
    columns, rows = csv_rows(selected_ledger_csv(query(financial_snapshot()), ["transfer", "simple", "simple"]))
    assert columns == LEDGER_COLUMNS
    assert [row["ID"] for row in rows] == ["transfer", "simple"]


def test_empty_exports_have_existing_column_headers_without_synthetic_values():
    exports = financial_csv_exports(LedgerSnapshot())
    assert csv_rows(exports["transactions"]) == (TRANSACTION_COLUMNS, [])
    assert csv_rows(exports["journals"]) == (JOURNAL_COLUMNS, [])
    assert csv_rows(selected_ledger_csv(query(LedgerSnapshot()), [])) == (LEDGER_COLUMNS, [])


@pytest.mark.parametrize("identity", ["missing", "debit", "shared-journal"])
def test_partial_or_missing_selected_entries_refuse_the_entire_download(identity):
    with pytest.raises(StorageNotFoundError):
        selected_ledger_csv(query(financial_snapshot()), ["simple", identity])


def test_selection_must_remain_inside_structured_filters_and_shared_ids_do_not_cross_entities():
    with pytest.raises(StorageNotFoundError):
        selected_ledger_csv(query(financial_snapshot(), LedgerFilter(kind="Transfer")), ["simple"])
    for name in ("Alpha", "Beta"):
        exports = financial_csv_exports(financial_snapshot(name))
        assert csv_rows(exports["transactions"])[1][0]["Account"] == name
        assert csv_rows(exports["journals"])[1][1]["Account"] == name
        rows = csv_rows(selected_ledger_csv(query(financial_snapshot(name)), ["simple"]))[1]
        assert rows[0]["Account"] == "Parent › " + name


@pytest.mark.parametrize("text", ["=formula", "+formula", "-formula", "@formula", " \ufeff=hidden", "\ttext", "\rtext", "\ntext"])
def test_all_formula_leading_text_remains_literal_while_numeric_signs_are_preserved(text):
    snapshot = financial_snapshot()
    transaction = replace(snapshot.transactions[0], amount=Decimal("-12.50"), payee=text, tags=(text,))
    snapshot = replace(snapshot, transactions=(transaction,))
    full = csv_rows(financial_csv_exports(snapshot)["transactions"])[1][0]
    selected = csv_rows(selected_ledger_csv(query(snapshot), ["simple"]))[1][0]
    assert full["Payee"] == selected["Payee"] == "'" + text
    normalized_tag = text.strip()
    expected_tag = "'" + normalized_tag if normalized_tag[0] in '=+-@\ufeff' else normalized_tag
    assert full["Tags"] == selected["Tags"] == expected_tag
    assert full["Amount"] == selected["Amount"] == "-12.50"


@pytest.mark.parametrize("amount", ["90071992547409.91", "-90071992547409.91"])
def test_csv_money_retains_exact_cents_beyond_float_precision(amount):
    snapshot = financial_snapshot()
    transaction = replace(snapshot.transactions[0], amount=Decimal(amount))
    journal = replace(snapshot.journals[0], postings=tuple(
        replace(line, amount=abs(Decimal(amount))) for line in snapshot.journals[0].postings))
    snapshot = replace(snapshot, transactions=(transaction,), journals=(journal,))
    exports = financial_csv_exports(snapshot)
    assert csv_rows(exports["transactions"])[1][0]["Amount"] == amount
    postings = csv_rows(exports["journals"])[1]
    assert postings[0]["Debit"] == postings[1]["Credit"] == amount.lstrip('-')
    rows = csv_rows(selected_ledger_csv(query(snapshot), ["simple", "journal:shared-journal"]))[1]
    assert rows[0]["Amount"] == amount
    assert rows[1]["Amount"] == rows[2]["Debit"] == rows[3]["Credit"] == amount.lstrip('-')
    assert rows[2]["Amount"] == rows[3]["Amount"] == ""
