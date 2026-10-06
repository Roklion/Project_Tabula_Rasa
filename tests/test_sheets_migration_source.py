"""Synthetic live workbook preflight, mappings and dependency planning."""

from copy import deepcopy
import json

import pytest

from tabula_rasa.migration.model import Binding, MigrationError
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.infrastructure.sheets_migration import extract_workbook, snapshot_from_values
from tabula_rasa.storage.google_sheets.schema import WORKSHEET_HEADERS
from tabula_rasa.depreciation_posting import asset_schedule, depreciation_entry_id
from tabula_rasa.mixed_use_records import mixed_use_ledger_description
from tabula_rasa.recurrence import occurrence_id

WHEN = "2026-10-05T00:00:00Z"


def values_with_records(*, recurring=False, journal=False):
    values = {title: [list(fields)] for title, fields in WORKSHEET_HEADERS.items()}

    def add(title, **row):
        values[title].append([str(row.get(field, "")) for field in WORKSHEET_HEADERS[title]])

    add("Accounts", id="cash", name="Synthetic cash", type="Bank", classification="Asset",
        opening_balance="-12.50", active="FALSE", created_at=WHEN)
    add("Categories", id="office", name="Synthetic office", kind="Expense")
    add("Payees", id="vendor", name="Synthetic vendor", active="FALSE", created_at=WHEN)
    add("Tags", id="job", name="Synthetic job", active="FALSE", created_at=WHEN)
    provenance = {}
    if recurring:
        add("RecurringSchedules", id="schedule", name="Synthetic schedule", kind="Expense", source_kind="transaction",
            recurrence_unit="month", recurrence_interval="1", anchor_date="2026-10-05", start_date="2026-10-05",
            status="paused", amount="12.50", account_id="cash", category_id="office", payee_id="vendor",
            tag_ids='["job"]', created_at=WHEN, updated_at=WHEN)
        provenance = dict(recurring_schedule_id="schedule", recurring_scheduled_date="2026-10-05",
                          recurring_source_kind="transaction", recurring_occurrence_type="initial")
    add("Transactions", id="entry", txn_date="2026-10-05", kind="Expense", amount="12.50",
        account_id="cash", category_id="office", payee_id="vendor", tag_ids='["job"]',
        created_at=WHEN, description="Private synthetic ledger narrative", **provenance)
    if journal:
        add("JournalEntries", id="entry", txn_date="2026-10-05", description="Synthetic journal", created_at=WHEN, updated_at=WHEN)
        for identity, target, side in (("debit", "category", "Debit"), ("credit", "account", "Credit")):
            add("JournalPostings", id=identity, parent_entry_id="entry", position="1" if side == "Debit" else "2",
                target_type=target, target_id="office" if target == "category" else "cash", side=side, amount="5.00")
    return values


def plan_for(values=None, *, profile="alpha", entity="alpha", workbook="workbook-alpha"):
    return build_plan(snapshot_from_values(Binding(profile, workbook, entity),
                                          values or values_with_records(), extracted_at=WHEN))


class ReadOnlyWorkbook:
    def __init__(self, values, identity="workbook-alpha"):
        self.id = identity
        self.values = values
        self.reads = []

    def worksheets(self):
        owner = self

        class Sheet:
            def __init__(self, title):
                self.title = title

            def get_all_values(self):
                owner.reads.append(self.title)
                return deepcopy(owner.values[self.title])

        return [Sheet(title) for title in self.values]


def test_live_source_read_only_shared_headers_exact_reordering_and_private_snapshot():
    original = values_with_records(recurring=True, journal=True)
    reordered = {title: [list(reversed(row)) for row in rows] for title, rows in original.items()}
    source = ReadOnlyWorkbook(reordered)
    snapshot = extract_workbook(source, Binding("alpha", source.id, "alpha"), extracted_at=WHEN)
    plan = build_plan(snapshot)
    assert source.reads == list(WORKSHEET_HEADERS)
    assert plan == plan_for(original)
    assert "Private synthetic" not in repr(snapshot) + repr(plan) + repr(plan.units)
    assert "Private synthetic" not in json.dumps(plan.report())
    original["Transactions"][1][3] = "99.00"
    assert snapshot.tables["Transactions"][0]["amount"] == "12.50"
    decoded = snapshot.tables
    decoded["Transactions"].clear()
    assert len(snapshot.tables["Transactions"]) == 1


