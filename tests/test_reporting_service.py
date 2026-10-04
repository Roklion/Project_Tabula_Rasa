"""Reporting behavior through a native, persistence-free application port."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.application.reporting_contracts import (
    LedgerFilter,
    LedgerJournal,
    LedgerPosting,
    LedgerSnapshot,
    LedgerTransaction,
    ReportingAccount,
    ReportingCategory,
)


class FakeLedgerQueryRepository:
    def __init__(self, snapshot: LedgerSnapshot) -> None:
        self.snapshot = snapshot
        self.reads: list[bool] = []
        self.error: Exception | None = None

    def read_ledger(self, *, force_refresh: bool = False) -> LedgerSnapshot:
        self.reads.append(force_refresh)
        if self.error is not None:
            raise self.error
        return self.snapshot


@pytest.fixture
def ledger() -> LedgerSnapshot:
    return LedgerSnapshot(
        accounts=(
            ReportingAccount("bank", "Checking", "Bank", "Asset", Decimal("100"), True),
            ReportingAccount("savings", "Savings", "Bank", "Asset", Decimal("0"), False),
            ReportingAccount("capital", "Capital", "Equity", "Equity", Decimal("-100"), True),
        ),
        categories=(
            ReportingCategory("sales", "Sales", "Income"),
            ReportingCategory("operations", "Operations", "Expense"),
            ReportingCategory("office", "Office", "Expense", "operations"),
        ),
        transactions=(
            LedgerTransaction(
                "income", date(2026, 6, 30), "Income", Decimal("50"), "bank",
                category_id="sales", tag_ids=("client",),
            ),
            LedgerTransaction(
                "expense", date(2026, 7, 1), "Expense", Decimal("20"), "bank",
                category_id="office", tag_ids=("internal", "client"),
            ),
            LedgerTransaction(
                "transfer", date(2026, 7, 2), "Transfer", Decimal("30"), "bank",
                to_account_id="savings",
            ),
        ),
        journals=(LedgerJournal(
            "split", date(2026, 7, 3), (
                LedgerPosting("debit", "category", "office", "Debit", Decimal("15"), 1),
                LedgerPosting("credit", "account", "bank", "Credit", Decimal("15"), 2),
            ), description="Journal expense",
        ),),
    )


def test_structured_queries_keep_complete_journals_and_transfer_sides(ledger) -> None:
    repository = FakeLedgerQueryRepository(ledger)
    service = ReportingService(repository)
    query = service.query_ledger()
    assert [entry.id for entry in query.entries] == ["journal:split", "transfer", "expense", "income"]
    assert query.entries[0].journal is ledger.journals[0]
    assert query.entries[0].amount == Decimal("15")
    assert len(query.entries[0].journal.postings) == 2
    assert repository.reads == [False]

    def ids(filters):
        return [entry.id for entry in service.query_ledger(filters, snapshot=ledger).entries]

    assert ids(LedgerFilter(account_ids=("savings",))) == ["transfer"]
    assert ids(LedgerFilter(category_ids=("office",))) == ["journal:split", "expense"]
    assert ids(LedgerFilter(kind="Journal")) == ["journal:split"]
    assert ids(LedgerFilter(tag_ids=("missing", "client"))) == ["expense", "income"]
    assert ids(LedgerFilter(
        start=date(2026, 7, 1), end=date(2026, 7, 1),
        account_ids=("bank",), category_ids=("sales",), tag_ids=("client",),
    )) == ["expense"]
    assert ids(LedgerFilter(start=date(2026, 8, 1), end=date(2026, 7, 1))) == []
    assert repository.reads == [False]  # Reusing a snapshot performs no extra reads.


def test_current_reports_preserve_transfers_hierarchy_and_independent_as_of(ledger) -> None:
    service = ReportingService(FakeLedgerQueryRepository(ledger))
    period = service.period_report(ledger, start=date(2026, 7, 1), end=date(2026, 7, 31))
    assert period.totals == {"income": 0.0, "expenses": 35.0, "net": -35.0}
    assert period.monthly == ({"month": "2026-07", "income": 0.0, "expenses": 35.0},)
    assert [(row["category"], row["layer"], row["direct_total"], row["rollup_total"])
            for row in period.expense_categories] == [
        ("Operations", 1, 0.0, 35.0), ("Office", 2, 35.0, 35.0),
    ]
    balances = {row["id"]: row["balance"] for row in service.account_balances(ledger)}
    assert balances == {"bank": 85.0, "savings": 30.0, "capital": -100.0}
    statement = service.balance_sheet(ledger, as_of=date(2026, 6, 30))
    assert statement["total_assets"] == 150.0
    assert statement["total_equity"] == 150.0
    assert statement["current_earnings"] == 50.0
    assert statement["difference"] == 0.0
    assert service.balance_sheet(ledger)["difference"] == 0.0


def test_empty_ledgers_and_reversed_period_preserve_empty_results(ledger) -> None:
    service = ReportingService(FakeLedgerQueryRepository(LedgerSnapshot()))
    assert service.query_ledger().entries == ()
    report = service.period_report(LedgerSnapshot())
    assert report.totals == {"income": 0.0, "expenses": 0.0, "net": 0.0}
    assert report.monthly == report.expense_categories == ()
    assert service.balance_sheet(LedgerSnapshot())["difference"] == 0.0
    reversed_report = service.period_report(ledger, start=date(2026, 8, 1), end=date(2026, 7, 1))
    assert reversed_report.totals == report.totals


def test_repository_failures_propagate_once_and_profiles_share_no_snapshot(ledger) -> None:
    north_repository = FakeLedgerQueryRepository(ledger)
    south_repository = FakeLedgerQueryRepository(LedgerSnapshot(transactions=(
        LedgerTransaction("income", date(2026, 7, 1), "Income", Decimal("200"), "bank",
                          category_id="sales"),
    )))
    north, south = ReportingService(north_repository), ReportingService(south_repository)
    assert north.query_ledger(force_refresh=True).entries[-1].amount == Decimal("50")
    assert south.query_ledger().entries[0].amount == Decimal("200")
    assert north_repository.reads == [True]
    assert south_repository.reads == [False]
    failure = RuntimeError("Synthetic read failure")
    south_repository.error = failure
    with pytest.raises(RuntimeError) as raised:
        south.query_ledger()
    assert raised.value is failure
    assert south_repository.reads == [False, False]
    assert len(north.query_ledger().entries) == 4


def test_reporting_import_and_fake_query_need_no_ui_or_provider() -> None:
    code = """
