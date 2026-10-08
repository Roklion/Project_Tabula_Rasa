"""Persistent non-commercial authority in the shared production HTTP application.

The injected resolver is a synthetic authorization fixture, not a shipped login.
All databases are independently created/dropped by the native pytest fixture.
"""

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from scripts.cutover_bookkeeping import smoke_application
from tabula_rasa.bookkeeping_export.format import validate_artifact
from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import open_migrated_runtime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext
from tabula_rasa.http.errors import TransportError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_export_service
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.cutover import CutoverError, PostgresCutoverController
from tests.postgres.test_cutover import loaded, settings_for, REHEARSAL_EVIDENCE


SETTINGS = HttpSettings("production", "https://owner.example.test", "owner-verification")


def context(profile, *, write=True):
    return RequestContext("synthetic-operator-" + profile, "synthetic-org-" + profile, profile,
        frozenset({"bookkeeping:read", "bookkeeping:write"} if write else {"bookkeeping:read"}),
        "synthetic-session-" + profile, "synthetic-csrf-" + profile)


def resolver(request):
    # Test-only session stand-in. The deployed application supplies its normal
    # authenticated resolver; no environment variable grants request authority.
    profile = request.cookies.get("test_session")
    if profile not in {"alpha", "beta", "alpha-read-only"}:
        raise TransportError("unauthorized")
    return context("alpha", write=False) if profile == "alpha-read-only" else context(profile)


def runtime_factory(database, config):
    return lambda settings: open_migrated_runtime(settings,
        resolve_context=resolver, entity_profiles={"alpha": "alpha", "beta": "beta"},
        profile_secrets=config, database_settings=DatabaseSettings(database.engine.url))


def activated_profiles(database):
    plans = {profile: loaded(database, profile) for profile in ("alpha", "beta")}
    controller = PostgresCutoverController(database)
    for plan in plans.values():
        controller.prepare(plan, mode="rehearsal", evidence=REHEARSAL_EVIDENCE)
        controller.activate(plan.snapshot.binding)
    return plans, controller, settings_for("alpha", "beta")


def test_owner_authority_survives_production_restart_writes_reports_and_complete_export(database, monkeypatch):
    plans, controller, config = activated_profiles(database)
    monkeypatch.setattr("tabula_rasa.composition.GoogleSheetsStorage.from_secrets",
                        lambda _: pytest.fail("Migrated production must not initialize Sheets."))
    assert smoke_application("alpha", config, database, plans["alpha"])["passed"]
    before = create_postgres_export_service(database, "alpha").export()
    for restart in range(2):
        app = create_app(settings=SETTINGS, runtime_factory=runtime_factory(database, config))
        with TestClient(app, base_url=SETTINGS.public_origin) as client:
            client.cookies.set("test_session", "alpha")
            assert client.get("/health/ready").status_code == 200
            session = client.get("/api/v1/session").json()
            assert session["entity"]["id"] == "alpha" and not session["trusted_development"]
            services = app.state.runtime.services(context("alpha"))
            if restart == 0:
                response = client.post("/api/v1/entities/alpha/accounts",
                    headers={"Origin": SETTINGS.public_origin, "X-CSRF-Token": session["csrf_token"]},
                    json={"name": "Synthetic owner reserve", "type": "Bank", "opening_balance": "0"})
                assert response.status_code == 201
                services.transactions.create(transaction_id="owner-expense", kind="Expense",
                    txn_date="2026-10-08", amount="12.50", account_id="cash", category_id="office")
            else:
                accounts = client.get("/api/v1/entities/alpha/accounts").json()["items"]
                assert sum(row["name"] == "Synthetic owner reserve" for row in accounts) == 1
            assert sum(row["id"] == "owner-expense" for row in services.transactions.list(fresh=True)) == 1
            report = services.reporting.period_report(services.reporting.read_ledger(force_refresh=True))
            assert report.totals["net"] == pytest.approx(32.6)
            assert services.receipts.document_scope == "folder-alpha"
            assert services.receipts.references("ordinary")[0].storage_key == "file-ordinary"
            exported = create_postgres_export_service(app.state.runtime.database, "alpha").export()
            validate_artifact(exported, entity_id="alpha")
            assert exported["manifest"]["status"] == "complete"
            assert exported["manifest"]["content_sha256"] != before["manifest"]["content_sha256"]
            assert client.get("/api/v1/entities/beta/accounts").status_code == 403
            client.cookies.set("test_session", "beta")
            assert client.get("/api/v1/session").json()["entity"]["id"] == "beta"
            beta = app.state.runtime.services(context("beta"))
            assert not any(row["id"] == "owner-expense" for row in beta.transactions.list(fresh=True))
            assert beta.receipts.document_scope == "folder-beta"
            assert beta.reporting.period_report(beta.reporting.read_ledger()).totals["net"] == pytest.approx(45.1)
        assert controller.inspect(plans["alpha"].snapshot.binding)["divergent"]
        assert not controller.inspect(plans["beta"].snapshot.binding)["divergent"]
        with pytest.raises(CutoverError, match="committed divergent"):
            controller.rollback(plans["alpha"])
    # A non-commercial authority cannot be relabeled as commercially activated.
    config["bookkeeping_backends"]["alpha"]["mode"] = "commercial_production"
    with pytest.raises(RuntimeError, match="startup failed"):
        runtime_factory(database, config)(SETTINGS)


