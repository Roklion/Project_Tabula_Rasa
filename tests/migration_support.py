"""A realistic, entirely synthetic frozen profile spanning migration domains."""

from tabula_rasa.application.documents import DocumentMetadata, DocumentReference
from tabula_rasa.infrastructure.sheets_migration import snapshot_from_values
from tabula_rasa.migration.documents import enrich_snapshot
from tabula_rasa.migration.model import Binding
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.receipt_records import document_to_receipt_reference
from tests.test_sheets_migration_source import (
    values_with_mixed_asset_history, values_with_records, mileage_values, WHEN,
)
import json


def put(values, title, index, **changes):
    fields = values[title][0]
    row = dict(zip(fields, values[title][index]))
    row.update(changes)
    values[title][index] = [row.get(field, "") for field in fields]


def document(profile, storage_key, *, verified=False):
    metadata = DocumentMetadata("a" * 32 if verified else "", "Synthetic scan.pdf",
                                "Synthetic original.pdf" if verified else "",
                                "application/pdf" if verified else "", 123 if verified else None,
                                "b" * 64 if verified else "")
    return DocumentReference(profile, metadata, storage_key, "https://drive.google.com/open?id=" + storage_key)


def complete_plan(profile="alpha"):
    values = values_with_mixed_asset_history()
    core = values_with_records(recurring=True, journal=True)
    values["JournalEntries"] += core["JournalEntries"][1:]
    values["JournalPostings"] += core["JournalPostings"][1:]
    put(values, "JournalPostings", 1, amount="2.00", payee_id="vendor", description="Synthetic journal line")
    put(values, "JournalPostings", 2, amount="4.00")
    values["JournalPostings"].append(list(values["JournalPostings"][1]))
    put(values, "JournalPostings", 3, id="second-debit", position="3", amount="3.00")
    values["JournalPostings"].append(list(values["JournalPostings"][2]))
    put(values, "JournalPostings", 4, id="second-credit", position="4", amount="1.00")
    put(values, "Assets", 1, schedule_overrides='{"2":{"amount":"20.00","reason":"Synthetic future override"}}')
    values["RecurringSchedules"] += core["RecurringSchedules"][1:]
    values["Transactions"] += core["Transactions"][1:]
    put(values, "Transactions", 3, id="ordinary")
    values["Mileage"] += mileage_values()["Mileage"][1:]
    # A recurring mixed pair retains one source-owned occurrence association.
    values["RecurringSchedules"].append(list(values["RecurringSchedules"][1]))
    put(values, "RecurringSchedules", 2, id="mixed-schedule", name="Synthetic mixed schedule",
        source_kind="mixed_use", total_expense="25.00", business_use_percentage="50",
        allocation_rationale="Synthetic allocation")
    provenance = dict(recurring_schedule_id="mixed-schedule", recurring_scheduled_date="2026-10-05",
                      recurring_source_kind="mixed_use", recurring_occurrence_type="initial")
    put(values, "Transactions", 1, **provenance)
    put(values, "MixedUseExpenses", 1, **provenance)
    docs = (document(profile, "file-mixed"), document(profile, "file-ordinary", verified=True),
            document(profile, "file-unreferenced"))
    mixed_ref = json.dumps([document_to_receipt_reference(docs[0])], separators=(",", ":"))
    put(values, "Transactions", 1, receipt_references=mixed_ref)
    put(values, "MixedUseExpenses", 1, receipt_references=mixed_ref)
    put(values, "Transactions", 3, receipt_references=json.dumps([document_to_receipt_reference(docs[1])]))
    # Transfers and income cross a year boundary without creating P&L transfers.
    values["Accounts"].append(list(values["Accounts"][1]))
    put(values, "Accounts", 3, id="bank", name="Synthetic child bank", parent_id="cash", opening_balance="7.25")
    values["Categories"].append(list(values["Categories"][1]))
    put(values, "Categories", 2, id="sales", name="Synthetic sales", kind="Income")
    values["Transactions"].append(list(core["Transactions"][1]))
    put(values, "Transactions", 4, id="income", txn_date="2025-12-31", kind="Income", amount="100.10",
        category_id="sales", recurring_schedule_id="", recurring_scheduled_date="", recurring_source_kind="",
        recurring_occurrence_type="")
    values["Transactions"].append(list(values["Transactions"][4]))
    put(values, "Transactions", 5, id="transfer", txn_date="2026-01-01", kind="Transfer", amount="20.00",
        to_account_id="bank", category_id="", payee_id="")
    snapshot = snapshot_from_values(Binding(profile, "workbook-" + profile, profile), values, extracted_at=WHEN)
    snapshot = enrich_snapshot(snapshot, entity_name="Synthetic " + profile, document_scope="folder-" + profile,
                               documents=docs, inventory_complete=True)
    return build_plan(snapshot), values, docs
