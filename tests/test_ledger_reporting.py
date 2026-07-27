from __future__ import annotations


from tabula_rasa.ledger_reporting import (
    account_balances,
    balance_sheet,
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