@pytest.mark.parametrize("change", ["missing", "additional", "retired", "duplicate", "missing_sheet", "overwide"])
def test_unsupported_format_and_extra_cells_fail_without_writes(change):
    values = values_with_records()
    if change == "missing":
        values["Transactions"][0].pop()
    elif change == "additional":
        values["Transactions"][0].append("future_field")
    elif change == "retired":
        values["Transactions"][0][7] = "payee"
    elif change == "duplicate":
        values["Transactions"][0][-1] = "id"
    elif change == "missing_sheet":
        del values["Assets"]
    else:
        values["Transactions"][1].append("private unsupported content")
    with pytest.raises(MigrationError) as caught:
        extract_workbook(ReadOnlyWorkbook(values), Binding("alpha", "workbook-alpha", "alpha"))
    assert "private unsupported content" not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("title,field,value", [
    ("Transactions", "amount", "-1"), ("Transactions", "category_id", "foreign"),
    ("Transactions", "source_type", "unknown"), ("Transactions", "recurring_schedule_id", "missing"),
    ("Transactions", "receipt_references", "private malformed JSON"),
    ("Accounts", "classification", "invalid"), ("Accounts", "created_at", "not a timestamp"),
    ("JournalPostings", "amount", "6.00"),
])
def test_domain_reference_provenance_failures_are_safe_before_target_access(title, field, value):
    values = values_with_records(journal=True)
    values[title][1][values[title][0].index(field)] = value
    with pytest.raises(MigrationError) as caught:
        plan_for(values)
    assert value not in str(caught.value) if value.startswith("private") else True
    assert "Private synthetic ledger narrative" not in str(caught.value)
    assert caught.value.__context__ is None


def test_collision_mapping_reproducible_namespaces_and_two_profile_binding():
    values = values_with_records(recurring=True, journal=True)
    first = plan_for(values)
    assert first.target_id("Transactions", "entry") == "entry"
    assert first.target_id("JournalEntries", "entry") != "entry"
    second = build_plan(snapshot_from_values(first.snapshot.binding, values, extracted_at="2026-10-06T00:00:00Z"))
    assert first.run_id == second.run_id
    assert first.mappings == second.mappings
    beta = plan_for(values, profile="beta", entity="beta", workbook="workbook-beta")
    assert first.run_id != beta.run_id
    assert first.target_id("JournalEntries", "entry") != beta.target_id("JournalEntries", "entry")
    order = {unit.key: index for index, unit in enumerate(first.units)}
    assert [unit.kind for unit in first.units].index("schedule") < [unit.kind for unit in first.units].index("recurring_entry")
    assert all(order[dependency] < order[unit.key] for unit in first.units for dependency in unit.dependencies)
    assert first.report()["cutover_authorized"] is False


def test_duplicate_ids_missing_owner_and_wrong_workbook_are_rejected():
    values = values_with_records()
    values["Transactions"].append(deepcopy(values["Transactions"][1]))
    with pytest.raises(MigrationError, match="duplicate identity"):
        plan_for(values)
    with pytest.raises(MigrationError, match="explicit binding"):
        extract_workbook(ReadOnlyWorkbook(values, "foreign"), Binding("alpha", "workbook-alpha", "alpha"))


def test_empty_final_format_is_valid_but_empty_uninitialized_source_is_not():
    assert len(plan_for({title: [list(fields)] for title, fields in WORKSHEET_HEADERS.items()}).units) == 1
    with pytest.raises(MigrationError, match="format 13"):
        snapshot_from_values(Binding("alpha", "workbook-alpha", "alpha"), {})


