"""Synthetic native PostgreSQL gate, fixture and two-entity deployment isolation."""

from fastapi.testclient import TestClient
import pytest

from tabula_rasa.deployment import database as tooling
from tabula_rasa.http.alpha import password_hash
from tabula_rasa.http.app import create_app
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository
from tabula_rasa.infrastructure.postgres.runtime import Database


def test_hosted_gate_native_fixture_isolation_and_repeat_seed_refusal(database, monkeypatch):
    # Only the provider endpoint boundary is substituted, with a disposable native DB.
    monkeypatch.setattr(tooling, "bound_database", lambda _: database)
    tooling.seed({})
    with pytest.raises(Exception):
        tooling.seed({})
    PostgresLedgerSetupRepository.create_entity(database, "other-synthetic", "Other fixture")
    other = create_postgres_services(database, "other-synthetic")
    other.accounts.create("Other environment only", "Bank", "99.00")
    monkeypatch.setattr("tabula_rasa.http.composition.open_alpha_database",
                        lambda _: Database(DatabaseSettings(database.engine.url)))
    configured = HttpSettings("staging", "https://stage.example.test", "test-release", "alpha-synthetic",
                              "stage", password_hash("synthetic-only"))
    with TestClient(create_app(settings=configured), base_url=configured.public_origin) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/v1/session").status_code == 401
        client.auth = ("stage", "synthetic-only")
        assert client.get("/api/v1/session").json()["entity"]["id"] == "alpha-synthetic"
        rows = client.get("/api/v1/entities/alpha-synthetic/accounts").json()["items"]
        assert len(rows) == 1 and rows[0]["name"] == "Deployment connectivity"
        assert rows[0]["opening_balance"] == "0.00"
        assert client.get("/api/v1/entities/other-synthetic/accounts").status_code == 403
        assert other.accounts.list()[0]["name"] == "Other environment only"


def test_migration_runs_existing_cli_against_native_current_head(database, monkeypatch):
    monkeypatch.setattr(tooling, "bound_database", lambda _: database)
    from os import environ
    tooling.migrate({**environ, "TABULA_RASA_DATABASE_URL": database.engine.url.render_as_string(hide_password=False)})
    assert database.health()["connected"] is True


def test_operator_bootstrap_requires_blank_native_database(empty_database, monkeypatch):
    from os import environ
    from sqlalchemy import text
    monkeypatch.setattr(tooling, "bound_database", lambda _: empty_database)
    configured = {**environ, "TABULA_RASA_DATABASE_URL": empty_database.engine.url.render_as_string(hide_password=False)}
    with empty_database.transaction() as connection:
        connection.execute(text("CREATE TABLE retained_record (id integer)"))
    with pytest.raises(ValueError, match="blank database"):
        tooling.migrate(configured, bootstrap=True)
    with empty_database.transaction() as connection:
        connection.execute(text("DROP TABLE retained_record"))
    tooling.migrate(configured, bootstrap=True)
    assert empty_database.health()["revision"] == tooling.head_revision()
