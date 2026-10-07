"""Pure canonical export projections into the existing reporting read models."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from tabula_rasa.application.reporting import calculation_records
from tabula_rasa.application.reporting_contracts import (
    LedgerSnapshot, LedgerTransaction, LedgerJournal, LedgerPosting, ReportingAccount, ReportingCategory,
)
from tabula_rasa.accounting_postings import accounting_postings


def _instant(value):
    return datetime.fromisoformat(value).isoformat().replace("+00:00", "Z")


def ledger_snapshot(domains):
    """Project validated exported history without regeneration or active filtering."""
    lines = defaultdict(list)
    for row in domains["postings"]:
        lines[row["entry_id"]].append(row)
    payees = {row["id"]: row["name"] for row in domains["payees"]}
    tag_names = {row["id"]: row["name"] for row in domains["tags"]}
    tags = defaultdict(list)
    for row in domains["entry_tags"]:
        tags[("entry", row["entry_id"])].append(row["tag_id"])
    for row in domains["mixed_use_tags"]:
        tags[("source", row["source_id"])].append(row["tag_id"])
    receipts = defaultdict(int)
    for row in domains["document_links"]:
        receipts[(row["entry_id"], row["mixed_use_source_id"])] += 1
    occurrences = {(row["entry_id"], row["mixed_use_source_id"]): row for row in domains["recurring_occurrences"]}
    transactions, journals = [], []
    for entry in sorted(domains["entries"], key=lambda row: (row["txn_date"], row["created_at"], row["id"]), reverse=True):
        postings = sorted(lines[entry["id"]], key=lambda row: row["position"])
        if entry["projection_kind"] == "journal":
            journals.append(LedgerJournal(
                id=entry["id"], date=date.fromisoformat(entry["txn_date"]), description=entry["description"],
                created_at=_instant(entry["created_at"]), updated_at=_instant(entry["updated_at"]), postings=tuple(
                    LedgerPosting(id=line["id"], position=line["position"], side=line["side"], amount=Decimal(line["amount"]),
                                  target_type="account" if line["account_id"] else "category",
                                  target_id=line["account_id"] or line["category_id"], payee_id=line["payee_id"] or "",
                                  payee=payees.get(line["payee_id"], ""), description=line["description"])
                    for line in postings),
            ))
            continue
        debit, credit = postings
        source = entry["mixed_use_source_id"]
        owner = (None, source) if source else (entry["id"], None)
        occurrence = occurrences.get(owner, {})
        tag_ids = tuple(sorted(tags[("source", source) if source else ("entry", entry["id"])]))
        transactions.append(LedgerTransaction(
            id=entry["id"], date=date.fromisoformat(entry["txn_date"]), kind=entry["simple_kind"],
            amount=Decimal(debit["amount"]),
            account_id=(debit["account_id"] if entry["simple_kind"] == "Income" else credit["account_id"]) or "",
            to_account_id=debit["account_id"] if entry["simple_kind"] == "Transfer" else "",
            category_id=debit["category_id"] or credit["category_id"] or "",
            payee_id=entry["payee_id"] or "", payee=payees.get(entry["payee_id"], ""), description=entry["description"],
            reference=entry["reference"], created_at=_instant(entry["created_at"]), tag_ids=tag_ids,
            tags=tuple(tag_names[tag] for tag in tag_ids), receipt_count=receipts[owner],
            source_type="mixed_use_expense" if source else "depreciation" if entry["depreciation_asset_id"] else "",
            source_id=source or entry["depreciation_asset_id"] or "",
            recurring_schedule_id=occurrence.get("schedule_id", ""),
            recurring_scheduled_date=date.fromisoformat(occurrence["scheduled_date"]) if occurrence else None,
            recurring_source_kind=occurrence.get("source_kind", ""), recurring_occurrence_type=occurrence.get("occurrence_type", ""),
        ))
    return LedgerSnapshot(
        tuple(sorted((ReportingAccount(id=row["id"], name=row["name"], type=row["type"], classification=row["classification"],
                                       opening_balance=Decimal(row["opening_balance"]), active=row["active"], parent_id=row["parent_id"] or "")
                      for row in domains["accounts"]), key=lambda row: row.name.casefold())),
        tuple(sorted((ReportingCategory(id=row["id"], name=row["name"], kind=row["kind"], parent_id=row["parent_id"] or "")
                      for row in domains["categories"]), key=lambda row: (row.kind, row.name.casefold()))),
        tuple(transactions), tuple(journals),
    )


def normalized_accounting(snapshot):
    """Exact comparison facts using the shared Simple Ledger expansion owner."""
    accounts, categories, transactions, journals = calculation_records(snapshot)
    fields = ("entry_type", "parent_entry_id", "id", "txn_date", "target_type", "target_id", "category_kind", "side", "amount")
    return {
        "accounts": sorted((row["id"], row["classification"], row["parent_id"], row["opening_balance"]) for row in accounts),
        "categories": sorted((row["id"], row["kind"], row["parent_id"]) for row in categories),
        "postings": sorted(tuple(row[field] for field in fields) for row in accounting_postings(transactions, journals, categories)),
    }