def test_owner_runtime_preserves_identity_capability_origin_and_csrf_guards(database):
    plans, controller, config = activated_profiles(database)
    app = create_app(settings=SETTINGS, runtime_factory=runtime_factory(database, config))
    with TestClient(app, base_url=SETTINGS.public_origin) as client:
        assert client.get("/api/v1/session").status_code == 401
        client.cookies.set("test_session", "alpha")
        assert client.get("/api/v1/entities/beta/accounts").status_code == 403
        body = {"name": "Synthetic forbidden", "type": "Bank"}
        for headers in ({}, {"Origin": "https://foreign.test", "X-CSRF-Token": "synthetic-csrf-alpha"},
                        {"Origin": SETTINGS.public_origin, "X-CSRF-Token": "invalid"}):
            assert client.post("/api/v1/entities/alpha/accounts", json=body, headers=headers).status_code == 403
        client.cookies.set("test_session", "alpha-read-only")
        assert client.post("/api/v1/entities/alpha/accounts", json=body,
            headers={"Origin": SETTINGS.public_origin, "X-CSRF-Token": "synthetic-csrf-alpha"}).status_code == 403
    for plan in plans.values():
        assert not controller.inspect(plan.snapshot.binding)["divergent"]


@pytest.mark.parametrize("failure", ["unprepared", "prepared", "profile", "entity", "folder", "database", "authority"])
def test_invalid_owner_target_or_authority_refuses_production_startup(database, failure):
    from sqlalchemy import text

    plans = {profile: loaded(database, profile) for profile in ("alpha", "beta")}
    config = settings_for("alpha", "beta")
    controller = PostgresCutoverController(database)
    for profile, plan in plans.items():
        if failure == "unprepared" and profile == "alpha":
            continue
        controller.prepare(plan, mode="rehearsal", evidence=REHEARSAL_EVIDENCE)
        if failure != "prepared" or profile != "alpha":
            controller.activate(plan.snapshot.binding)
    if failure == "profile":
        config["business_profiles"]["alpha"]["spreadsheet_id"] = "workbook-beta"
    elif failure == "entity":
        config["bookkeeping_backends"]["alpha"]["entity_id"] = "beta"
    elif failure == "folder":
        config["business_profiles"]["alpha"]["google_drive"]["receipt_folder"]["id"] = "folder-beta"
    elif failure == "authority":
        config["bookkeeping_backends"]["alpha"] = None
    elif failure == "database":
        with database.transaction() as connection:
            connection.execute(text("UPDATE bookkeeping_cutovers SET evidence=evidence || CAST(:value AS jsonb) WHERE entity_id='alpha'"),
                {"value": '{"database_sha256":"' + "c" * 64 + '"}'})
    with pytest.raises(RuntimeError, match="startup failed") as caught:
        runtime_factory(database, deepcopy(config))(SETTINGS)
    assert caught.value.__context__ is None
    assert not controller.inspect(plans["beta"].snapshot.binding)["divergent"]
