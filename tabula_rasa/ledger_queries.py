"""Pure logical ledger identity, ordering, and structured-filter rules."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def combine_ledger_entries(transactions, journals):
    """Keep simple IDs compatible; give journals an explicit selection namespace."""
    entries = [dict(row) for row in transactions]
    simple_ids = {str(row["id"]) for row in entries}
    for journal in journals:
        key = f"journal:{journal['id']}"
        if key in simple_ids:
            raise ValueError("Ledger record identities conflict")
        entries.append({
            **journal, "id": key, "kind": "Journal", "_journal": journal,
            "amount": str(sum(
                (Decimal(line["amount"]) for line in journal["postings"] if line["side"] == "Debit"),
                Decimal("0"),
            )),
            "account_id": "", "to_account_id": "", "category_id": "",
            "payee": "", "tag_ids": [], "tags": [], "receipt_references": "[]",
        })
    return sorted(entries, key=lambda row: (
        str(row["txn_date"]), str(row.get("created_at", "")), str(row["id"]),
    ), reverse=True)


def is_journal(entry: Mapping) -> bool:
    return "_journal" in entry


def entry_matches_targets(entry, targets: set[tuple[str, str]]) -> bool:
    if not targets:
        return True
    if is_journal(entry):
        return any((line["target_type"], line["target_id"]) in targets for line in entry["postings"])
    return bool({
        ("account", str(entry.get("account_id", ""))),
        ("account", str(entry.get("to_account_id", ""))),
        ("category", str(entry.get("category_id", ""))),
    } & targets)


def filter_ledger_entries(entries, *, start=None, end=None, kind=None, targets=(), tag_ids=()):
    targets = set(targets)
    tag_ids = set(tag_ids)
    return [entry for entry in entries if (
        (start is None or str(entry["txn_date"]) >= str(start))
        and (end is None or str(entry["txn_date"]) <= str(end))
        and (not kind or kind == "All" or entry["kind"] == kind)
        and entry_matches_targets(entry, targets)
        and (not tag_ids or tag_ids.intersection(entry.get("tag_ids", ())))
    )]
