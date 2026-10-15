"""Logical ledger records and their subordinate, non-mutable display rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

import pandas as pd

from tabula_rasa.hierarchy import hierarchy_paths
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.ledger_queries import (
    combine_ledger_entries as combine_ledger_entries,
    entry_matches_targets as entry_matches_targets,
    filter_ledger_entries as filter_ledger_entries,
    is_journal,
)


LEDGER_COLUMNS = [
    "Date", "Type", "Account", "To account", "Category", "Payee", "Amount",
    "Tags", "Description", "Receipt", "Reference", "ID",
]
SEARCH_FIELDS = (
    "Type", "Account", "To account", "Category", "Payee", "Tags",
    "Description", "Reference", "ID",
)


def journal_summary(entry: Mapping, *, preserve_amounts=False) -> dict:
    row = dict.fromkeys(LEDGER_COLUMNS, "")
    row.update({
        "Date": entry["txn_date"], "Type": "Journal",
        "Account": f"Multiple accounts · {len(entry['postings'])} postings",
        "Amount": Decimal(str(entry["amount"])) if preserve_amounts else float(entry["amount"]), "Description": entry.get("description", ""),
        "ID": entry["id"],
    })
    return row


def posting_display_rows(entry, accounts, categories, *, preserve_amounts=False):
    account_paths = hierarchy_paths(accounts)
    category_paths = hierarchy_paths(categories)
    rows = []
    for line in entry["postings"]:
        names = account_paths if line["target_type"] == "account" else category_paths
        row = dict.fromkeys(LEDGER_COLUMNS, "")
        row.update({
            "Type": "↳ Posting", "Account": names.get(line["target_id"], "Unknown"),
            "Payee": line.get("payee", ""), "Description": line.get("description", ""),
            "Amount": None, "Debit": None, "Credit": None,
        })
        row[line["side"]] = Decimal(str(line["amount"])) if preserve_amounts else float(line["amount"])
        rows.append(row)
    return rows


def search_ledger_entries(entries, summaries, accounts, categories, query):
    query = query.strip().casefold()
    if not query:
        return list(entries)
    by_id = {row["ID"]: row for row in summaries}
    matched = []
    for entry in entries:
        rows = [by_id[entry["id"]]]
        if is_journal(entry):
            rows += posting_display_rows(entry, accounts, categories)
        if any(query in str(row.get(field) or "").casefold() for row in rows for field in SEARCH_FIELDS):
            matched.append(entry)
    return matched


def sort_ledger_entries(entries, summaries, *, field="Date", descending=True):
    by_id = {row["ID"]: row for row in summaries}
    def key(entry):
        value = by_id[entry["id"]].get(field, "")
        if field == "Amount":
            value = Decimal(str(value or 0))
        else:
            value = str(value or "").casefold()
        return value, str(entry.get("created_at", "")), str(entry["id"])
    return sorted(entries, key=key, reverse=descending)


def ledger_summary_frame(entries, accounts, categories, *, tags=(), preserve_amounts=False):
    simple = [row for row in entries if not is_journal(row)]
    frame = ledger_frame(simple, accounts, categories, tags=tags, preserve_amounts=preserve_amounts)
    by_id = {row["ID"]: row for row in frame.to_dict("records")}
    rows = [journal_summary(entry, preserve_amounts=preserve_amounts) if is_journal(entry) else by_id[entry["id"]] for entry in entries]
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS).fillna({"Receipt": "", "Reference": ""})


def flatten_ledger_entries(entries, summaries, accounts, categories, *, preserve_amounts=False):
    """Return display rows and their stable parent map; never sort this frame."""
    by_id = {row["ID"]: row for row in summaries}
    rows, parents = [], []
    has_journals = any(is_journal(entry) for entry in entries)
    for entry in entries:
        rows.append(by_id[entry["id"]])
        parents.append(entry["id"])
        if is_journal(entry):
            children = posting_display_rows(entry, accounts, categories, preserve_amounts=preserve_amounts)
            rows.extend(children)
            parents.extend([entry["id"]] * len(children))
    columns = list(LEDGER_COLUMNS)
    if has_journals:
        columns[7:7] = ["Debit", "Credit"]
    return pd.DataFrame(rows, columns=columns), parents


def selected_parent_ids(parents: Sequence[str], selected_rows: Sequence[int]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(parents[index] for index in selected_rows if 0 <= index < len(parents)))