def values_with_mixed_asset_history():
    values = values_with_records()
    transaction = dict(zip(values["Transactions"][0], values["Transactions"][1]))
    transaction.update(source_type="mixed_use_expense", source_id="mixed",
                       description=mixed_use_ledger_description("Synthetic mixed cost", "Synthetic allocation"))
    source = {**transaction, "id": "mixed", "description": "Synthetic mixed cost", "total_expense": "25.00",
              "business_use_percentage": "50", "allocated_amount": "12.50", "linked_transaction_id": "entry",
              "allocation_rationale": "Synthetic allocation"}
    values["Transactions"][1] = [transaction.get(field, "") for field in WORKSHEET_HEADERS["Transactions"]]
    values["MixedUseExpenses"].append([source.get(field, "") for field in WORKSHEET_HEADERS["MixedUseExpenses"]])
    account = dict(id="contra", name="Synthetic accumulated depreciation", type="Other", classification="Asset",
                   active="TRUE", created_at=WHEN, opening_balance="0.00")
    values["Accounts"].append([account.get(field, "") for field in WORKSHEET_HEADERS["Accounts"]])
    asset = dict(id="asset", name="Synthetic equipment", asset_type="Computers & office equipment",
                 acquisition_date="2026-10-05", depreciation_start_date="2026-10-05", cost_basis="100.00", salvage_value="0.00",
                 useful_life_quarters="4", depreciation_method="Straight-line", status="active", source_transaction_id="entry",
                 depreciation_expense_account_id="office", accumulated_depreciation_account_id="contra",
                 created_at=WHEN, updated_at=WHEN, schedule_overrides="{}", tag_ids='["job"]')
    period = asset_schedule(asset)[0]
    depreciation = {**transaction, "id": depreciation_entry_id("asset", 1), "source_type": "depreciation", "source_id": "asset",
                    "account_id": "contra", "amount": str(period.depreciation_amount), "txn_date": period.scheduled_date.isoformat()}
    values["Transactions"].append([depreciation.get(field, "") for field in WORKSHEET_HEADERS["Transactions"]])
    values["Assets"].append([asset.get(field, "") for field in WORKSHEET_HEADERS["Assets"]])
    return values


def test_source_owned_mixed_acquisition_precedes_asset_and_existing_history_is_not_regenerated():
    plan = plan_for(values_with_mixed_asset_history())
    kinds = [unit.kind for unit in plan.units]
    assert kinds == ["foundation", "mixed_pair", "asset_history"]
    mixed, asset = plan.units[1:]
    assert mixed.key in asset.dependencies
    assert len(mixed.rows["Transactions"]) == len(asset.rows["Transactions"]) == 1
    assert mixed.rows["Transactions"][0]["id"] == "entry"
    assert asset.rows["Transactions"][0]["id"] == depreciation_entry_id("asset", 1)
    assert plan.report({"foundation"})["missing_loaders"] == ["asset_history", "mixed_pair"]


def test_source_owned_dependency_cycle_is_reported_before_loading():
    values = values_with_mixed_asset_history()
    values["Assets"][1][values["Assets"][0].index("source_transaction_id")] = depreciation_entry_id("asset", 1)
    with pytest.raises(MigrationError, match="dependency cycle"):
        plan_for(values)


def test_generated_identity_is_validated_without_replaying_schedule():
    values = values_with_records(recurring=True)
    fields = values["Transactions"][0]
    values["Transactions"][1][fields.index("recurring_occurrence_type")] = "generated"
    with pytest.raises(MigrationError, match="provenance"):
        plan_for(values)
    identity = occurrence_id("schedule", "2026-10-05", "generated")
    values["Transactions"][1][fields.index("id")] = identity
    assert plan_for(values).target_id("Transactions", identity) == identity


@pytest.mark.parametrize("kind", ["expense", " Expense "])
def test_transaction_kind_uses_canonical_domain_normalization(kind):
    values = values_with_records()
    values["Transactions"][1][values["Transactions"][0].index("kind")] = kind
    assert plan_for(values) == plan_for()


def test_schedule_interval_target_integer_boundary_is_validated_before_planning():
    values = values_with_records(recurring=True)
    index = values["RecurringSchedules"][0].index("recurrence_interval")
    values["RecurringSchedules"][1][index] = "2147483647"
    assert plan_for(values).snapshot.tables["RecurringSchedules"][0]["recurrence_interval"] == "2147483647"
    values["RecurringSchedules"][1][index] = "2147483648"
    with pytest.raises(MigrationError, match="Source domain/reference/provenance") as caught:
        plan_for(values)
    assert caught.value.__context__ is None


def values_with_transfer(kind, category=""):
    values = values_with_records()
    account = dict(zip(values["Accounts"][0], values["Accounts"][1]))
    account.update(id="destination", name="Synthetic destination")
    values["Accounts"].append([account[field] for field in values["Accounts"][0]])
    fields = values["Transactions"][0]
    for field, value in (("kind", kind), ("category_id", category), ("to_account_id", "destination"), ("payee_id", "")):
        values["Transactions"][1][fields.index(field)] = value
    return values


@pytest.mark.parametrize("kind", ["Transfer", "transfer", " transfer "])
def test_transfer_category_guard_uses_canonical_kind(kind):
    assert plan_for(values_with_transfer(kind)) == plan_for(values_with_transfer("Transfer"))
    with pytest.raises(MigrationError, match="invalid domain or reference"):
        plan_for(values_with_transfer(kind, "office"))
