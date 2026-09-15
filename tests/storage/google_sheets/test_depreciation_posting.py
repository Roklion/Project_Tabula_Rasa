from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from tabula_rasa.ledger_reporting import account_balances, balance_sheet, profit_and_loss
from tabula_rasa.storage.google_sheets.depreciation_posting import depreciation_entry_id
from .test_assets import _asset_data
from ._support import (
    FakeWorkbook, GoogleSheetsStorage, GoogleSheetsStorageTestCase,
    StorageConflictError, StorageValidationError, StorageUnavailableError, backup_receipt_manifest, pytest,
    rewrite_backup_tables,
)


class TestDepreciationPosting(GoogleSheetsStorageTestCase):
    def asset(self, **changes):
        expense = self.storage.create_category("Depreciation", "Expense")
        offset = self.storage.create_account("Accumulated depreciation", "Other", classification="Asset")
        return self.storage.create_asset(**_asset_data(
            depreciation_expense_account_id=expense["id"],
            accumulated_depreciation_account_id=offset["id"], **changes))

    def test_posting_is_non_cash_balanced_expense_and_idempotent(self):
        bank = self.storage.create_account("Bank", "Bank", opening_balance="500")
        self.storage.create_account("Opening equity", "Equity", opening_balance="-500")
        asset = self.asset(cost_basis="100.01", useful_life_quarters=3)
        self.storage.post_due_depreciation(asset["id"], "2025-04-30", expected_asset=asset)
        rows = self.storage.list_transactions()
        assert len(rows) == 2
        assert {r["id"] for r in rows} == {depreciation_entry_id(asset["id"], n) for n in (1, 2)}
        assert {r["source_id"] for r in rows} == {asset["id"]}
        assert self.storage.post_due_depreciation(asset["id"], "2025-04-30") == []
        self.storage.post_due_depreciation(asset["id"], "2025-12-31")
        rows = self.storage.list_transactions()
        assert sorted(r["amount"] for r in rows) == ["33.33", "33.34", "33.34"]
        accounts = self.storage.list_accounts()
        balances = {r["id"]: r["balance"] for r in account_balances(accounts, rows)}
        assert balances[bank["id"]] == 500
        assert balances[asset["accumulated_depreciation_account_id"]] == -100.01
        assert profit_and_loss(rows)["expenses"] == 100.01
        sheet = balance_sheet(accounts, rows)
        assert sheet["current_earnings"] == -100.01
        assert sheet["difference"] == 0

    def test_history_protects_source_and_all_ordinary_mutations(self):
        asset = self.asset()
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        entry = self.storage.list_transactions()[0]
        for operation in (
            lambda: self.storage.edit_transaction(entry["id"], amount="1"),
            lambda: self.storage.delete_transaction(entry["id"]),
            lambda: self.storage.bulk_delete_transactions([entry["id"]], expected_transactions=[entry]),
            lambda: self.storage.bulk_edit_transactions([entry["id"]], expected_transactions=[entry], changes={"payee_id": ""}),
            lambda: self.storage.create_recurring_expense_from_transaction(entry["id"]),
        ):
            with pytest.raises(StorageValidationError, match="Assets"):
                operation()
        for operation in (
            lambda: self.storage.edit_asset(asset["id"], cost_basis="500"),
            lambda: self.storage.delete_asset(asset["id"]),
            lambda: self.storage.retire_asset(asset["id"], "2025-01-20"),
            lambda: self.storage.override_asset_period(asset["id"], 1, 10, "change", as_of_date=date(2025, 2, 1)),
        ):
            with pytest.raises(StorageConflictError):
                operation()
        self.storage.edit_asset(asset["id"], name="Renamed")
        assert self.storage.list_transactions()[0]["description"] == entry["description"]
        self.storage.retire_asset(asset["id"], "2025-04-30")
        assert len(self.storage.post_due_depreciation(asset["id"], "2030-01-01")) == 1

    def test_stale_asset_invalid_accounts_and_zero_amount_periods(self):
        asset = self.asset(cost_basis="0.01", useful_life_quarters=3)
        self.storage.edit_asset(asset["id"], name="Changed")
        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.post_due_depreciation(asset["id"], "2026-01-01", expected_asset=asset)
        self.storage.post_due_depreciation(asset["id"], "2026-01-01")
        assert sum(Decimal(r["amount"]) for r in self.storage.list_transactions()) == Decimal("0.01")
        assert len(self.storage.list_transactions()) == 3
        empty = self.storage.create_asset(**_asset_data())
        with pytest.raises(StorageValidationError, match="expense"):
            self.storage.post_due_depreciation(empty["id"], "2026-01-01")

    def test_concurrent_sessions_and_two_profile_isolation(self):
        asset = self.asset()
        peer = GoogleSheetsStorage(self.workbook, sleeper=lambda _: None)
        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda storage: storage.post_due_depreciation(asset["id"], "2025-01-31"), [self.storage, peer]))
        assert sum(len(result) for result in results) == 1
        assert other.list_transactions() == []
        assert other.list_assets() == []

    def test_uncertain_committed_append_is_reconciled_and_backup_restores(self):
        asset = self.asset()
        sheet = self.workbook.worksheet("Transactions")
        original = sheet.append_row
        calls = []
        def uncertain(*args, **kwargs):
            original(*args, **kwargs)
            calls.append(1)
            raise TimeoutError("synthetic timeout")
        with patch.object(sheet, "append_row", side_effect=uncertain):
            self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        assert len(calls) == 1
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        restored.restore_backup_zip(backup)
        assert restored.list_transactions() == self.storage.list_transactions()
        assert restored.post_due_depreciation(asset["id"], "2025-01-31") == []

    def test_partial_failure_keeps_confirmed_period_and_resumes_without_duplicates(self):
        asset = self.asset()
        sheet = self.workbook.worksheet("Transactions")
        original = sheet.append_row
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise TimeoutError("synthetic timeout")
            original(*args, **kwargs)
        with patch.object(sheet, "append_row", side_effect=fail_second):
            with pytest.raises(StorageUnavailableError):
                self.storage.post_due_depreciation(asset["id"], "2025-04-30")
        assert len(calls) == 3  # One successful period, one failed period and its bounded retry.
        assert len(self.storage.list_transactions()) == 1
        assert len(self.storage.post_due_depreciation(asset["id"], "2025-04-30")) == 1
        assert len(self.storage.list_transactions()) == 2

    def test_account_reference_guards_and_inactive_account_posting(self):
        asset = self.asset()
        category_id = asset["depreciation_expense_account_id"]
        offset_id = asset["accumulated_depreciation_account_id"]
        with pytest.raises(StorageConflictError, match="asset"):
            self.storage.delete_category(category_id)
        with pytest.raises(StorageConflictError, match="asset"):
            self.storage.edit_category(category_id, kind="Income")
        with pytest.raises(StorageConflictError, match="asset"):
            self.storage.edit_account(offset_id, type="Bank")
        self.storage.deactivate_account(offset_id)
        with pytest.raises(StorageValidationError, match="inactive"):
            self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        assert self.storage.list_transactions() == []

    def test_corrupt_provenance_and_amount_are_rejected_on_restore(self):
        asset = self.asset()
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        for field, value in (("source_id", "missing"), ("id", "wrong-period"), ("amount", "12.00")):
            def corrupt(rows):
                rows[1][rows[0].index(field)] = value
            broken = rewrite_backup_tables(backup, {"Transactions": corrupt})
            restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
            with pytest.raises(StorageValidationError, match="Depreciation"):
                restored.restore_backup_zip(broken)
            assert restored.list_transactions() == []

    def test_same_source_identity_in_two_workbooks_posts_independently(self):
        asset = self.asset()
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        other.restore_backup_zip(backup)
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        assert other.list_transactions() == []
        other.post_due_depreciation(asset["id"], "2025-04-30")
        assert len(other.list_transactions()) == 2
        assert len(self.storage.list_transactions()) == 1

    def test_historical_override_allows_initial_posting_account_configuration(self):
        asset = self.storage.create_asset(**_asset_data())
        self.storage.override_asset_period(asset["id"], 1, 25, "Historical amount", as_of_date=date(2025, 2, 1))
        category = self.storage.create_category("Depreciation", "Expense")
        offset = self.storage.create_account("Accumulated depreciation", "Other", classification="Asset")
        self.storage.edit_asset(asset["id"], depreciation_expense_account_id=category["id"],
                                accumulated_depreciation_account_id=offset["id"])
        assert self.storage.post_due_depreciation(asset["id"], "2025-01-31")[0]["amount"] == "25.00"
        with pytest.raises(StorageConflictError, match="locked"):
            self.storage.remove_asset_period_override(asset["id"], 1)
