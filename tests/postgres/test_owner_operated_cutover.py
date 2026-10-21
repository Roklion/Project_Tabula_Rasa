"""Persistent non-commercial authority in the shared production HTTP application.

Named sessions/memberships use synthetic users and the real durable validator.
All databases are independently created/dropped by the native pytest fixture.
"""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from scripts.cutover_bookkeeping import smoke_application
from tabula_rasa.bookkeeping_export.format import validate_artifact
from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import open_migrated_runtime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext
from tabula_rasa.http.identity import NamedIdentity
from tabula_rasa.infrastructure.postgres.composition import create_postgres_export_service
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.cutover import CutoverError, PostgresCutoverController
from tabula_rasa.infrastructure.postgres.control_plane import PostgresIdentityRepository
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from tests.postgres.test_cutover import loaded, settings_for, REHEARSAL_EVIDENCE
from tests.postgres.test_identity import verified


SETTINGS = HttpSettings("production", "https://owner.example.test", "owner-verification", access_mode='named_user')


@pytest.fixture(autouse=True)
def synthetic_document_grants(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('TABULA_RASA_CONNECTION_SECRETS_DIR', str(tmp_path))
    monkeypatch.setenv('TABULA_RASA_CONNECTION_SECRETS_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr('tabula_rasa.http.connections.provider_store',
        lambda row, payload, **kwargs: SimpleNamespace(scope_key=payload['scope_key'], store_kind='google_drive'))


def context(database, profile, *, write=True):
    repository = PostgresIdentityRepository(database)
    user = repository.resolve_user(verified('owner-' + profile))
    access = repository.allowed_entities(user.id)[0]
    return RequestContext(user.id, access.organization_id, profile,
        frozenset({"bookkeeping:read", "bookkeeping:write"} if write else {"bookkeeping:read"}),
        "synthetic-session-" + profile, "synthetic-csrf-" + profile)


def named_sessions(database):
    sessions = PostgresSessionRepository(database, SETTINGS.environment, 'a' * 64)
    sessions.configure()
    return sessions


def owned_profiles(database):
    import os
    from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
    from tabula_rasa.http.connections import TenantConnections
    secrets = ConnectionSecrets.from_environment(os.environ)
    repo = PostgresIdentityRepository(database)
    sessions = named_sessions(database)
    credentials = {}
    for profile in ('alpha', 'beta'):
        identity = verified('owner-' + profile)
        user = repo.resolve_user(identity)
        organization = repo.create_organization(user.id, profile)
        from tests.postgres.test_legacy_claims import apply_claim, claim_for
        from tabula_rasa.infrastructure.postgres.connections import PostgresConnections
        apply_claim(database, claim_for(database, profile, organization, user))
        reference = secrets.put(dict(environment=SETTINGS.environment, organization_id=organization,
            entity_id=profile, provider='google_drive', profile_key=profile, scope_key='folder-' + profile))
        PostgresConnections(database).stage(organization_id=organization, entity_id=profile,
            profile_key=profile, scope_key='folder-' + profile,
            secret_ref=reference, expected_revision=0)
        TenantConnections(database, SETTINGS.environment, secrets).change(context(database, profile),
            SimpleNamespace(authenticated_at=identity.authenticated_at), revision=1, connect=True)
        credentials[profile] = sessions.issue(identity)
        if profile == 'alpha':
            reader = verified('reader-alpha')
            repo.set_membership(organization, repo.resolve_user(reader).id, 'read_only')
            credentials['alpha-read-only'] = sessions.issue(reader)
    return credentials


def login(client, credentials, profile='alpha'):
    raw, _ = credentials[profile]
    client.cookies.set('__Host-tabula_session', raw)


def runtime_factory(database, config):
    resolver = NamedIdentity(SETTINGS, named_sessions(database), Mock())
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


def container_factory(database, config, tmp_path, monkeypatch):
    from tabula_rasa.http.composition import open_runtime
    from tabula_rasa.http.migrated_configuration import FILE_ENV
    source = tmp_path / 'bindings.json'
    source.write_text(json.dumps({'profiles': [
        {'entity_id': profile, 'profile_key': profile, 'spreadsheet_id': values['spreadsheet_id'],
         'receipt_folder_id': values['google_drive']['receipt_folder']['id'],
         'mode': config['bookkeeping_backends'][profile]['mode']}
        for profile, values in config['business_profiles'].items()
    ]}), encoding='utf-8')
    monkeypatch.setenv(FILE_ENV, str(source))
    monkeypatch.setattr(DatabaseSettings, 'from_environment', Mock(return_value=DatabaseSettings(database.engine.url)))
    monkeypatch.setattr('tabula_rasa.infrastructure.oidc.OidcSettings.from_environment',
                        Mock(return_value=SimpleNamespace(configuration_hash='a' * 64)))
    monkeypatch.setattr('tabula_rasa.infrastructure.oidc.OidcProvider', Mock())
    return open_runtime


@pytest.mark.parametrize('deployment', ['injected_factory', 'container_configuration'])
def test_owner_authority_survives_production_restart_writes_reports_and_complete_export(database, monkeypatch,
                                                                                     tmp_path, deployment):
    plans, controller, config = activated_profiles(database)
    monkeypatch.setattr("tabula_rasa.composition.GoogleSheetsStorage.from_secrets",
                        lambda _: pytest.fail("Migrated production must not initialize Sheets."))
    assert smoke_application("alpha", config, database, plans["alpha"])["passed"]
    before = create_postgres_export_service(database, "alpha").export()
    credentials = owned_profiles(database)
    factory = (container_factory(database, config, tmp_path, monkeypatch)
               if deployment == 'container_configuration' else runtime_factory(database, config))
    for restart in range(2):
        app = create_app(settings=SETTINGS, runtime_factory=factory)
        with TestClient(app, base_url=SETTINGS.public_origin) as client:
            login(client, credentials)
            assert client.get("/health/ready").status_code == 200
            session = client.get("/api/v1/session").json()
            assert session["entity"]["id"] == "alpha" and not session["trusted_development"]
            services = app.state.runtime.services(context(database, "alpha"))
            if restart == 0:
                response = client.post("/api/v1/entities/alpha/accounts",
                    headers={"Origin": SETTINGS.public_origin, "X-CSRF-Token": session["csrf_token"]},
                    json={"name": "Synthetic owner reserve", "type": "Bank", "opening_balance": "0"})
                assert response.status_code == 201
                services.transactions.create(transaction_id="owner-expense", kind="Expense",
                    txn_date="2026-10-08", amount="12.50", account_id=response.json()["id"], category_id="office")
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
            login(client, credentials, 'beta')
            assert client.get("/api/v1/session").json()["entity"]["id"] == "beta"
            beta = app.state.runtime.services(context(database, "beta"))
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


@pytest.mark.parametrize('failure', ['folder', 'inactive_authority', 'missing_connection', 'pending',
                                    'disconnected', 'missing_grant', 'profile_connection', 'folder_connection'])
def test_container_runtime_refuses_invalid_live_bindings_without_native_fallback(database, tmp_path,
                                                                                monkeypatch, failure):
    plans, controller, config = activated_profiles(database)
    owned_profiles(database)
    if failure == 'folder':
        config['business_profiles']['alpha']['google_drive']['receipt_folder']['id'] = 'folder-beta'
    elif failure == 'inactive_authority':
        controller.rollback(plans['alpha'])
    else:
        from sqlalchemy import text
        with database.transaction() as connection:
            if failure == 'missing_connection':
                connection.execute(text("DELETE FROM external_connections WHERE entity_id='alpha'"))
            elif failure in {'pending', 'disconnected'}:
                connection.execute(text("UPDATE external_connections SET status=:status WHERE entity_id='alpha'"),
                                   {'status': failure})
            elif failure == 'missing_grant':
                connection.execute(text("UPDATE external_connections SET secret_ref=:ref WHERE entity_id='alpha'"),
                                   {'ref': 'c' * 32})
            elif failure == 'profile_connection':
                connection.execute(text("UPDATE external_connections SET profile_key='wrong' WHERE entity_id='alpha'"))
            else:
                connection.execute(text("UPDATE external_connections SET store_scope_key='wrong' WHERE entity_id='alpha'"))
    factory = container_factory(database, config, tmp_path, monkeypatch)
    native = Mock()
    monkeypatch.setattr('tabula_rasa.http.composition.create_postgres_services', native)
    with pytest.raises(RuntimeError, match='startup failed') as caught:
        factory(SETTINGS)
    assert caught.value.__context__ is None
    native.assert_not_called()
    assert not controller.inspect(plans['beta'].snapshot.binding)['divergent']


def test_owner_runtime_preserves_identity_capability_origin_and_csrf_guards(database):
    plans, controller, config = activated_profiles(database)
    credentials = owned_profiles(database)
    app = create_app(settings=SETTINGS, runtime_factory=runtime_factory(database, config))
    with TestClient(app, base_url=SETTINGS.public_origin) as client:
        assert client.get("/api/v1/session").status_code == 401
        login(client, credentials)
        assert client.get("/api/v1/entities/beta/accounts").status_code == 403
        body = {"name": "Synthetic forbidden", "type": "Bank"}
        for headers in ({}, {"Origin": "https://foreign.test", "X-CSRF-Token": "synthetic-csrf-alpha"},
                        {"Origin": SETTINGS.public_origin, "X-CSRF-Token": "invalid"}):
            assert client.post("/api/v1/entities/alpha/accounts", json=body, headers=headers).status_code == 403
        login(client, credentials, 'alpha-read-only')
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
        from tests.postgres.test_legacy_claims import apply_claim, claim_for
        user = PostgresIdentityRepository(database).resolve_user(verified('owner-' + profile))
        organization = PostgresIdentityRepository(database).create_organization(user.id, profile)
        apply_claim(database, claim_for(database, profile, organization, user))
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
