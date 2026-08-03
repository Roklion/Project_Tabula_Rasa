from __future__ import annotations


from tabula_rasa.ledger_reporting import (
    account_balances,
    balance_sheet,
    category_activity_rollups,
    expenses_by_category,
    monthly_performance,
    profit_and_loss,
)


class TestLedgerReporting:
    def setup_method(self) -> None:
        self.accounts = [
            {"id": "checking", "name": "Checking", "opening_balance": "100.00"},
            {"id": "savings", "name": "Savings", "opening_balance": "10.00"},
        ]
        self.categories = [
            {"id": "sales", "name": "Sales", "kind": "Income"},
            {"id": "software", "name": "Software", "kind": "Expense"},
        ]
        self.transactions = [
            {
                "id": "income",
                "txn_date": "2026-06-30",
                "kind": "Income",
                "amount": "50.00",
                "account_id": "checking",
                "to_account_id": "",
                "category_id": "sales",
            },
            {
                "id": "expense",
                "txn_date": "2026-07-01",
                "kind": "Expense",
                "amount": "20.00",
                "account_id": "checking",
                "to_account_id": "",
                "category_id": "software",
            },
            {
                "id": "transfer",
                "txn_date": "2026-07-02",
                "kind": "Transfer",
                "amount": "30.00",
                "account_id": "checking",
                "to_account_id": "savings",
                "category_id": "",
            },
        ]

    def test_balances_include_transfers(self) -> None:
        balances = {
            account["id"]: account["balance"]
            for account in account_balances(self.accounts, self.transactions)
        }
        assert balances == {"checking": 100.0, "savings": 40.0}

    def test_profit_and_loss_excludes_transfers_and_honors_dates(self) -> None:
        assert profit_and_loss(self.transactions) == {
            "income": 50.0,
            "expenses": 20.0,
            "net": 30.0,
        }
        assert profit_and_loss(self.transactions, start="2026-07-01") == {
            "income": 0.0,
            "expenses": 20.0,
            "net": -20.0,
        }

    def test_monthly_and_category_totals(self) -> None:
        assert monthly_performance(self.transactions) == [
            {"month": "2026-06", "income": 50.0, "expenses": 0.0},
            {"month": "2026-07", "income": 0.0, "expenses": 20.0},
        ]
        assert expenses_by_category(self.transactions, self.categories) == [
            {"category": "Software", "total": 20.0}
        ]

    def test_balance_sheet_classifies_accounts_and_includes_earnings(self) -> None:
        accounts = [
            {
                "id": "bank",
                "name": "Checking",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "1000.00",
            },
            {
                "id": "card",
                "name": "Credit card",
                "type": "Credit card",
                "classification": "Liability",
                "opening_balance": "-200.00",
            },
            {
                "id": "capital",
                "name": "Owner capital",
                "type": "Equity",
                "classification": "Equity",
                "opening_balance": "-800.00",
            },
        ]
        transactions = [
            {
                "txn_date": "2026-07-01",
                "kind": "Expense",
                "amount": "50.00",
                "account_id": "card",
                "to_account_id": "",
                "category_id": "software",
            }
        ]

        report = balance_sheet(accounts, transactions)

        assert report["total_assets"] == 1000.0
        assert report["total_liabilities"] == 250.0
        assert report["current_earnings"] == -50.0
        assert report["total_equity"] == 750.0
        assert report["difference"] == 0.0

    def test_account_rollups_do_not_double_count_grand_totals(self) -> None:
        accounts = [
            {
                "id": "assets",
                "name": "Operating assets",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "100.00",
                "active": False,
                "parent_id": "",
            },
            {
                "id": "checking",
                "name": "Checking",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "30.00",
                "active": True,
                "parent_id": "assets",
            },
            {
                "id": "cash",
                "name": "Cash",
                "type": "Cash",
                "classification": "Asset",
                "opening_balance": "20.00",
                "active": True,
                "parent_id": "assets",
            },
            {
                "id": "debts",
                "name": "Debts",
                "type": "Credit card",
                "classification": "Liability",
                "opening_balance": "-100.00",
                "active": True,
                "parent_id": "",
            },
            {
                "id": "card",
                "name": "Card",
                "type": "Credit card",
                "classification": "Liability",
                "opening_balance": "-50.00",
                "active": True,
                "parent_id": "debts",
            },
            {
                "id": "equity",
                "name": "Equity",
                "type": "Equity",
                "classification": "Equity",
                "opening_balance": "0.00",
                "active": True,
                "parent_id": "",
            },
        ]
        transactions = [
            {
                "txn_date": "2026-07-01",
                "kind": "Income",
                "amount": "25.00",
                "account_id": "assets",
                "to_account_id": "",
                "category_id": "sales",
            }
        ]

        report = balance_sheet(accounts, transactions)
        asset_rows = {row["id"]: row for row in report["assets"]}
        liability_rows = {row["id"]: row for row in report["liabilities"]}

        assert asset_rows["assets"]["direct_balance"] == 125.0
        assert asset_rows["assets"]["rollup_balance"] == 175.0
        assert asset_rows["checking"]["rollup_balance"] == 30.0
        assert liability_rows["debts"]["direct_balance"] == 100.0
        assert liability_rows["debts"]["rollup_balance"] == 150.0
        assert report["total_assets"] == 175.0
        assert report["total_liabilities"] == 150.0
        assert report["current_earnings"] == 25.0
        assert report["total_equity"] == 25.0
        assert report["difference"] == 0.0

    def test_account_rollups_honor_dates_empty_parents_and_current_parent(self) -> None:
        accounts = [
            {
                "id": "first",
                "name": "First",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "0",
                "parent_id": "",
            },
            {
                "id": "second",
                "name": "Second",
                "type": "Bank",
                "classification": "Asset",
                "opening_balance": "0",
                "parent_id": "",
            },
            {
                "id": "child",
                "name": "Child",
                "type": "Cash",
                "classification": "Asset",
                "opening_balance": "10",
                "parent_id": "second",
            },
        ]
        transactions = [
            {
                "txn_date": "2026-07-02",
                "kind": "Income",
                "amount": "5",
                "account_id": "child",
                "to_account_id": "",
                "category_id": "sales",
            }
        ]

        before = balance_sheet(accounts, transactions, as_of="2026-07-01")
        after = balance_sheet(accounts, transactions, as_of="2026-07-02")
        before_rows = {row["id"]: row for row in before["assets"]}
        after_rows = {row["id"]: row for row in after["assets"]}

        assert before_rows["first"]["rollup_balance"] == 0.0
        assert before_rows["second"]["rollup_balance"] == 10.0
        assert after_rows["second"]["rollup_balance"] == 15.0

    def test_category_rollups_keep_direct_child_and_uncategorized_detail(self) -> None:
        categories = [
            {"id": "travel", "name": "Travel", "kind": "Expense", "parent_id": ""},
            {
                "id": "flights",
                "name": "Flights",
                "kind": "Expense",
                "parent_id": "travel",
            },
            {
                "id": "hotels",
                "name": "Hotels",
                "kind": "Expense",
                "parent_id": "travel",
            },
            {"id": "sales", "name": "Sales", "kind": "Income", "parent_id": ""},
        ]
        transactions = [
            {"txn_date": "2026-07-01", "kind": "Expense", "amount": "10", "category_id": "travel"},
            {"txn_date": "2026-07-02", "kind": "Expense", "amount": "20", "category_id": "flights"},
            {"txn_date": "2026-07-03", "kind": "Expense", "amount": "30", "category_id": "hotels"},
            {"txn_date": "2026-07-04", "kind": "Expense", "amount": "4", "category_id": ""},
            {"txn_date": "2026-07-05", "kind": "Transfer", "amount": "99", "category_id": "travel"},
            {"txn_date": "2026-07-06", "kind": "Income", "amount": "40", "category_id": "sales"},
        ]

        rows = category_activity_rollups(
            transactions,
            categories,
            kind="Expense",
            end="2026-07-04",
        )

        assert rows == [
            {
                "id": "travel",
                "category": "Travel",
                "parent_id": "",
                "layer": 1,
                "direct_total": 10.0,
                "rollup_total": 60.0,
            },
            {
                "id": "flights",
                "category": "Flights",
                "parent_id": "travel",
                "layer": 2,
                "direct_total": 20.0,
                "rollup_total": 20.0,
            },
            {
                "id": "hotels",
                "category": "Hotels",
                "parent_id": "travel",
                "layer": 2,
                "direct_total": 30.0,
                "rollup_total": 30.0,
            },
            {
                "id": "",
                "category": "Uncategorized",
                "parent_id": "",
                "layer": 1,
                "direct_total": 4.0,
                "rollup_total": 4.0,
            },
        ]
        assert expenses_by_category(
            transactions,
            categories,
            end="2026-07-04",
        ) == [
            {"category": "Travel", "total": 60.0},
            {"category": "Uncategorized", "total": 4.0},
        ]
        assert category_activity_rollups(
            transactions,
            categories,
            kind="Income",
        ) == [
            {
                "id": "sales",
                "category": "Sales",
                "parent_id": "",
                "layer": 1,
                "direct_total": 40.0,
                "rollup_total": 40.0,
            }
        ]

    def test_category_rollup_uses_current_parent_after_move(self) -> None:
        categories = [
            {"id": "travel", "name": "Travel", "kind": "Expense", "parent_id": ""},
            {"id": "office", "name": "Office", "kind": "Expense", "parent_id": ""},
            {
                "id": "flights",
                "name": "Flights",
                "kind": "Expense",
                "parent_id": "office",
            },
        ]
        transactions = [
            {"txn_date": "2026-07-01", "kind": "Expense", "amount": "20", "category_id": "flights"}
        ]

        assert expenses_by_category(transactions, categories) == [
            {"category": "Office", "total": 20.0}
        ]

    def test_category_rollup_treats_none_parent_as_layer_one(self) -> None:
        categories = [
            {
                "id": "travel",
                "name": "Travel",
                "kind": "Expense",
                "parent_id": None,
            }
        ]
        transactions = [
            {
                "txn_date": "2026-07-01",
                "kind": "Expense",
                "amount": "20",
                "category_id": "travel",
            }
        ]

        assert expenses_by_category(transactions, categories) == [
            {"category": "Travel", "total": 20.0}
        ]

    def test_category_rollup_keeps_orphaned_activity_visible(self) -> None:
        categories = [
            {
                "id": "travel",
                "name": "Travel",
                "kind": "Expense",
                "parent_id": "missing",
            },
            {
                "id": "income-parent",
                "name": "Revenue",
                "kind": "Income",
                "parent_id": "",
            },
            {
                "id": "wrong-kind-child",
                "name": "Other expense",
                "kind": "Expense",
                "parent_id": "income-parent",
            },
        ]
        transactions = [
            {
                "txn_date": "2026-07-01",
                "kind": "Expense",
                "amount": "20",
                "category_id": "travel",
            },
            {
                "txn_date": "2026-07-02",
                "kind": "Expense",
                "amount": "5",
                "category_id": "wrong-kind-child",
            },
        ]

        assert expenses_by_category(transactions, categories) == [
            {"category": "Travel", "total": 20.0},
            {"category": "Other expense", "total": 5.0},
        ]
