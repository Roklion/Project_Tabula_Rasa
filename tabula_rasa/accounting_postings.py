"""Deterministic in-memory accounting postings for both ledger record types."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any


def accounting_postings(
    transactions: Iterable[Mapping[str, Any]],
    journals: Iterable[Mapping[str, Any]] = (),
    categories: Iterable[Mapping[str, Any]] = (),
) -> Iterable[dict[str, Any]]:
    """Expand simple entries without persisting a second accounting ledger.

    Shared domain rules own reference/balance validation. This adapter preserves journal
    direction, and retains simple category kind even without a category lookup.
    """
    category_kinds = {str(row["id"]): str(row["kind"]) for row in categories}
    for entry in transactions:
        kind = entry["kind"]
        if kind == "Income":
            targets = (("account", entry.get("account_id", ""), "Debit"),
                       ("category", entry.get("category_id", ""), "Credit"))
        elif kind == "Expense":
            targets = (("category", entry.get("category_id", ""), "Debit"),
                       ("account", entry.get("account_id", ""), "Credit"))
        elif kind == "Transfer":
            targets = (("account", entry.get("to_account_id", ""), "Debit"),
                       ("account", entry.get("account_id", ""), "Credit"))
        else:
            raise ValueError("Unsupported simple transaction kind")
        for index, (target_type, target_id, side) in enumerate(targets, 1):
            yield {
                "entry_type": "transaction", "parent_entry_id": entry.get("id", ""),
                "id": f"{entry.get('id', '')}:{index}", "txn_date": entry.get("txn_date", ""),
                "target_type": target_type, "target_id": str(target_id or ""),
                "category_kind": kind if target_type == "category" else "",
                "side": side, "amount": Decimal(str(entry["amount"])),
            }
    for entry in journals:
        for line in entry["postings"]:
            target_id = str(line["target_id"])
            is_category = line["target_type"] == "category"
            if is_category and target_id not in category_kinds:
                # Account-only consumers may omit Categories; P&L consumers
                # supply them and validate the kind below before using it.
                category_kind = ""
            else:
                category_kind = category_kinds.get(target_id, "") if is_category else ""
            yield {
                **line, "entry_type": "journal", "parent_entry_id": entry["id"],
                "txn_date": entry["txn_date"], "category_kind": category_kind,
                "amount": Decimal(str(line["amount"])),
            }


def category_activity(posting: Mapping[str, Any]) -> Decimal:
    """Return conventional signed income/expense activity for a category line."""
    kind = posting["category_kind"]
    if kind not in {"Income", "Expense"}:
        raise ValueError("Journal reporting requires its managed category records")
    positive_side = "Credit" if kind == "Income" else "Debit"
    return posting["amount"] if posting["side"] == positive_side else -posting["amount"]
