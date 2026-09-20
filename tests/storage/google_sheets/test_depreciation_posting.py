from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from tabula_rasa.ledger_reporting import (
    account_balances,
    balance_sheet,
    profit_and_loss,
)
from tabula_rasa.storage.google_sheets.depreciation_posting import (
    asset_schedule,
    depreciation_entry_id,
    validate_depreciation_history,
)
from .test_assets import _asset_data
from ._support import (
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    StorageConflictError,
    StorageValidationError,
    StorageUnavailableError,
    backup_receipt_manifest,
    pytest,
    rewrite_backup_tables,
)


class TestDepreciationPosting(GoogleSheetsStorageTestCase):
    def asset(self, **changes):
        expense = self.storage.create_category("Depreciation", "Expense")
        offset = self.storage.create_account(
            "Accumulated depreciation", "Other", classification="Asset"
        )
        return self.storage.create_asset(
            **_asset_data(
                depreciation_expense_account_id=expense["id"],
                accumulated_depreciation_account_id=offset["id"],
                **changes,
            )
        )

    def test_posting_is_non_cash_balanced_expense_and_idempotent(self):
        bank = self.storage.create_account("Bank", "Bank", opening_balance="500")
        self.storage.create_account("Opening equity", "Equity", opening_balance="-500")
        asset = self.asset(cost_basis="100.01", useful_life_quarters=3)
        self.storage.post_due_depreciation(
            asset["id"], "2025-04-30", expected_asset=asset
        )
        rows = self.storage.list_transactions()
        assert len(rows) == 2
        assert {r["id"] for r in rows} == {
            depreciation_entry_id(asset["id"], n) for n in (1, 2)
        }
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
            lambda: self.storage.bulk_delete_transactions(
                [entry["id"]], expected_transactions=[entry]
            ),
            lambda: self.storage.bulk_edit_transactions(
                [entry["id"]], expected_transactions=[entry], changes={"payee_id": ""}
            ),
            lambda: self.storage.create_recurring_expense_from_transaction(entry["id"]),
        ):
            with pytest.raises(StorageValidationError, match="Assets"):
                operation()
        for operation in (
            lambda: self.storage.edit_asset(asset["id"], cost_basis="500"),
            lambda: self.storage.delete_asset(asset["id"]),
            lambda: self.storage.retire_asset(asset["id"], "2025-01-20"),
            lambda: self.storage.override_asset_period(
                asset["id"], 1, 10, "change", as_of_date=date(2025, 2, 1)
            ),
        ):
            with pytest.raises(StorageConflictError):
                operation()
        self.storage.edit_asset(asset["id"], name="Renamed")
        assert (
            self.storage.list_transactions()[0]["description"] == entry["description"]
        )
        self.storage.retire_asset(asset["id"], "2025-04-30")
        assert len(self.storage.post_due_depreciation(asset["id"], "2030-01-01")) == 1

    def test_stale_asset_invalid_accounts_and_zero_amount_periods(self):
        asset = self.asset(cost_basis="0.01", useful_life_quarters=3)
        self.storage.edit_asset(asset["id"], name="Changed")
        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.post_due_depreciation(
                asset["id"], "2026-01-01", expected_asset=asset
            )
        self.storage.post_due_depreciation(asset["id"], "2026-01-01")
        assert sum(
            Decimal(r["amount"]) for r in self.storage.list_transactions()
        ) == Decimal("0.01")
        assert len(self.storage.list_transactions()) == 3
        empty = self.storage.create_asset(**_asset_data())
        with pytest.raises(StorageValidationError, match="accounts"):
            self.storage.post_due_depreciation(empty["id"], "2026-01-01")

    def test_concurrent_sessions_and_two_profile_isolation(self):
        asset = self.asset()
        peer = GoogleSheetsStorage(self.workbook, sleeper=lambda _: None)
        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda storage: storage.post_due_depreciation(
                        asset["id"], "2025-01-31"
                    ),
                    [self.storage, peer],
                )
            )
        assert sum(len(result) for result in results) == 1
        assert other.list_transactions() == []
        assert other.list_assets() == []

    def test_uncertain_committed_append_is_reconciled_and_backup_restores(self):
        asset = self.asset()
        sheet = self.workbook.worksheet("Transactions")
        original = sheet.append_rows
        calls = []

        def uncertain(*args, **kwargs):
            original(*args, **kwargs)
            calls.append(1)
            raise TimeoutError("synthetic timeout")

        with patch.object(sheet, "append_rows", side_effect=uncertain):
            self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        assert len(calls) == 1
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))
        restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        restored.restore_backup_zip(backup)
        assert restored.list_transactions() == self.storage.list_transactions()
        assert restored.post_due_depreciation(asset["id"], "2025-01-31") == []

    def test_partial_failure_keeps_confirmed_period_and_resumes_without_duplicates(
        self,
    ):
        asset = self.asset()
        sheet = self.workbook.worksheet("Transactions")
        original = sheet.append_rows
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(1)
            values = args[0]
            original(values[:1], **kwargs)
            raise TimeoutError("synthetic timeout")

        with patch.object(sheet, "append_rows", side_effect=fail_second):
            with pytest.raises(StorageUnavailableError):
                self.storage.post_due_depreciation(asset["id"], "2025-04-30")
        assert len(calls) == 1
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
        for field, value in (
            ("source_id", "missing"),
            ("id", "wrong-period"),
            ("amount", "12.00"),
        ):

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
        self.storage.override_asset_period(
            asset["id"], 1, 25, "Historical amount", as_of_date=date(2025, 2, 1)
        )
        category = self.storage.create_category("Depreciation", "Expense")
        offset = self.storage.create_account(
            "Accumulated depreciation", "Other", classification="Asset"
        )
        self.storage.edit_asset(
            asset["id"],
            depreciation_expense_account_id=category["id"],
            accumulated_depreciation_account_id=offset["id"],
        )
        assert (
            self.storage.post_due_depreciation(asset["id"], "2025-01-31")[0]["amount"]
            == "25.00"
        )
        with pytest.raises(StorageConflictError, match="locked"):
            self.storage.remove_asset_period_override(asset["id"], 1)

    def test_partial_account_configuration_and_inactive_metadata_are_allowed_before_posting(
        self,
    ):
        expense = self.storage.create_category("Depreciation", "Expense")
        asset = self.storage.create_asset(
            **_asset_data(depreciation_expense_account_id=expense["id"])
        )
        assert asset["depreciation_expense_account_id"] == expense["id"]

        offset = self.storage.create_account(
            "Accumulated depreciation", "Other", classification="Asset"
        )
        payee = self.storage.create_payee("Asset vendor")
        tag = self.storage.create_tag("Asset tag")
        configured = self.storage.edit_asset(
            asset["id"],
            accumulated_depreciation_account_id=offset["id"],
            payee_id=payee["id"],
            tag_ids=[tag["id"]],
        )
        self.storage.edit_payee(payee["id"], active=False)
        self.storage.edit_tag(tag["id"], active=False)
        self.storage.post_due_depreciation(configured["id"], "2025-01-31")
        assert len(self.storage.list_transactions()) == 1
        assert self.storage.list_transactions()[0]["payee_id"] == ""
        assert self.storage.list_transactions()[0]["tag_ids"] == []

    def test_posting_prefetches_descriptive_lookups_once(self):
        asset = self.asset(useful_life_quarters=3)
        with (
            patch.object(self.storage, "_payee_lookup", wraps=self.storage._payee_lookup) as payees,
            patch.object(self.storage, "_tag_lookup", wraps=self.storage._tag_lookup) as tags,
        ):
            self.storage.post_due_depreciation(asset["id"], "2025-04-30")
        assert payees.call_count == 1
        assert tags.call_count == 1

    def test_history_accepts_normalized_source_type(self):
        asset = self.asset(cost_basis="0.01", useful_life_quarters=3)
        self.storage.post_due_depreciation(asset["id"], "2025-04-30")
        backup = self.storage.export_backup_zip(backup_receipt_manifest(self.storage))

        def padded_source_type(rows):
            rows[1][rows[0].index("source_type")] = " DePreCiAtIoN "

        restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        restored.restore_backup_zip(
            rewrite_backup_tables(backup, {"Transactions": padded_source_type})
        )
        rows = restored.list_transactions()
        assert len(rows) == 2
        assert rows[0]["amount"] == "0.00"
        with pytest.raises(StorageConflictError):
            restored.edit_asset(asset["id"], cost_basis="500")

    def test_history_normalizes_padded_references(self):
        asset = self.asset()
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        transaction = self.storage.list_transactions()[0]
        padded_asset = dict(
            asset,
            id=f" {asset['id']} ",
            depreciation_expense_account_id=f" {asset['depreciation_expense_account_id']} ",
            accumulated_depreciation_account_id=f" {asset['accumulated_depreciation_account_id']} ",
        )
        padded_transaction = dict(
            transaction,
            id=f" {transaction['id']} ",
            source_type=" depreciation ",
            source_id=f" {asset['id']} ",
            account_id=f" {transaction['account_id']} ",
            category_id=f" {transaction['category_id']} ",
            txn_date=f" {transaction['txn_date']} ",
        )
        accounts = {
            f" {account['id']} ": account
            for account in self.storage.list_accounts(active_only=False)
        }
        categories = {
            f" {category['id']} ": category
            for category in self.storage.list_categories()
        }
        validate_depreciation_history(
            [padded_asset], [padded_transaction], accounts, categories
        )

    def test_listing_depreciation_does_not_reload_assets_for_validation(self):
        asset = self.asset()
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        with patch.object(self.storage, "_rows", wraps=self.storage._rows) as rows:
            self.storage.list_transactions()
        assert all(call.args[0] != "Assets" for call in rows.call_args_list)

    def test_padded_account_id_still_protects_asset_reference(self):
        asset = self.asset()
        with pytest.raises(StorageConflictError, match="asset"):
            self.storage.edit_account(
                f"  {asset['accumulated_depreciation_account_id']}  ",
                type="Bank",
            )

    def test_whitespace_ids_remain_canonical_and_protected(self):
        asset = self.asset()
        padded_id = f"  {asset['id']}  "
        self.storage.post_due_depreciation(padded_id, "2025-01-31")
        entry = self.storage.list_transactions()[0]
        assert entry["source_id"] == asset["id"]
        assert entry["id"] == depreciation_entry_id(asset["id"], 1)
        with pytest.raises(StorageConflictError):
            self.storage.edit_asset(padded_id, cost_basis="500")
        with pytest.raises(StorageConflictError):
            self.storage.delete_asset(padded_id)
        with pytest.raises(StorageConflictError):
            self.storage.delete_category(
                f"  {asset['depreciation_expense_account_id']}  "
            )

    def test_invalid_zero_amount_inputs_are_validation_errors(self):
        asset = self.asset()
        with pytest.raises(StorageValidationError):
            self.storage._prepare_transaction(
                {
                    "txn_date": "2025-01-31",
                    "kind": "Expense",
                    "amount": "not-a-number",
                    "account_id": asset["accumulated_depreciation_account_id"],
                    "category_id": asset["depreciation_expense_account_id"],
                },
                _allow_zero_amount=True,
            )

    def test_malformed_schedule_overrides_and_receipts_are_rejected(self):
        asset = self.asset()
        with pytest.raises(StorageValidationError, match="schedule"):
            asset_schedule(dict(asset, schedule_overrides="[]"))
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        transaction = self.storage.list_transactions()[0]
        with pytest.raises(StorageValidationError, match="conflicts"):
            validate_depreciation_history(
                [asset],
                [dict(transaction, receipt_references='[{"id":"receipt"}]')],
                {
                    account["id"]: account
                    for account in self.storage.list_accounts(active_only=False)
                },
                {category["id"]: category for category in self.storage.list_categories()},
            )

    def test_false_like_receipt_references_are_rejected(self):
        asset = self.asset()
        self.storage.post_due_depreciation(asset["id"], "2025-01-31")
        transaction = self.storage.list_transactions()[0]
        accounts = {
            account["id"]: account
            for account in self.storage.list_accounts(active_only=False)
        }
        categories = {
            category["id"]: category for category in self.storage.list_categories()
        }
        for receipt_references in ("{}", "null", "false", "0", {}, False, 0):
            with pytest.raises(StorageValidationError, match="conflicts"):
                validate_depreciation_history(
                    [asset],
                    [dict(transaction, receipt_references=receipt_references)],
                    accounts,
                    categories,
                )
