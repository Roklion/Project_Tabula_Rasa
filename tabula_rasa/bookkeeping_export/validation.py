"""Export-specific structural guards; accounting formulas retain domain owners."""

from collections import defaultdict
from decimal import Decimal, localcontext
import re

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.asset import ASSET_TYPES
from tabula_rasa.reference_data import ACCOUNT_TYPES, FIXED_TYPE_CLASSIFICATIONS
from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.mixed_use import validate_mixed_use_allocation, MixedUseAllocationError
from tabula_rasa.mixed_use_records import mixed_use_ledger_description


def require(condition, code="accounting"):
    if not condition:
        raise ExportError(code)


def _allocation(row):
    # The domain owner checks rounding. Do not expose its exceptions/row values.
    try:
        allocation = validate_mixed_use_allocation(row["total_expense"], row["business_use_percentage"])
    except (MixedUseAllocationError, ValueError, ArithmeticError):
        allocation = None
    require(allocation is not None)
    require(Decimal(row["allocated_amount"] if "allocated_amount" in row else row["amount"])
            == Decimal(allocation.allocated_amount))


def validate_bookkeeping(domains, indexes):
    with localcontext() as context:
        # SQL numeric(28,2) values must remain exact even when summed.
        context.prec = 60
        return _validate(domains, indexes)


