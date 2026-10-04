"""Translate neutral query results into existing UI table records."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from tabula_rasa.application.reporting_contracts import LedgerEntry, LedgerSnapshot
from tabula_rasa.hierarchy import hierarchy_paths
from tabula_rasa.ledger_queries import combine_ledger_entries


def snapshot_display_records(snapshot: LedgerSnapshot) -> tuple[list[dict], ...]:
    """Keep dates, amounts, and names compatible with current presentation helpers.

    These read-only display records are never mutation baselines. The legacy
    editing controllers still receive the storage facade's exact snapshots.
    """
    accounts = [asdict(row) for row in snapshot.accounts]
    categories = [asdict(row) for row in snapshot.categories]
    transactions = []
    for row in snapshot.transactions:
        record = asdict(row)
        record["txn_date"] = record.pop("date").isoformat()
        record["tag_ids"] = list(row.tag_ids)
        record["tags"] = list(row.tags)
        transactions.append(record)
    journals = []
    for row in snapshot.journals:
        record = asdict(row)
        record["txn_date"] = record.pop("date").isoformat()
        record["postings"] = [asdict(line) for line in row.postings]
        journals.append(record)
    return accounts, categories, transactions, journals


def ledger_entry_display_records(entries: tuple[LedgerEntry, ...]) -> list[dict]:
    snapshot = LedgerSnapshot(
        transactions=tuple(row.transaction for row in entries if row.transaction is not None),
        journals=tuple(row.journal for row in entries if row.journal is not None),
    )
    _, _, transactions, journals = snapshot_display_records(snapshot)
    by_id = {row["id"]: row for row in combine_ledger_entries(transactions, journals)}
    return [by_id[entry.id] for entry in entries]


def account_balance_display_frame(rows: list[dict], accounts: list[dict]) -> pd.DataFrame:
    """Format already calculated balances without recalculating in presentation."""
    account_paths = hierarchy_paths(accounts)
    return pd.DataFrame(
        [
            {
                "ID": row["id"],
                "Account": account_paths.get(row["id"], row["name"]),
                "Type": row["type"], "Classification": row["classification"],
                "Active": row["active"], "Balance": row["balance"],
            }
            for row in rows
        ],
        columns=["ID", "Account", "Type", "Classification", "Active", "Balance"],
    )
