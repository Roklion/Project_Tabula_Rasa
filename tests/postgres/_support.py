"""Synthetic records; never load profiles or application secrets."""

from sqlalchemy import text


def entity(connection, scope="alpha"):
    connection.execute(text("INSERT INTO business_entities(id,name,incarnation_id) VALUES (:id,:id,:id)"), {"id": scope})


def account(connection, scope="alpha", account_id="cash", *, parent=None, classification="Asset"):
    connection.execute(text("""INSERT INTO accounts(entity_id,id,name,name_key,type,classification,incarnation_id,parent_id)
        VALUES (:scope,:id,:id,:id,'Other',:classification,:id,:parent)"""),
        {"scope": scope, "id": account_id, "classification": classification, "parent": parent})


def category(connection, scope="alpha", category_id="sales", *, kind="Income"):
    connection.execute(text("""INSERT INTO categories(entity_id,id,name,name_key,kind,incarnation_id)
        VALUES (:scope,:id,:id,:id,:kind,:id)"""), {"scope": scope, "id": category_id, "kind": kind})


def simple_entry(connection, scope="alpha", entry_id="income", *, amount="10.00", category_id="sales"):
    connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,simple_kind)
        VALUES (:scope,:id,:id,'2026-10-05','simple','Income')"""), {"scope": scope, "id": entry_id})
    connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
        VALUES (:scope,:id||chr(58)||'1',:id,'simple',1,'Debit',:amount,'cash',NULL),
               (:scope,:id||chr(58)||'2',:id,'simple',2,'Credit',:amount,NULL,:category)"""),
        {"scope": scope, "id": entry_id, "amount": amount, "category": category_id})


def ledger(connection):
    entity(connection)
    account(connection)
    category(connection)


def load_baseline(database, key):
    from tabula_rasa.infrastructure.postgres.concurrency import AGGREGATE_TABLES, baseline_for
    from tabula_rasa.infrastructure.postgres.operations import repository_operation
    with repository_operation(database, read_only=True) as connection:
        row = connection.execute(text(
            f"SELECT * FROM {AGGREGATE_TABLES[key.kind]} WHERE entity_id=:scope AND id=:id",
        ), {"scope": key.entity_id, "id": key.record_id}).mappings().one()
        return baseline_for(key, row)


def expense_references(connection, scope="alpha"):
    entity(connection, scope)
    account(connection, scope)
    category(connection, scope, "expense", kind="Expense")


def expense_entry(connection, scope="alpha", identity="expense", *, amount="10", date="2026-10-05", owner=None, mixed_owner=None):
    connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,
        simple_kind,depreciation_asset_id,mixed_use_source_id)
        VALUES (:scope,:id,:id,:date,'simple','Expense',:owner,:mixed)"""),
        {"scope": scope, "id": identity, "date": date, "owner": owner, "mixed": mixed_owner})
    connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,
        amount,account_id,category_id) VALUES
        (:scope,:id||chr(58)||'1',:id,'simple',1,'Debit',:amount,NULL,'expense'),
        (:scope,:id||chr(58)||'2',:id,'simple',2,'Credit',:amount,'cash',NULL)"""),
        {"scope": scope, "id": identity, "amount": amount})


def mixed_pair(connection, scope="alpha", *, state="complete"):
    connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,
        total_expense,business_use_percentage,allocated_amount,account_id,category_id,
        allocation_rationale,expected_projection_entry_id,relationship_state)
        VALUES (:scope,'source','source','2026-10-05',100,50,50,'cash','expense','Synthetic','projection',:state)"""),
        {"scope": scope, "state": state})
    if state == "missing_projection":
        return
    expense_entry(connection, scope, "projection", amount="50", mixed_owner="source")
    connection.execute(text("""UPDATE entries SET description=:description
        WHERE entity_id=:scope AND id='projection'"""),
        {"scope": scope, "description": "Allocation rationale: Synthetic" if state == "complete" else "Mismatched"})


def schedule(connection, scope="alpha", identity="schedule", *, source_kind="transaction"):
    connection.execute(text("""INSERT INTO recurring_schedules(entity_id,id,incarnation_id,name,source_kind,
        recurrence_unit,recurrence_interval,anchor_date,start_date,status,amount,account_id,category_id,
        total_expense,business_use_percentage,allocation_rationale)
        VALUES (:scope,:id,:id,:id,:kind,'day',1,'2026-10-01','2026-10-01','active',10,'cash','expense',
        :total,:percentage,:rationale)"""), {"scope": scope, "id": identity, "kind": source_kind,
        "total": 100 if source_kind == "mixed_use" else None,
        "percentage": 10 if source_kind == "mixed_use" else None,
        "rationale": "Synthetic" if source_kind == "mixed_use" else ""})


def asset(connection, scope="alpha", *, posted=False, override=False):
    connection.execute(text("""INSERT INTO fixed_assets(entity_id,id,incarnation_id,name,asset_type,
        acquisition_date,depreciation_start_date,cost_basis,salvage_value,useful_life_quarters,
        depreciation_method,expense_category_id,accumulated_depreciation_account_id,status)
        VALUES (:scope,'asset','asset','Synthetic','Other depreciable property','2026-01-01',
        '2026-01-01',100,0,4,'Straight-line','expense','cash','active')"""), {"scope": scope})
    if override:
        connection.execute(text("""INSERT INTO asset_period_overrides(entity_id,asset_id,sequence,amount,reason)
            VALUES (:scope,'asset',1,10,'Synthetic')"""), {"scope": scope})
    if posted:
        expense_entry(connection, scope, "depreciation", amount="25", date="2026-03-31", owner="asset")
        connection.execute(text("""INSERT INTO depreciation_events(entity_id,asset_id,sequence,entry_id,
            scheduled_date,amount) VALUES (:scope,'asset',1,'depreciation','2026-03-31',25)"""), {"scope": scope})
