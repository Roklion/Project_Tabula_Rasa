from __future__ import annotations

import unittest

from ledger_reporting import (
    account_balances,
    expenses_by_category,
    monthly_performance,
    profit_and_loss,
)


class LedgerReportingTests(unittest.TestCase):
    def setUp(self) -> None:
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
        self.assertEqual(balances, {"checking": 100.0, "savings": 40.0})

    def test_profit_and_loss_excludes_transfers_and_honors_dates(self) -> None:
        self.assertEqual(
            profit_and_loss(self.transactions),
            {"income": 50.0, "expenses": 20.0, "net": 30.0},
        )
        self.assertEqual(
            profit_and_loss(self.transactions, start="2026-07-01"),
            {"income": 0.0, "expenses": 20.0, "net": -20.0},
        )

    def test_monthly_and_category_totals(self) -> None:
        self.assertEqual(
            monthly_performance(self.transactions),
            [
                {"month": "2026-06", "income": 50.0, "expenses": 0.0},
                {"month": "2026-07", "income": 0.0, "expenses": 20.0},
            ],
        )
        self.assertEqual(
            expenses_by_category(self.transactions, self.categories),
            [{"category": "Software", "total": 20.0}],
        )


if __name__ == "__main__":
    unittest.main()
