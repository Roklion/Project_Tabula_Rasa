"""Persistence-neutral ledger queries and existing financial reports."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal, getcontext, localcontext

from tabula_rasa.ledger_queries import combine_ledger_entries, filter_ledger_entries
from tabula_rasa.ledger_reporting import (
    account_balances,
    balance_sheet,
    category_activity_rollups,
    monthly_performance,
    profit_and_loss,
)

from .reporting_contracts import (
    LedgerEntry,
    LedgerFilter,
    LedgerQuery,
    LedgerQueryRepository,
    LedgerSnapshot,
    PeriodReport,
)


def calculation_records(snapshot: LedgerSnapshot) -> tuple[list[dict], ...]:
    """Adapt native domain projections to the existing pure calculation owner.

    This is an in-memory domain mapping, independent of provider serialization.
    Receipt and recurring metadata are unnecessary for accounting calculations.
    """
    accounts = [asdict(row) for row in snapshot.accounts]
    categories = [asdict(row) for row in snapshot.categories]
    transactions = [
        {
            "id": row.id, "txn_date": row.date.isoformat(), "kind": row.kind,
            "amount": row.amount, "account_id": row.account_id,
            "to_account_id": row.to_account_id, "category_id": row.category_id,
            "tag_ids": row.tag_ids, "created_at": row.created_at,
        }
        for row in snapshot.transactions
    ]
    journals = [
        {
            "id": row.id, "txn_date": row.date.isoformat(),
            "created_at": row.created_at,
            "postings": [asdict(posting) for posting in row.postings],
        }
        for row in snapshot.journals
    ]
    return accounts, categories, transactions, journals


def _calculation_context(snapshot: LedgerSnapshot):
    """Keep cent-valued inputs exact, including growth in aggregate totals.

    Scope precision to this calculation without changing the process context.
    The largest input's integer digits, cents, and the number of contributing
    terms bound sum precision; two extra digits cover statement differences.
    """
    amounts = [row.opening_balance for row in snapshot.accounts]
    amounts.extend(row.amount for row in snapshot.transactions)
    amounts.extend(line.amount for row in snapshot.journals for line in row.postings)
    precision = max((value.adjusted() + 3 for value in amounts), default=3)
    return localcontext(prec=max(getcontext().prec, precision + len(str(len(amounts) + 1)) + 2))


class ReportingService:
    """Query one injected ledger; presentation owns labels, frames, and charts."""

    def __init__(self, repository: LedgerQueryRepository) -> None:
        self._repository = repository

    def read_ledger(self, *, force_refresh: bool = False) -> LedgerSnapshot:
        return self._repository.read_ledger(force_refresh=force_refresh)

    def query_ledger(
        self,
        filters: LedgerFilter = LedgerFilter(),
        *,
        force_refresh: bool = False,
        snapshot: LedgerSnapshot | None = None,
    ) -> LedgerQuery:
        snapshot = snapshot if snapshot is not None else self.read_ledger(
            force_refresh=force_refresh
        )
        _, _, transactions, journals = calculation_records(snapshot)
        selected = filter_ledger_entries(
            combine_ledger_entries(transactions, journals),
            start=filters.start, end=filters.end, kind=filters.kind,
            targets=(
                *(('account', value) for value in filters.account_ids),
                *(('category', value) for value in filters.category_ids),
            ),
            tag_ids=filters.tag_ids,
        )
        transaction_by_id = {row.id: row for row in snapshot.transactions}
        journal_by_id = {f"journal:{row.id}": row for row in snapshot.journals}
        entries = tuple(
            LedgerEntry(
                id=row["id"], kind=row["kind"],
                date=date.fromisoformat(row["txn_date"]),
                amount=Decimal(row["amount"]),
                transaction=transaction_by_id.get(row["id"]),
                journal=journal_by_id.get(row["id"]),
            )
            for row in selected
        )
        return LedgerQuery(snapshot=snapshot, entries=entries)

    def period_report(
        self, snapshot: LedgerSnapshot, *, start: date | None = None,
        end: date | None = None, decimal_values: bool = False,
    ) -> PeriodReport:
        _, categories, transactions, journals = calculation_records(snapshot)
        with _calculation_context(snapshot):
            return PeriodReport(
                totals=profit_and_loss(
                    transactions, start=start, end=end, journals=journals, categories=categories,
                    decimal_values=decimal_values,
                ),
                monthly=tuple(monthly_performance(
                    transactions, start=start, end=end, journals=journals, categories=categories,
                )),
                expense_categories=tuple(category_activity_rollups(
                    transactions, categories, kind="Expense", start=start, end=end,
                    journals=journals,
                )),
            )

    def account_balances(self, snapshot: LedgerSnapshot, *, decimal_values: bool = False) -> list[dict]:
        accounts, _, transactions, journals = calculation_records(snapshot)
        with _calculation_context(snapshot):
            return account_balances(accounts, transactions, journals=journals, decimal_values=decimal_values)

    def balance_sheet(
        self, snapshot: LedgerSnapshot, *, as_of: date | None = None, decimal_values: bool = False,
    ) -> dict:
        accounts, categories, transactions, journals = calculation_records(snapshot)
        with _calculation_context(snapshot):
            return balance_sheet(
                accounts, transactions, as_of=as_of, journals=journals, categories=categories,
                decimal_values=decimal_values,
            )
