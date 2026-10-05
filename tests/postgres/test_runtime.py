from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError
from tests.postgres._support import entity, account


def test_outer_operation_commits_nested_repository_work(database):
    with database.transaction() as outer:
        entity(outer)
        with database.transaction() as inner:
            assert inner is outer
            account(inner)
        with database.transaction(read_only=True) as read:
            assert read is outer
            assert read.scalar(text("SELECT count(*) FROM accounts")) == 1
        with database.engine.connect() as independent:
            assert independent.scalar(text("SELECT count(*) FROM accounts")) == 0
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM accounts")) == 1


def test_operation_rolls_back_all_participating_work(database):
    with pytest.raises(RuntimeError, match="synthetic"):
        with database.transaction() as connection:
            entity(connection)
            with database.transaction() as inner:
                account(inner)
            raise RuntimeError("synthetic")
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 0


def test_caught_nested_failure_cannot_commit_partial_operation(database):
    with pytest.raises(DatabaseError, match="operation_aborted"):
        with database.transaction() as connection:
            entity(connection)
            try:
                with database.transaction():
                    raise ValueError("synthetic")
            except ValueError:
                pass
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 0


def test_caught_sql_failure_cannot_report_commit(database):
    with pytest.raises(DatabaseError, match="operation_aborted"):
        with database.transaction() as connection:
            entity(connection)
            try:
                with database.transaction() as inner:
                    entity(inner)
            except SQLAlchemyError:
                pass


def test_read_snapshot_is_coherent_and_forbids_writes(database):
    with database.transaction() as connection:
        entity(connection)
        account(connection)
    writer = Database(DatabaseSettings(database.engine.url))
    try:
        with database.transaction(read_only=True) as reader:
            assert reader.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert reader.scalar(text("SHOW transaction_read_only")) == "on"
            assert reader.scalar(text("SHOW timezone")) == "UTC"
            assert reader.scalar(text("SELECT opening_balance FROM accounts")) == Decimal("0")
            with writer.transaction() as connection:
                connection.execute(text("UPDATE accounts SET opening_balance = 12.34"))
            assert reader.scalar(text("SELECT opening_balance FROM accounts")) == Decimal("0")
        with pytest.raises(DatabaseError, match="read_only"):
            with database.transaction(read_only=True) as reader:
                reader.execute(text("UPDATE accounts SET opening_balance = 0"))
    finally:
        writer.dispose()


def test_caught_outer_sql_failure_cannot_silently_roll_back_as_success(database):
    with pytest.raises(DatabaseError, match="operation_aborted"):
        with database.transaction() as connection:
            entity(connection)
            try:
                entity(connection)
            except SQLAlchemyError:
                pass
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 0


def test_mismatched_nested_read_boundary_aborts_operation(database):
    with pytest.raises(DatabaseError, match="boundary_mismatch"):
        with database.transaction(read_only=True):
            with database.transaction():
                pass


def test_constraint_error_translation_never_prints_private_values(database, capsys, caplog):
    with database.transaction() as connection:
        entity(connection)
    with pytest.raises(DatabaseError) as caught:
        with database.transaction() as connection:
            connection.execute(text("""INSERT INTO business_entities(id,name,incarnation_id)
                VALUES ('alpha','private ledger content','secret credential shaped value')"""))
    assert caught.value.code == "duplicate"
    assert str(caught.value) == "PostgreSQL operation failed (duplicate)."
    assert caught.value.__context__ is None
    assert "private ledger content" not in caplog.text + capsys.readouterr().out
    assert database.health()["connected"] is True


def test_connectivity_error_diagnostic_hides_url_and_password():
    database = Database(DatabaseSettings.from_environment({
        "TABULA_DATABASE_URL": "postgresql://private-user:private-password@127.0.0.1:1/private-database",
        "TABULA_DATABASE_CONNECT_TIMEOUT": "1",
    }))
    try:
        assert database.health() == {"connected": False, "code": "unavailable"}
    finally:
        database.dispose()


@pytest.mark.parametrize("nested", [False, True])
def test_raw_driver_failure_is_safe_and_rolls_back(database, nested, capsys, caplog):
    with pytest.raises(DatabaseError) as caught:
        with database.transaction() as connection:
            entity(connection)
            if nested:
                with database.transaction() as inner:
                    with inner.connection.driver_connection.cursor() as cursor:
                        cursor.execute("SELECT 'synthetic private value'::integer")
            else:
                with connection.connection.driver_connection.cursor() as cursor:
                    cursor.execute("SELECT 'synthetic private value'::integer")
    assert caught.value.code == "unavailable"
    assert str(caught.value) == "PostgreSQL operation failed (unavailable)."
    assert caught.value.__context__ is None
    assert "synthetic private value" not in caplog.text + capsys.readouterr().out
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 0
    assert database.health()["connected"] is True