def _validate(domains, indexes):
    diagnostics = []
    entries, categories = indexes["entries"], indexes["categories"]
    lines = defaultdict(list)
    for posting in domains["postings"]:
        require(posting["side"] in {"Debit", "Credit"} and Decimal(posting["amount"]) >= 0)
        require((posting["account_id"] is None) != (posting["category_id"] is None), "relationship")
        require(posting["projection_kind"] == entries[posting["entry_id"]]["projection_kind"], "relationship")
        lines[posting["entry_id"]].append(posting)
    tags = defaultdict(set)
    for row in domains["entry_tags"]:
        require(entries[row["entry_id"]]["projection_kind"] == "simple")
        tags[("entry", row["entry_id"])].add(row["tag_id"])
    for row in domains["mixed_use_tags"]:
        tags[("source", row["source_id"])].add(row["tag_id"])
    for entry in domains["entries"]:
        postings = sorted(lines[entry["id"]], key=lambda row: row["position"])
        require(len(postings) >= 2 and [row["position"] for row in postings] == list(range(1, len(postings) + 1)))
        require(sum((Decimal(row["amount"]) * (1 if row["side"] == "Debit" else -1) for row in postings), Decimal(0)) == 0)
        require(entry["projection_kind"] in {"simple", "journal"})
        if entry["projection_kind"] == "journal":
            require(entry["simple_kind"] is None and entry["payee_id"] is None and entry["reference"] == ""
                    and entry["mixed_use_source_id"] is None and entry["depreciation_asset_id"] is None)
            require(all(Decimal(row["amount"]) > 0 for row in postings))
            continue
        require(entry["simple_kind"] in {"Income", "Expense", "Transfer"} and len(postings) == 2)
        debit, credit = postings
        transaction = {"id": entry["id"], "kind": entry["simple_kind"], "amount": debit["amount"],
                       "account_id": debit["account_id"] if entry["simple_kind"] == "Income" else credit["account_id"],
                       "to_account_id": debit["account_id"] if entry["simple_kind"] == "Transfer" else "",
                       "category_id": debit["category_id"] or credit["category_id"]}
        expected = list(accounting_postings([transaction]))
        for actual, wanted in zip(postings, expected):
            require(actual["id"] == wanted["id"] and actual["side"] == wanted["side"]
                    and actual["amount"] == debit["amount"] and actual["payee_id"] is None and actual["description"] == ""
                    and (actual["account_id"] or actual["category_id"]) == wanted["target_id"]
                    and ("account" if actual["account_id"] else "category") == wanted["target_type"])
        if entry["simple_kind"] == "Transfer":
            require(debit["account_id"] != credit["account_id"])
        else:
            require(categories[transaction["category_id"]]["kind"] == entry["simple_kind"])
        require(not (entry["mixed_use_source_id"] and entry["depreciation_asset_id"]))
        if entry["mixed_use_source_id"] or entry["depreciation_asset_id"]:
            require(entry["simple_kind"] == "Expense")
        require(Decimal(debit["amount"]) > 0 or entry["depreciation_asset_id"] is not None)

    for row in domains["accounts"]:
        require(row["type"] in ACCOUNT_TYPES and FIXED_TYPE_CLASSIFICATIONS.get(row["type"], row["classification"]) == row["classification"])
    for name, field, allowed in (("accounts", "classification", {"Asset", "Liability", "Equity"}),
                                  ("categories", "kind", {"Income", "Expense"})):
        for row in domains[name]:
            require(row[field] in allowed)
            if row["parent_id"]:
                parent = indexes[name][row["parent_id"]]
                require(parent["parent_id"] is None and parent["id"] != row["id"] and row[field] == parent[field], "hierarchy")

    projections = defaultdict(list)
    for entry in domains["entries"]:
        if entry["mixed_use_source_id"]:
            projections[entry["mixed_use_source_id"]].append(entry)
    expected_ids = set()
    for position, source in enumerate(domains["mixed_use_sources"]):
        _allocation(source)
        require(categories[source["category_id"]]["kind"] == "Expense")
        require(source["expected_projection_entry_id"] not in expected_ids, "relationship")
        expected_ids.add(source["expected_projection_entry_id"])
        candidates = projections[source["id"]]
        state = source["relationship_state"]
        require(state in {"complete", "missing_projection", "projection_mismatch"} and len(candidates) <= 1, "relationship")
        if state == "missing_projection":
            require(not candidates, "relationship")
        else:
            require(len(candidates) == 1, "relationship")
            entry = candidates[0]
            debit, credit = sorted(lines[entry["id"]], key=lambda row: row["position"])
            matches = (entry["id"] == source["expected_projection_entry_id"]
                       and all(entry[field] == source[field] for field in ("txn_date", "payee_id", "reference"))
                       and entry["description"] == mixed_use_ledger_description(source["description"], source["allocation_rationale"])
                       and debit["category_id"] == source["category_id"] and credit["account_id"] == source["account_id"]
                       and debit["amount"] == source["allocated_amount"]
                       and tags[("entry", entry["id"])] == tags[("source", source["id"])])
            require(matches == (state == "complete"), "relationship")
        if state != "complete":
            diagnostics.append({"domain": "mixed_use_sources", "record": position, "code": state})

    for schedule in domains["recurring_schedules"]:
        require(schedule["source_kind"] in {"transaction", "mixed_use"} and schedule["status"] in {"active", "paused", "ended"})
        require(schedule["recurrence_unit"] in {"day", "week", "month", "year"} and schedule["recurrence_interval"] > 0)
        require(schedule["anchor_date"] == schedule["start_date"] and (
            schedule["end_date"] is None or schedule["end_date"] >= schedule["start_date"] or schedule["status"] == "ended"))
        require(Decimal(schedule["amount"]) > 0 and categories[schedule["category_id"]]["kind"] == "Expense")
        if schedule["source_kind"] == "mixed_use":
            require(schedule["total_expense"] is not None and schedule["business_use_percentage"] is not None
                    and bool(schedule["allocation_rationale"].strip()))
            _allocation(schedule)
        else:
            require(schedule["total_expense"] is None and schedule["business_use_percentage"] is None
                    and schedule["allocation_rationale"] == "")
    occurrence_owners = set()
    for row in domains["recurring_occurrences"]:
        schedule = indexes["recurring_schedules"][row["schedule_id"]]
        require(row["source_kind"] == schedule["source_kind"] and row["occurrence_type"] in {"initial", "generated"})
        require((row["entry_id"] is not None) == (row["source_kind"] == "transaction")
                and (row["mixed_use_source_id"] is not None) == (row["source_kind"] == "mixed_use"), "relationship")
        owner = (row["entry_id"], row["mixed_use_source_id"])
        require(owner not in occurrence_owners, "relationship")
        occurrence_owners.add(owner)
        if row["entry_id"]:
            entry = entries[row["entry_id"]]
            require(entry["projection_kind"] == "simple" and entry["simple_kind"] == "Expense"
                    and entry["mixed_use_source_id"] is None and entry["depreciation_asset_id"] is None)
        else:
            require(indexes["mixed_use_sources"][row["mixed_use_source_id"]]["relationship_state"] == "complete")

    event_entries = set()
    for row in domains["depreciation_events"]:
        entry, asset = entries[row["entry_id"]], indexes["fixed_assets"][row["asset_id"]]
        require(row["sequence"] > 0 and row["sequence"] <= asset["useful_life_quarters"] and row["entry_id"] not in event_entries)
        event_entries.add(row["entry_id"])
        require(asset["retired_date"] is None or row["scheduled_date"] <= asset["retired_date"])
        debit, credit = sorted(lines[entry["id"]], key=lambda row: row["position"])
        require(entry["depreciation_asset_id"] == row["asset_id"] and entry["txn_date"] == row["scheduled_date"]
                and debit["amount"] == row["amount"] and debit["category_id"] == asset["expense_category_id"]
                and credit["account_id"] == asset["accumulated_depreciation_account_id"])
    require({row["id"] for row in domains["entries"] if row["depreciation_asset_id"]} == event_entries, "relationship")
    for asset in domains["fixed_assets"]:
        require(asset["asset_type"] in ASSET_TYPES)
        if asset["accumulated_depreciation_account_id"]:
            offset = indexes["accounts"][asset["accumulated_depreciation_account_id"]]
            require(offset["type"] == "Other" and offset["classification"] == "Asset")
        require(Decimal(asset["cost_basis"]) > Decimal(asset["salvage_value"]) >= 0
                and asset["useful_life_quarters"] > 0 and asset["depreciation_method"] == "Straight-line")
        require(asset["depreciation_start_date"] >= asset["acquisition_date"])
        require((asset["status"] == "active" and asset["retired_date"] is None) or
                (asset["status"] == "retired" and asset["retired_date"] is not None and asset["retired_date"] >= asset["acquisition_date"]))
        if asset["expense_category_id"]:
            require(categories[asset["expense_category_id"]]["kind"] == "Expense")
        if asset["source_entry_id"]:
            require(entries[asset["source_entry_id"]]["projection_kind"] == "simple")
    for row in domains["asset_period_overrides"]:
        require(0 < row["sequence"] <= indexes["fixed_assets"][row["asset_id"]]["useful_life_quarters"]
                and Decimal(row["amount"]) >= 0 and bool(row["reason"].strip()))

    link_positions = defaultdict(list)
    for row in domains["document_links"]:
        require((row["entry_id"] is None) != (row["mixed_use_source_id"] is None), "relationship")
        if row["entry_id"]:
            entry = entries[row["entry_id"]]
            require(entry["projection_kind"] == "simple" and entry["mixed_use_source_id"] is None, "relationship")
        link_positions[(row["entry_id"], row["mixed_use_source_id"])].append(row["position"])
    for positions in link_positions.values():
        require(sorted(positions) == list(range(1, len(positions) + 1)) and len(positions) <= 100, "relationship")
    for row in domains["documents"]:
        require(bool(row["store_kind"].strip()) and bool(row["storage_key"].strip()) and bool(row["stored_filename"].strip()))
        require(row["byte_size"] is None or row["byte_size"] >= 0)
        require(row["sha256"] is None or bool(re.fullmatch("[0-9a-f]{64}", row["sha256"])))
    require(len({row["insertion_order"] for row in domains["mileage_records"]}) == len(domains["mileage_records"]), "relationship")
    for row in domains["mileage_records"]:
        require(Decimal(row["miles"]) > 0 and row["insertion_order"] > 0)
    for row in domains["import_records"]:
        require(row["source_position"] > 0 and bool(row["fingerprint"].strip()))
        require((row["record_kind"] == "entry" and row["entry_id"] is not None and row["mileage_id"] is None)
                or (row["record_kind"] == "mileage" and row["mileage_id"] is not None and row["entry_id"] is None), "relationship")
        if row["entry_id"]:
            require(entries[row["entry_id"]]["projection_kind"] == "simple")
    for row in domains["import_batches"]:
        require(row["source_kind"] in {"csv", "quickbooks"} and row["status"] in {"prepared", "complete", "failed"})
    for row in domains["migration_units"]:
        require(bool(re.fullmatch("[0-9a-f]{64}", row["unit_sha256"])), "provenance")
        require(row["status"] in {"pending", "loaded", "failed"} and (row["status"] == "loaded") == (row["loaded_at"] is not None))
    for row in domains["migration_runs"]:
        require(bool(re.fullmatch("[0-9a-f]{64}", row["source_snapshot_sha256"])), "provenance")
        require((row["source_kind"] == "current_workbook" and row["source_backup_version"] is None)
                or (row["source_kind"] == "v13_backup" and row["source_backup_version"] == 13), "provenance")
        require(row["status"] in {"prepared", "loading", "failed", "validated"})
    # Migration maps deliberately outlive deletion of their target records.
    targets = {"account": "accounts", "category": "categories", "payee": "payees", "tag": "tags", "entry": "entries",
               "mixed_use": "mixed_use_sources", "schedule": "recurring_schedules", "asset": "fixed_assets", "mileage": "mileage_records"}
    journal_ids = {row["id"] for row in domains["postings"] if row["projection_kind"] == "journal"}
    for position, row in enumerate(domains["migration_id_mappings"]):
        kind = row["target_record_kind"]
        require(kind in targets or kind == "journal_posting", "unsupported_provenance")
        present = row["target_id"] in (journal_ids if kind == "journal_posting" else indexes[targets[kind]])
        if not present:
            diagnostics.append({"domain": "migration_id_mappings", "record": position, "code": "historical_target_absent"})
    return diagnostics
