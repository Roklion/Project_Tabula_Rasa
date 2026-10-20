"""Native mutation-baseline contract probes, not deployable domain repositories.

Only the exercised create/snapshot/attention ports are implemented. Domain
preparation and reconciliation use the real services; SQL stores their outputs.
The domain adapter slices must run equivalent cases through their full ports.
"""

from datetime import date, datetime

from sqlalchemy import text

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.application.recurring_contracts import RecurringSnapshot
from tabula_rasa.infrastructure.postgres.concurrency import AggregateKey, baseline_for
from tabula_rasa.infrastructure.postgres.operations import repository_operation
from tabula_rasa.reference_data import normalize_tag_ids
from tabula_rasa.transaction import TransactionReferences


def record(row):
    return {key: "" if value is None else value.isoformat() if isinstance(value, (date, datetime))
            else str(value) for key, value in row.items()}


def references(connection, scope):
    collections = []
    for table in ("accounts", "categories", "payees", "tags"):
        rows = connection.execute(text(f"SELECT * FROM {table} WHERE entity_id=:scope"), {"scope": scope}).mappings()
        collections.append({row["id"]: record(row) for row in rows})
    return TransactionReferences(*collections)


class ReferenceProbe:
    def __init__(self, database, scope, table):
        assert table in {"payees", "tags"}
        self.database, self.scope, self.table = database, scope, table

    def create(self, name, *, active=True):
        identity = name.casefold().replace(" ", "-")
        with repository_operation(self.database) as connection:
            row = connection.execute(text(f"""INSERT INTO {self.table}(entity_id,id,incarnation_id,name,name_key,active)
                VALUES (:scope,:id,:id,:name,:key,:active) RETURNING *"""),
                {"scope": self.scope, "id": identity, "name": name, "key": name.casefold(), "active": active}).mappings().one()
        return record(row)


class TransactionProbe:
    def __init__(self, database, scope, *, fail_occurrence=None):
        self.database, self.scope = database, scope
        self.fail_occurrence = fail_occurrence

    def create(self, identity, *, build):
        with repository_operation(self.database, require_outer=True) as connection:
            prepared = build(references(connection, self.scope), None)
            connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,
                simple_kind,description,reference,payee_id,created_at)
                VALUES (:scope,:id,:id,:txn_date,'simple',:kind,:description,:reference,:payee,:created_at)"""),
                {**prepared, "scope": self.scope, "payee": prepared["payee_id"] or None})
            for line in accounting_postings([prepared]):
                connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,
                    amount,account_id,category_id) VALUES (:scope,:id,:entry,'simple',:position,:side,:amount,:account,:category)"""),
                    {**line, "scope": self.scope, "entry": identity, "position": int(line["id"].rsplit(":", 1)[1]),
                     "account": line["target_id"] if line["target_type"] == "account" else None,
                     "category": line["target_id"] if line["target_type"] == "category" else None})
            for tag in normalize_tag_ids(prepared["tag_ids"]):
                connection.execute(text("INSERT INTO entry_tags VALUES (:scope,:id,:tag)"),
                                   {"scope": self.scope, "id": identity, "tag": tag})
            schedule = prepared.get("recurring_schedule_id")
            if schedule:
                connection.execute(text("""INSERT INTO recurring_occurrences(entity_id,schedule_id,scheduled_date,
                    source_kind,occurrence_type,entry_id)
                    VALUES (:scope,:schedule,:date,:kind,:role,:entry)"""),
                    {"scope": self.scope, "schedule": schedule, "date": prepared["recurring_scheduled_date"],
                     "kind": prepared["recurring_source_kind"], "role": prepared["recurring_occurrence_type"], "entry": identity})
            if self.fail_occurrence == (schedule, prepared["txn_date"]):
                connection.execute(text("""UPDATE postings SET amount=amount+1
                    WHERE entity_id=:scope AND entry_id=:id AND position=2"""), {"scope": self.scope, "id": identity})
            row = connection.execute(text("SELECT * FROM entries WHERE entity_id=:scope AND id=:id"),
                                     {"scope": self.scope, "id": identity}).mappings().one()
            result = {**prepared, "baseline": baseline_for(AggregateKey(self.scope, "entry", identity), row)}
        return result


class RecurringProbe:
    def __init__(self, database, scope, *, fail_attention=False):
        self.database, self.scope, self.fail_attention = database, scope, fail_attention

    def snapshot(self, *, fresh=False):
        with repository_operation(self.database, read_only=True, require_outer=True) as connection:
            schedules = [dict(record(row), kind="Expense", tag_ids="") for row in connection.execute(
                text("SELECT * FROM recurring_schedules WHERE entity_id=:scope"), {"scope": self.scope}).mappings()]
            transactions = []
            for row in connection.execute(text("""SELECT e.*,e.simple_kind AS kind,p.amount,p.category_id,
                cash.account_id,o.schedule_id AS recurring_schedule_id,
                o.scheduled_date AS recurring_scheduled_date,o.source_kind AS recurring_source_kind,
                o.occurrence_type AS recurring_occurrence_type
                FROM entries e JOIN postings p ON p.entity_id=e.entity_id AND p.entry_id=e.id AND p.position=1
                JOIN postings cash ON cash.entity_id=e.entity_id AND cash.entry_id=e.id AND cash.position=2
                LEFT JOIN recurring_occurrences o ON o.entity_id=e.entity_id AND o.entry_id=e.id
                WHERE e.entity_id=:scope"""), {"scope": self.scope}).mappings():
                transactions.append({**record(row), "tag_ids": "", "source_type": "", "source_id": ""})
            snapshot = RecurringSnapshot(schedules, transactions, [], references(connection, self.scope))
        return snapshot

    def reconcile(self, process):
        # Snapshot closes before the service starts independent occurrence units.
        return process(self.snapshot(fresh=True))

    def attention(self, identity, code):
        with repository_operation(self.database, require_outer=True) as connection:
            if self.fail_attention:
                connection.execute(text("SELECT 1/0"))
            connection.execute(text("""UPDATE recurring_schedules SET attention_code=:code,
                attention_at=CASE WHEN :code='' THEN NULL ELSE CURRENT_TIMESTAMP END
                WHERE entity_id=:scope AND id=:id"""), {"scope": self.scope, "id": identity, "code": code})
