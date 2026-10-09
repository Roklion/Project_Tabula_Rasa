"""Real browser-contract HTTP -> services -> PostgreSQL; two synthetic entities."""

from fastapi.testclient import TestClient
import pytest

from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext
from tabula_rasa.http.composition import open_runtime
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository


def test_native_http_list_create_validation_and_two_entity_isolation(database):
    for scope in ("alpha", "beta"):
        PostgresLedgerSetupRepository.create_entity(database, scope, scope.title())
    context = RequestContext("actor", "org", "alpha",
        frozenset({"bookkeeping:read", "bookkeeping:write"}), "scope", "csrf")
    runtime = PostgresRuntime(database, lambda request: context,
        service_factory=lambda context: create_postgres_services(database, context.entity_id))
    settings = HttpSettings("test", "http://testserver")
    with TestClient(create_app(settings=settings, runtime_factory=lambda settings: runtime)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/v1/session").json()["entity"]["name"] == "Alpha"
        body = {"name": "Reserve", "type": "Bank", "opening_balance": "-12.50"}
        headers = {"Origin": "http://testserver", "X-CSRF-Token": "csrf"}
        created = client.post("/api/v1/entities/alpha/accounts", json=body, headers=headers)
        assert created.status_code == 201
        row = created.json()
        assert row["opening_balance"] == "-12.50" and row["baseline"]
        assert client.get("/api/v1/entities/alpha/accounts").json()["items"] == [row]
        assert client.post("/api/v1/entities/alpha/accounts", json=body, headers=headers).status_code == 409
        assert client.post("/api/v1/entities/beta/accounts", json=body, headers=headers).status_code == 403
        assert create_postgres_services(database, "beta").accounts.list() == []
        invalid = client.post("/api/v1/entities/alpha/accounts",
            json={**body, "name": "Invalid", "classification": "Liability"}, headers=headers)
        assert invalid.status_code == 422
        assert len(create_postgres_services(database, "alpha").accounts.list()) == 1
        for amount in ("9" * 27, "-" + "9" * 27, "9" * 26 + ".999"):
            invalid = client.post("/api/v1/entities/alpha/accounts",
                json={**body, "name": "Overflow", "opening_balance": amount}, headers=headers)
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "validation"
            assert amount not in invalid.text
        assert len(create_postgres_services(database, "alpha").accounts.list()) == 1
        assert create_postgres_services(database, "beta").accounts.list() == []
        maximum = client.post("/api/v1/entities/alpha/accounts",
            json={**body, "name": "Maximum", "opening_balance": "9" * 26 + ".99"}, headers=headers)
        assert maximum.status_code == 201
        assert maximum.json()["opening_balance"] == "9" * 26 + ".99"


def test_native_readiness_rejects_unmigrated_database(empty_database):
    runtime = PostgresRuntime(empty_database, lambda request: None, service_factory=lambda context: None)
    with TestClient(create_app(settings=HttpSettings("test", "http://testserver"),
                              runtime_factory=lambda settings: runtime)) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200


def test_runtime_unknown_fixture_refuses_startup_without_creating_entity(database, monkeypatch):
    monkeypatch.setattr("tabula_rasa.http.composition.Database", lambda settings: database)
    monkeypatch.setattr("tabula_rasa.http.composition.DatabaseSettings.from_environment", lambda **kwargs: None)
    with pytest.raises(RuntimeError, match="startup failed"):
        open_runtime(HttpSettings("test", "http://testserver", trusted_entity_id="alpha-synthetic"))

def test_default_local_runtime_starts_with_seeded_fixture_and_real_pool(database, monkeypatch):
    from tabula_rasa.infrastructure.postgres.config import DatabaseSettings

    PostgresLedgerSetupRepository.create_entity(database, "alpha-synthetic", "Synthetic development")
    PostgresLedgerSetupRepository.create_entity(database, "beta-synthetic", "Beta development")
    monkeypatch.setattr("tabula_rasa.http.composition.DatabaseSettings.from_environment",
                        lambda **kwargs: DatabaseSettings(database.engine.url))
    settings = HttpSettings("test", "http://testserver", trusted_entity_id="alpha-synthetic")
    with TestClient(create_app(settings=settings), client=("127.0.0.1", 50000)) as client:
        session = client.get("/api/v1/session").json()
        assert session["trusted_development"] is True
        assert session["entity"]["id"] == "alpha-synthetic"
        assert client.get("/health/ready").status_code == 200
        assert {item["id"] for item in client.get("/api/v1/entities").json()["items"]} == {"alpha-synthetic", "beta-synthetic"}
        assert client.get("/api/v1/entities/alpha-synthetic/accounts").json() == {"items": []}
        response = client.post("/api/v1/entities/alpha-synthetic/accounts",
            headers={"Origin": settings.public_origin, "X-CSRF-Token": session["csrf_token"]},
            json={"name": "Synthetic bank", "type": "Bank", "opening_balance": "10.00"})
        assert response.status_code == 201
        assert client.get("/api/v1/entities/another/accounts").status_code == 403


def test_default_runtime_refuses_partial_development_fixture(database, monkeypatch):
    from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
    from tests.postgres.test_http_baselines import snapshot

    PostgresLedgerSetupRepository.create_entity(database, "alpha-synthetic", "Alpha development")
    before = snapshot(database)
    monkeypatch.setattr("tabula_rasa.http.composition.DatabaseSettings.from_environment",
                        lambda **kwargs: DatabaseSettings(database.engine.url))
    with pytest.raises(RuntimeError, match="startup failed"):
        open_runtime(HttpSettings("test", "http://testserver", trusted_entity_id="alpha-synthetic"))
    assert snapshot(database) == before  # Startup never creates the missing fixture.
