"""Read migration meaning through the shipped repository projections."""

from sqlalchemy import text

from tabula_rasa.migration.model import digest
from tabula_rasa.migration.reconciliation import mismatched_fields
from tabula_rasa.storage.google_sheets.schema import WORKSHEET_HEADERS
from .accounting import PostgresTransactionRepository, PostgresJournalRepository
from .assets import PostgresAssetRepository
from .mixed_use import PostgresMixedUseRepository
from .mileage import PostgresMileageRepository
from .recurring import PostgresRecurringRepository
from .reference_data import reference_record
from .repository import serialized

TABLES = dict(Accounts="accounts", Categories="categories", Payees="payees", Tags="tags",
              Transactions="entries", JournalEntries="entries", MixedUseExpenses="mixed_use_sources",
              RecurringSchedules="recurring_schedules", Assets="fixed_assets", Mileage="mileage_records",
              Documents="documents")


def source_projection(connection, scope, title, row):
    if title in {"Accounts", "Categories", "Payees", "Tags"}:
        return reference_record(row, TABLES[title])
    if title == "Transactions":
        return PostgresTransactionRepository(None, scope).project(connection, row)
    if title == "JournalEntries":
        return PostgresJournalRepository(None, scope).project(connection, row)
    if title == "MixedUseExpenses":
        return PostgresMixedUseRepository(None, scope).project(connection, row)
    if title == "Assets":
        return PostgresAssetRepository(None, scope).project(connection, row)
    if title == "Mileage":
        return PostgresMileageRepository(None, scope).project(connection, row).as_record()
    if title == "RecurringSchedules":
        return PostgresRecurringRepository(None, scope, transactions=None, mixed_use=None).project(connection, row)
    return {field: serialized(value) for field, value in row.items()}


def unit_differences(connection, plan, unit):
    scope = plan.snapshot.binding.entity_id
    differences = []
    for title, records in unit.rows.items():
        if title == "JournalPostings":
            continue
        for source in records:
            source_id = source["storage_key"] if title == "Documents" else source["id"]
            identity = plan.target_id(title, source_id)
            extra = " AND projection_kind=:projection" if title in {"Transactions", "JournalEntries"} else ""
            row = connection.execute(text(f"SELECT * FROM {TABLES[title]} WHERE entity_id=:scope AND id=:id{extra}"),
                                     dict(scope=scope, id=identity, projection="simple" if title == "Transactions" else "journal")).mappings().first()
            fields = ["missing_record"]
            if row is not None:
                actual = source_projection(connection, scope, title, row)
                if title == "Documents":
                    expected = {**source["metadata"], "id": identity, "storage_key": source["storage_key"],
                                "open_url": source["open_url"], "store_kind": "google_drive",
                                "store_scope_key": plan.snapshot.metadata["document_scope"],
                                "created_at": source["created_at"]}
                    expected.pop("document_id")
                    # Unknown checksum is SQL NULL, never an invented verified fact.
                    fields = mismatched_fields(actual, expected)
                else:
                    expected = {field: source[field] for field in WORKSHEET_HEADERS[title] if field != "updated_at"}
                    expected["id"] = identity
                    fields = mismatched_fields(actual, expected)
                if title == "JournalEntries":
                    postings = sorted(unit.rows["JournalPostings"], key=lambda line: int(line["position"]))
                    if len(postings) != len(actual["postings"]):
                        fields.append("posting_count")
                    else:
                        for wanted, found in zip(postings, actual["postings"]):
                            expected_line = {**wanted, "parent_entry_id": identity}
                            fields.extend("postings." + field for field in mismatched_fields(
                                {**found, "parent_entry_id": identity}, expected_line))
                if title == "Assets":
                    events = connection.execute(text("SELECT sequence,entry_id,scheduled_date,amount FROM depreciation_events "
                                                     "WHERE entity_id=:scope AND asset_id=:id ORDER BY sequence"),
                                                dict(scope=scope, id=identity)).all()
                    from tabula_rasa.depreciation_posting import asset_schedule, depreciation_entry_id
                    periods = {depreciation_entry_id(source["id"], period.sequence): period for period in asset_schedule(source)}
                    wanted = sorted((periods[entry["id"]].sequence, plan.target_id("Transactions", entry["id"]),
                                     periods[entry["id"]].scheduled_date, periods[entry["id"]].depreciation_amount)
                                    for entry in unit.rows["Transactions"])
                    if list(events) != wanted:
                        fields.append("depreciation_events")
                if title == "MixedUseExpenses" and row["relationship_state"] != "complete":
                    fields.append("relationship_state")
            if fields:
                differences.append(dict(domain=title, record_key=digest([title, source_id]),
                                        fields=sorted(set(fields))))
    return differences
