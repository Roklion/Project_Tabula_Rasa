"""Dependency-complete units shared by future core/secondary loaders."""

import json

from tabula_rasa.ledger_validation import decode_receipt_references

from .model import IdMapping, MigrationError, Plan, Unit, digest, stable_id

TARGET_KINDS = {
    "Accounts": "account", "Categories": "category", "Payees": "payee", "Tags": "tag",
    "Transactions": "entry", "JournalEntries": "entry", "JournalPostings": "journal_posting",
    "MixedUseExpenses": "mixed_use", "RecurringSchedules": "schedule",
    "Assets": "asset", "Mileage": "mileage",
}


def _key(kind, identity):
    return kind + ":" + digest(identity)


def build_plan(snapshot):
    tables = snapshot.tables
    mappings = []
    reserved = {row["id"] for title in ("Transactions", "JournalEntries") for row in tables[title]}
    transaction_ids = {row["id"] for row in tables["Transactions"]}
    for title in sorted(tables):
        for row in tables[title]:
            target, reason = row["id"], "preserved"
            if title == "JournalEntries" and target in transaction_ids:
                sequence = 0
                while True:
                    binding = snapshot.binding
                    target = stable_id("journal-entry-collision", binding.profile_key,
                                       binding.workbook_key, binding.entity_id, row["id"], sequence)
                    if target not in reserved:
                        break
                    sequence += 1
                reserved.add(target)
                reason = "simple_journal_entry_namespace_collision"
            mappings.append(IdMapping(title, row["id"], TARGET_KINDS[title], target, reason, row.get("updated_at") or None))

    units = []

    def add(key, kind, rows, dependencies=("foundation",)):
        units.append(Unit(key, kind, tuple(sorted(set(dependencies))),
                          json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))))

    add("foundation", "foundation", {title: tables[title] for title in
                                     ("Accounts", "Categories", "Payees", "Tags")}, ())
    for row in tables["RecurringSchedules"]:
        add(_key("schedule", row["id"]), "schedule", {"RecurringSchedules": [row]})
    owners = {}
    for row in tables["Transactions"]:
        source = row["source_type"]
        if source == "mixed_use_expense":
            owners[row["id"]] = _key("mixed_pair", row["source_id"])
        elif source == "depreciation":
            owners[row["id"]] = _key("asset_history", row["source_id"])
        else:
            kind = "recurring_entry" if row["recurring_schedule_id"] else "simple_entry"
            if decode_receipt_references(row["receipt_references"]):
                kind += "_receipts"
            key = owners[row["id"]] = _key("entry", row["id"])
            dependencies = ["foundation"]
            if row["recurring_schedule_id"]:
                dependencies.append(_key("schedule", row["recurring_schedule_id"]))
            add(key, kind, {"Transactions": [row]}, dependencies)
    for source in tables["MixedUseExpenses"]:
        entries = [row for row in tables["Transactions"]
                   if row["source_type"] == "mixed_use_expense" and row["source_id"] == source["id"]]
        dependencies = ["foundation"]
        if source["recurring_schedule_id"]:
            dependencies.append(_key("schedule", source["recurring_schedule_id"]))
        add(_key("mixed_pair", source["id"]), "mixed_pair",
            {"MixedUseExpenses": [source], "Transactions": entries}, dependencies)
    for asset in tables["Assets"]:
        dependencies = ["foundation"]
        acquisition = asset["source_transaction_id"]
        if acquisition in owners:
            dependencies.append(owners[acquisition])
        add(_key("asset_history", asset["id"]), "asset_history",
            {"Assets": [asset], "Transactions": [row for row in tables["Transactions"]
             if row["source_type"] == "depreciation" and row["source_id"] == asset["id"]]}, dependencies)
    for row in tables["JournalEntries"]:
        add(_key("journal", row["id"]), "journal", {"JournalEntries": [row],
            "JournalPostings": [line for line in tables["JournalPostings"] if line["parent_entry_id"] == row["id"]]})
    for row in tables["Mileage"]:
        add(_key("mileage", row["id"]), "mileage", {"Mileage": [row]})

    ordered = []
    pending = {unit.key: unit for unit in units}
    complete = set()
    while pending:
        available = sorted(key for key, unit in pending.items() if set(unit.dependencies) <= complete)
        if not available:
            raise MigrationError("Source migration units contain a dependency cycle or missing owner.")
        for key in available:
            ordered.append(pending.pop(key))
            complete.add(key)
    # Every source row belongs to exactly one unit, including source-owned entries.
    actual = [(title, row["id"]) for unit in ordered for title, rows in unit.rows.items() for row in rows]
    expected = {(title, row["id"]) for title, rows in tables.items() for row in rows}
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise MigrationError("Source records are missing or multiply owned in the migration plan.")
    return Plan(snapshot, tuple(ordered), tuple(mappings))
