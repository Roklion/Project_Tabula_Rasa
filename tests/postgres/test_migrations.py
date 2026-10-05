import pytest
from sqlalchemy import inspect, text

from tabula_rasa.infrastructure.postgres.migrations import current_revision, downgrade, head_revision, upgrade
from tests.postgres._support import entity
from tabula_rasa.infrastructure.postgres.runtime import DatabaseError


def test_zero_to_head_repeated_upgrade_and_explicit_downgrade(empty_database):
    assert empty_database.health() == {"connected": True, "revision": None}
    upgrade(empty_database)
    assert empty_database.health()["revision"] == head_revision() == "0001_canonical"
    with empty_database.transaction() as connection:
        entity(connection)
    upgrade(empty_database)
    with empty_database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM business_entities")) == 1
    with pytest.raises(ValueError, match="allow-destructive"):
        downgrade(empty_database, "base")
    downgrade(empty_database, "base", allow_destructive=True)
    with empty_database.engine.connect() as connection:
        assert current_revision(connection) is None
        assert inspect(connection).get_table_names() == ["alembic_version"]
    upgrade(empty_database)
    assert empty_database.health()["revision"] == head_revision()


def test_catalog_is_canonical_and_every_relationship_is_entity_qualified(database):
    with database.engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert len(tables) == 26
        assert {"entries", "postings", "business_entities", "migration_id_mappings"} <= tables
        assert "transactions" not in tables
        for table in tables - {"business_entities"}:
            columns = {c["name"]: c for c in inspector.get_columns(table)}
            assert columns["entity_id"]["nullable"] is False
            foreign_keys = inspector.get_foreign_keys(table)
            assert any(fk["referred_table"] == "business_entities" for fk in foreign_keys)
            for fk in foreign_keys:
                assert fk["constrained_columns"][0] == "entity_id"
                if fk["referred_table"] != "business_entities":
                    assert fk["referred_columns"][0] == "entity_id"
        assert str({c["name"]: c for c in inspector.get_columns("postings")}["amount"]["type"]) == "NUMERIC(28, 2)"
        assert not any("password" in c["name"] or "token" in c["name"]
                       for t in tables for c in inspector.get_columns(t))


def test_raw_driver_migration_errors_are_safe_and_roll_back(empty_database, monkeypatch):
    from tabula_rasa.infrastructure.postgres import migrations

    def fail(config, target):
        with config.attributes["connection"].connection.driver_connection.cursor() as cursor:
            cursor.execute("CREATE TABLE synthetic_partial(id integer)")
            cursor.execute("SELECT 'private synthetic migration content'::integer")

    monkeypatch.setattr(migrations.command, "upgrade", fail)
    with pytest.raises(DatabaseError) as caught:
        upgrade(empty_database)
    assert str(caught.value) == "PostgreSQL operation failed (unavailable)."
    assert caught.value.__context__ is None
    with empty_database.engine.connect() as connection:
        assert "synthetic_partial" not in inspect(connection).get_table_names()


def test_baseline_refuses_unknown_existing_schema_without_partial_install(empty_database):
    with empty_database.engine.begin() as connection:
        connection.execute(text("CREATE TABLE accounts (synthetic integer)"))
    with pytest.raises(DatabaseError):
        upgrade(empty_database)
    with empty_database.engine.connect() as connection:
        assert current_revision(connection) is None
        assert inspect(connection).get_table_names() == ["accounts"]


def test_operator_cli_readiness_and_successful_explicit_downgrade(empty_database, monkeypatch, capsys):
    import json
    from tabula_rasa.infrastructure.postgres.__main__ import main

    monkeypatch.setenv("TABULA_DATABASE_URL", empty_database.engine.url.render_as_string(hide_password=False))
    monkeypatch.setattr("sys.argv", ["postgres", "current"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["revision"] is None
    monkeypatch.setattr("sys.argv", ["postgres", "health"])
    assert main() == 1
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["postgres", "upgrade"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["at_head"] is True
    monkeypatch.setattr("sys.argv", ["postgres", "downgrade", "--revision", "base"])
    assert main() == 1
    assert "allow-destructive" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["postgres", "downgrade", "--revision", "base", "--allow-destructive"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["revision"] is None