import importlib.abc
import sys
class RejectInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ('streamlit', 'pandas', 'gspread', 'google',
                   'tabula_rasa.storage', 'tabula_rasa.infrastructure', 'tabula_rasa.composition')
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('Reporting imported infrastructure: ' + fullname)
sys.meta_path.insert(0, RejectInfrastructure())
from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.application.reporting_contracts import LedgerSnapshot
class Repository:
    def read_ledger(self, *, force_refresh=False):
        return LedgerSnapshot()
service = ReportingService(Repository())
assert service.query_ledger().entries == ()
assert service.period_report(service.read_ledger()).totals['net'] == 0
"""
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_adapter_normalizes_values_without_leaking_worksheet_metadata() -> None:
    from tabula_rasa.infrastructure.google_sheets_reporting import GoogleSheetsLedgerQueryRepository

    storage = Mock()
    storage.list_accounts.return_value = [{
        "id": "bank", "name": "Checking", "type": "Bank", "classification": "Asset",
        "opening_balance": 10.5, "active": False, "worksheet_row": 4,
    }]
    storage.list_categories.return_value = [{"id": "office", "name": "Office", "kind": "Expense"}]
    storage.list_transactions.return_value = [{
        "id": "expense", "txn_date": "2026-07-01", "kind": "Expense", "amount": "3.25",
        "account_id": "bank", "category_id": "office", "tag_ids": ["client"],
        "tags": ["Client"], "receipt_references": "[]", "worksheet_row": 7,
    }]
    storage.list_journal_entries.return_value = [{
        "id": "split", "txn_date": "2026-07-02", "postings": [{
            "id": "debit", "target_type": "category", "target_id": "office", "side": "Debit",
            "position": "1", "amount": "1.50", "worksheet_row": 9,
        }],
    }]
    adapter = GoogleSheetsLedgerQueryRepository(storage)
    snapshot = adapter.read_ledger(force_refresh=True)
    assert snapshot.accounts[0].opening_balance == Decimal("10.5")
    assert snapshot.accounts[0].active is False
    assert snapshot.transactions[0].date == date(2026, 7, 1)
    assert snapshot.transactions[0].amount == Decimal("3.25")
    assert snapshot.transactions[0].tag_ids == ("client",)
    assert snapshot.transactions[0].receipt_count == 0
    assert snapshot.journals[0].postings[0].position == 1
    assert not hasattr(snapshot.transactions[0], "worksheet_row")
    storage.prefetch_worksheets.assert_not_called()
    storage.list_accounts.assert_called_once_with(active_only=False, _force_refresh=True)
    storage.list_transactions.assert_called_once_with(_force_refresh=True)
    storage.list_journal_entries.assert_called_once_with(_force_refresh=True)

    failure = RuntimeError("Synthetic adapter read failure")
    storage.list_transactions.side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        adapter.read_ledger()
    assert raised.value is failure
    assert storage.list_transactions.call_count == 2


@pytest.mark.parametrize("page", ["dashboard", "reports"])
def test_report_pages_use_application_queries_without_legacy_reads(ledger, monkeypatch, page) -> None:
    from tabula_rasa.page_renderers import dashboard, reports

    module = dashboard if page == "dashboard" else reports
    ui = MagicMock()

    def columns(spec, **kwargs):
        result = [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
        for column in result:
            column.date_input.side_effect = lambda label, value, **kwargs: value
        return result

    ui.columns.side_effect = columns
    ui.date_input.return_value = date(2026, 7, 3)
    monkeypatch.setattr(module, "st", ui)
    monkeypatch.setattr(module, "render_page_header", Mock())
    monkeypatch.setattr(module, "render_global_footer", Mock())
    repository = FakeLedgerQueryRepository(ledger)
    services = SimpleNamespace(profile_key="north", reporting=ReportingService(repository))
    if page == "dashboard":
        context = dashboard.DashboardContext("north", services)
        dashboard.render_dashboard(context)
        activity = ui.dataframe.call_args_list[0].args[0]
        assert list(activity["Type"]) == ["Journal", "Transfer", "Expense", "Income"]
        assert list(activity["Amount"]) == [15.0, 30.0, -20.0, 50.0]
    else:
        context = reports.ReportsContext("north", services, Mock())
        reports.render_reports(context)
        assert ui.dataframe.call_count >= 3
        assert ui.warning.call_count == 0
    ui.error.assert_not_called()
    assert repository.reads == [False]


def test_reporting_page_binding_refuses_another_profiles_service(ledger) -> None:
    from tabula_rasa.page_renderers.reporting_service import reporting_service
    from tabula_rasa.storage import StorageValidationError

    repository = FakeLedgerQueryRepository(ledger)
    context = SimpleNamespace(
        profile_key="south",
        services=SimpleNamespace(profile_key="north", reporting=ReportingService(repository)),
    )
    with pytest.raises(StorageValidationError, match="selected business profile"):
        reporting_service(context)
    assert repository.reads == []
