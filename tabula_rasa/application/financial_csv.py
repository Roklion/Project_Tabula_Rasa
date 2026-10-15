"""Preparation for the existing financial CSV downloads, independent of UI."""

from dataclasses import asdict
import csv
import io
import re

from tabula_rasa.errors import StorageNotFoundError
from tabula_rasa.ledger_presentation import ledger_frame, transaction_type_label
from tabula_rasa.ledger_queries import combine_ledger_entries
from tabula_rasa.ledger_records import flatten_ledger_entries, ledger_summary_frame


JOURNAL_COLUMNS = [
    "Entry ID", "Date", "Memo", "Posting ID", "Position", "Account type",
    "Account ID", "Account", "Debit", "Credit", "Payee", "Description",
]


def spreadsheet_text(value):
    """Keep formula-leading text literal without changing numeric cells."""
    if isinstance(value, str) and (
        re.match(r"^[\s\uFEFF]*[=+@-]", value) or re.match(r"^[\t\r\n]", value)
    ):
        return "'" + value
    return value


def frame_csv(frame):
    return frame.map(spreadsheet_text).to_csv(index=False).encode("utf-8")


def prepare_financial_csv_exports(*, transactions, journals, accounts, categories, tags):
    """Retain leaf names, transaction signs and every ordered journal posting."""
    transaction_frame = ledger_frame(
        transactions, accounts, categories, display_paths=False, tags=tags, preserve_amounts=True,
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=JOURNAL_COLUMNS)
    writer.writeheader()
    account_names = {row["id"]: row["name"] for row in accounts}
    category_names = {row["id"]: row["name"] for row in categories}
    for entry in journals:
        for line in entry["postings"]:
            names = account_names if line["target_type"] == "account" else category_names
            row = {
                "Entry ID": entry["id"], "Date": entry["txn_date"], "Memo": entry["description"],
                "Posting ID": line["id"], "Position": line["position"],
                "Account type": line["target_type"], "Account ID": line["target_id"],
                "Account": names.get(line["target_id"], ""),
                "Debit": line["amount"] if line["side"] == "Debit" else "",
                "Credit": line["amount"] if line["side"] == "Credit" else "",
                "Payee": line.get("payee", ""), "Description": line["description"],
            }
            writer.writerow({key: value if key in {"Debit", "Credit", "Position"}
                             else spreadsheet_text(value) for key, value in row.items()})
    return {"transactions": frame_csv(transaction_frame), "journals": output.getvalue().encode("utf-8")}


def snapshot_records(snapshot):
    """Adapt native reporting projections to the existing presentation helpers."""
    accounts = [asdict(row) for row in snapshot.accounts]
    categories = [asdict(row) for row in snapshot.categories]
    transactions = [{**asdict(row), "txn_date": row.date.isoformat()} for row in snapshot.transactions]
    journals = [{**asdict(row), "txn_date": row.date.isoformat(),
                 "postings": [{**asdict(line), "amount": format(line.amount, ".2f")}
                              for line in row.postings]} for row in snapshot.journals]
    return accounts, categories, transactions, journals


def financial_csv_exports(snapshot):
    accounts, categories, transactions, journals = snapshot_records(snapshot)
    return prepare_financial_csv_exports(
        transactions=transactions, journals=journals, accounts=accounts, categories=categories, tags=(),
    )


def selected_ledger_csv(query, entry_ids):
    """Select logical IDs in visible order; journals always include all postings."""
    accounts, categories, transactions, journals = snapshot_records(query.snapshot)
    available = {entry.id for entry in query.entries}
    requested = tuple(dict.fromkeys(entry_ids))
    if any(identity not in available for identity in requested):
        # Do not silently export a partial selection after deletion/filter changes.
        raise StorageNotFoundError("Refresh the ledger and select the entries again.")
    by_id = {row["id"]: row for row in combine_ledger_entries(transactions, journals)}
    entries = [by_id[identity] for identity in requested]
    summaries = ledger_summary_frame(entries, accounts, categories, preserve_amounts=True).to_dict("records")
    for row, entry in zip(summaries, entries, strict=True):
        row["Type"] = transaction_type_label(row["Type"], entry)
        row["Receipt"] = "📎" if entry.get("receipt_count") else ""
    frame, _ = flatten_ledger_entries(entries, summaries, accounts, categories, preserve_amounts=True)
    return frame_csv(frame)
