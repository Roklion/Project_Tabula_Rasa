"""Actual default HTTP composition, canonical metadata and scoped Drive adapter."""

from dataclasses import replace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.http import alpha_documents, composition
from tabula_rasa.http.app import create_app
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database
from tests.alpha_documents_support import binding, write_binding, SyntheticDrive
from tests.http.test_alpha_documents import settings
from tests.postgres._support import account, category, entity

PREFIX = "/api/v1/entities/alpha-synthetic/"
CONTENT = b"%PDF synthetic alpha receipt"


@pytest.mark.parametrize("environment,profile", [("staging", "stage-receipts"), ("development", "dev-receipts")])
def test_bound_default_http_receipts_restart_and_failure_isolation(database, tmp_path, monkeypatch, environment, profile, caplog):
    with database.transaction() as connection:
        for scope in ("alpha-synthetic", "beta-synthetic"):
            entity(connection, scope)
            account(connection, scope, "bank")
            category(connection, scope, "office", kind="Expense")
    configured = settings(environment)
    monkeypatch.setenv(alpha_documents.FILE_ENV, write_binding(tmp_path, binding(environment, profile)))
    provider = SyntheticDrive(profile)
    def factory(config, grant):
        assert grant["refresh_token"] == "synthetic-" + profile
        return provider
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    monkeypatch.setattr("tabula_rasa.google_drive.GoogleDriveClient", factory)
    # Only pool allocation is substituted; create_app uses default open_runtime.
    monkeypatch.setattr(composition, "open_alpha_database", lambda _: Database(DatabaseSettings(database.engine.url)))
    document_id = "a" * 32
    url = PREFIX + "documents/" + document_id + "/content"
    transaction_id = None
    for restart in (False, True):
        with TestClient(create_app(settings=configured), base_url=configured.public_origin) as client:
            client.auth = ("operator", "synthetic-alpha-password")
            context = client.get("/api/v1/session").json()
            headers = {"Origin": configured.public_origin, "X-CSRF-Token": context["csrf_token"]}
            assert client.get(url).status_code == (200 if restart else 404)
            if not restart:
                created = client.post(PREFIX + "transactions", headers=headers, json={
                    "transaction_id": "expense", "txn_date": "2026-10-10", "kind": "Expense", "amount": "12.50",
                    "account_id": "bank", "category_id": "office"})
                assert created.status_code == 201, created.text
                transaction_id = created.json()["id"]
            uploaded = client.put(url, params={"filename": "receipt.pdf"}, headers=headers, content=CONTENT)
            assert uploaded.status_code == 200, uploaded.text
            document = uploaded.json()
            assert not {"storage_key", "open_url", "profile_key", "store_kind"} & document.keys()
            assert provider.uploads == 1
            path = PREFIX + "transactions/" + transaction_id + "/receipts"
            assert client.post(path, headers=headers, json={"document_id": document_id}).status_code == 200
            assert client.get(url).content == CONTENT
            assert client.get(path).json()["items"] == [document]
            assert client.delete(path + "/" + document_id, headers=headers).status_code == 200
            assert client.get(PREFIX + "documents").json()["items"] == [document]
            assert client.get(url).content == CONTENT
            assert client.post(path, headers=headers, json={"document_id": document_id}).status_code == 200
            assert client.delete(path + "/" + document_id, headers=headers).status_code == 200
            assert provider.deletes == 0
            assert client.get(url.replace("alpha-synthetic", "beta-synthetic")).status_code == 403
            runtime = client.app.state.runtime
            with pytest.raises(Exception):
                runtime.services(replace(runtime.resolve_context.context, entity_id="beta-synthetic"))
            with database.transaction(read_only=True) as connection:
                row = connection.execute(text("SELECT entity_id,store_kind,store_scope_key FROM documents")).one()
                assert tuple(row) == ("alpha-synthetic", "google_drive", profile + "-receipt_folder")
                assert connection.scalar(text("SELECT count(*) FROM document_links")) == 0
            # Dependency errors return only stable transport guidance, never raw text.
            original = provider.list_profile_receipts
            provider.list_profile_receipts = Mock(side_effect=GoogleDriveAccessError("private synthetic provider response"))
            try:
                response = client.get(PREFIX + "documents")
                assert response.status_code == 503 and "private synthetic" not in response.text
            finally:
                provider.list_profile_receipts = original
    assert provider.uploads == 1 and provider.deletes == 0
    assert "private synthetic" not in caplog.text
    # Retained unlinked metadata must not disappear behind another valid binding.
    replacement = SyntheticDrive("replacement-receipts")
    monkeypatch.setenv(alpha_documents.FILE_ENV,
        write_binding(tmp_path, binding(environment, "replacement-receipts")))
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", lambda *_: replacement)
    with pytest.raises(RuntimeError, match="startup failed") as caught:
        composition.open_runtime(configured)
    assert caught.value.__context__ is None
    assert replacement.uploads == 0 and provider.deletes == 0
    # The original binding remains usable; refusal changed neither metadata nor bytes.
    monkeypatch.setenv(alpha_documents.FILE_ENV, write_binding(tmp_path, binding(environment, profile)))
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    runtime = composition.open_runtime(configured)
    runtime.close()
