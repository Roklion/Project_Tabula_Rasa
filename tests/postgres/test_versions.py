import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.infrastructure.postgres.concurrency import AggregateKey, check_baseline, lock_aggregates
from tabula_rasa.infrastructure.postgres.migrations import downgrade, upgrade
from tabula_rasa.infrastructure.postgres.operations import repository_operation
from tests.postgres._support import account, category, entity, ledger, simple_entry, load_baseline as load


def version(connection, table, identity):
    return connection.scalar(text(f"SELECT version FROM {table} WHERE entity_id='alpha' AND id=:id"), {"id": identity})


def test_root_versions_noops_and_counter_protection(database):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
        assert version(connection, "accounts", "cash") == 1
        connection.execute(text("UPDATE accounts SET opening_balance=0"))
        assert version(connection, "accounts", "cash") == 1
        connection.execute(text("UPDATE accounts SET opening_balance=-12.34"))
        assert version(connection, "accounts", "cash") == 2
        stamp = connection.scalar(text("SELECT updated_at FROM accounts"))
        connection.execute(text("UPDATE accounts SET updated_at='2000-01-01'"))
        assert connection.scalar(text("SELECT updated_at FROM accounts")) == stamp
    for counter in (1, 20):
        with pytest.raises(StorageValidationError):
            with repository_operation(database) as connection:
                connection.execute(text("UPDATE accounts SET version=:version"), {"version": counter})


def test_entry_lines_tags_and_document_links_invalidate_the_loaded_baseline(database):
    with repository_operation(database) as connection:
        ledger(connection)
        simple_entry(connection)
        connection.execute(text("""INSERT INTO tags(entity_id,id,name,name_key,incarnation_id)
            VALUES ('alpha','tag','Synthetic','synthetic','tag')"""))
        connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
            VALUES ('alpha','receipt','receipt','synthetic.txt','synthetic','synthetic')"""))
    key = AggregateKey("alpha", "entry", "income")
    for sql in (
        "UPDATE postings SET amount=15",
        "INSERT INTO entry_tags VALUES ('alpha','income','tag')",
        "DELETE FROM entry_tags",
        "INSERT INTO document_links(entity_id,document_id,entry_id,position) VALUES ('alpha','receipt','income',1)",
        "DELETE FROM document_links",
    ):
        token = load(database, key)
        with repository_operation(database) as connection:
            connection.execute(text(sql))
        with repository_operation(database) as connection:
            row = lock_aggregates(connection, [key])[key]
            with pytest.raises(StorageConflictError):
                check_baseline(key, row, token, required=True)
    # A display-name refresh changes only the reference aggregate.
    token = load(database, key)
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE tags SET name='Renamed',name_key='renamed'"))
    assert load(database, key) == token


def test_mileage_tags_advance_only_the_selected_entity(database):
    with repository_operation(database) as connection:
        for scope in ("alpha", "beta"):
            entity(connection, scope)
            connection.execute(text("""INSERT INTO mileage_records(entity_id,id,incarnation_id,trip_date,miles,
                start_location,destination,business_purpose) VALUES (:scope,'trip','trip','2026-10-05',12.3,
                'Synthetic start','Synthetic end','Synthetic purpose')"""), {"scope": scope})
            connection.execute(text("""INSERT INTO tags(entity_id,id,name,name_key,incarnation_id)
                VALUES (:scope,'tag','Synthetic','synthetic','tag')"""), {"scope": scope})
    alpha = AggregateKey("alpha", "mileage", "trip")
    beta = AggregateKey("beta", "mileage", "trip")
    first, second = load(database, alpha), load(database, beta)
    with repository_operation(database) as connection:
        connection.execute(text("INSERT INTO mileage_tags VALUES ('alpha','trip','tag')"))
    assert load(database, alpha) != first
    assert load(database, beta) == second
    with pytest.raises(StorageValidationError) as caught:
        with repository_operation(database) as connection:
            connection.execute(text("INSERT INTO mileage_tags VALUES ('alpha','trip','beta-only')"))
    assert caught.value.code == "reference"
    assert load(database, beta) == second


def test_projection_detail_changes_advance_the_mixed_source(database):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
        category(connection, category_id="expense", kind="Expense")
        connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,
            total_expense,business_use_percentage,allocated_amount,account_id,category_id,
            allocation_rationale,expected_projection_entry_id)
            VALUES ('alpha','source','source','2026-10-05',100,50,50,'cash','expense','Synthetic','projection')"""))
        connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,
            simple_kind,mixed_use_source_id)
            VALUES ('alpha','projection','projection','2026-10-05','simple','Expense','source')"""))
        connection.execute(text("UPDATE entries SET description='Allocation rationale: Synthetic' WHERE id='projection'"))
        connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,
            amount,account_id,category_id) VALUES
            ('alpha','projection:1','projection','simple',1,'Debit',50,NULL,'expense'),
            ('alpha','projection:2','projection','simple',2,'Credit',50,'cash',NULL)"""))
    key = AggregateKey("alpha", "mixed_use", "source")
    before = load(database, key)
    with repository_operation(database) as connection:
        original_version = version(connection, "mixed_use_sources", "source")
        connection.execute(text("UPDATE postings SET amount=60"))
        assert version(connection, "mixed_use_sources", "source") > original_version
        connection.execute(text("UPDATE mixed_use_sources SET allocated_amount=60,business_use_percentage=60"))
    assert load(database, key) != before


def test_schedule_attention_is_outside_the_editable_baseline(database):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
        category(connection, kind="Expense")
        connection.execute(text("""INSERT INTO recurring_schedules(entity_id,id,incarnation_id,name,source_kind,
            recurrence_unit,recurrence_interval,anchor_date,start_date,status,amount,account_id,category_id)
            VALUES ('alpha','schedule','schedule','Synthetic','transaction','month',1,
            '2026-10-05','2026-10-05','active',10,'cash','sales')"""))
    key = AggregateKey("alpha", "schedule", "schedule")
    before = load(database, key)
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE recurring_schedules SET attention_code='synthetic',attention_at=now()"))
    assert load(database, key) == before
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE recurring_schedules SET amount=20"))
    assert load(database, key) != before


def test_version_revision_downgrade_preserves_data_and_reupgrade(database):
    with repository_operation(database) as connection:
        entity(connection)
        account(connection)
        connection.execute(text("UPDATE accounts SET opening_balance=25"))
    downgrade(database, "0001_canonical", allow_destructive=True)
    with database.transaction(read_only=True) as connection:
        assert version(connection, "accounts", "cash") == 2
        assert connection.scalar(text("SELECT opening_balance FROM accounts")) == 25
    upgrade(database)
    with repository_operation(database) as connection:
        connection.execute(text("UPDATE accounts SET opening_balance=30"))
        assert version(connection, "accounts", "cash") == 3
