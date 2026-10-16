"""Explicit hosted byte binding rejects wrong scope and sanitizes failures."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.application.documents import DocumentError, DocumentValidationError
from tabula_rasa.http import alpha_documents, composition
from tabula_rasa.http.config import HttpSettings
from tests.alpha_documents_support import binding, write_binding, SyntheticDrive
from tests.http.test_alpha_gate import HASH


def settings(environment="staging"):
    return HttpSettings(environment, f"https://{environment}.example.test", "test-release", "alpha-synthetic", "operator", HASH)


@pytest.mark.parametrize("change", [
    {"environment": "development"}, {"public_origin": "https://foreign.example.test"},
    {"entity_id": "beta-synthetic"}, {"profile_key": "../private"}, {"profile_key": 4},
    {"business_profiles": {}},
])
def test_wrong_binding_stops_before_google(tmp_path, monkeypatch, change):
    factory = Mock()
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    with pytest.raises(RuntimeError, match="binding failed") as caught:
        alpha_documents.load_alpha_document_store(settings(), {alpha_documents.FILE_ENV: write_binding(tmp_path, {**binding(), **change})})
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    factory.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "relative", "empty", "parse", "oversized", "oauth", "scope", "folder", "duplicate", "grant"])
def test_invalid_file_or_credentials_do_not_fallback(tmp_path, monkeypatch, failure):
    values = deepcopy(binding())
    if failure == "oauth":
        del values["google_drive_oauth"]["client_secret"]
    elif failure == "scope":
        values["google_drive"]["scopes"].append("https://www.googleapis.com/auth/drive")
    elif failure == "folder":
        del values["google_drive"]["receipt_folder"]
    elif failure == "duplicate":
        values["google_drive"]["receipt_folder"] = values["google_drive"]["storage_root"]
    elif failure == "grant":
        values["google_drive"]["refresh_token"] = ""
    path = write_binding(tmp_path, values)
    if failure in {"parse", "oversized"}:
        from pathlib import Path
        Path(path).write_text("private-secret = [" if failure == "parse" else "x" * 65537)
    path = {"missing": str(tmp_path / "absent"), "relative": "private.toml", "empty": ""}.get(failure, path)
    factory = Mock()
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    with pytest.raises(RuntimeError) as caught:
        alpha_documents.load_alpha_document_store(settings(), {alpha_documents.FILE_ENV: path})
    assert caught.value.__context__ is None and "private-secret" not in str(caught.value)
    factory.assert_not_called()


@pytest.mark.parametrize("configured", [HttpSettings("test", "http://testserver", trusted_entity_id="alpha-synthetic"),
                                        HttpSettings("production", "https://production.example.test", access_mode='named_user')])
def test_secret_file_is_hosted_synthetic_only(configured, tmp_path, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    with pytest.raises(RuntimeError):
        alpha_documents.load_alpha_document_store(configured, {alpha_documents.FILE_ENV: write_binding(tmp_path)})
    factory.assert_not_called()


def test_absent_file_has_no_google_or_ambient_profile_reads(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    assert alpha_documents.load_alpha_document_store(settings(), {}) is None
    factory.assert_not_called()


def test_two_hosted_bindings_keep_grants_folders_and_profile_keys_separate(tmp_path, monkeypatch):
    import hashlib
    from tabula_rasa.application.documents import DocumentUpload
    providers = {profile: SyntheticDrive(profile) for profile in ("stage-receipts", "dev-receipts")}
    def factory(config, grant):
        profile = grant["refresh_token"].removeprefix("synthetic-")
        assert grant["receipt_folder"]["id"] == profile + "-receipt_folder"
        return providers[profile]
    monkeypatch.setattr("tabula_rasa.google_drive.GoogleDriveClient", factory)
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    stores = []
    for environment, profile in (("staging", "stage-receipts"), ("development", "dev-receipts")):
        store = alpha_documents.load_alpha_document_store(settings(environment), {
            alpha_documents.FILE_ENV: write_binding(tmp_path, binding(environment, profile))})
        stores.append(store)
        assert store.inventory("alpha-synthetic", fresh=True).documents == ()
        content = profile.encode()
        document = store.upload("alpha-synthetic", DocumentUpload("a" * 32, "receipt.pdf", "application/pdf",
            hashlib.sha256(content).hexdigest(), content))
        assert document.profile_key == "alpha-synthetic"
        assert store.fetch("alpha-synthetic", document.storage_key) == content
        with pytest.raises(DocumentValidationError):
            store.inventory("beta-synthetic")
        with pytest.raises(DocumentError):
            store.store.inventory("wrong-profile")
    assert stores[0].scope_key != stores[1].scope_key
    assert stores[0].fetch("alpha-synthetic", "provider-" + "a" * 32) != stores[1].fetch("alpha-synthetic", "provider-" + "a" * 32)


def test_provider_failure_is_sanitized_and_disposes_default_pool(tmp_path, monkeypatch):
    monkeypatch.setenv(alpha_documents.FILE_ENV, write_binding(tmp_path))
    database = Mock()
    monkeypatch.setattr(composition, "open_alpha_database", lambda _: database)
    factory = Mock(side_effect=RuntimeError("synthetic-secret private provider response"))
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", factory)
    with pytest.raises(RuntimeError, match="startup failed") as caught:
        composition.open_runtime(settings())
    assert caught.value.__context__ is None
    database.dispose.assert_called_once()


@pytest.mark.parametrize("failure", [None, "profile", "kind", "parent", "trashed", "revoked"])
def test_real_client_validates_managed_folder_metadata_without_writes(tmp_path, monkeypatch, failure):
    from tabula_rasa.google_drive import GoogleDriveClient
    from tests.drive_fixtures import drive_folder
    from tests.google_drive._support import DriveSession, FakeResponse

    values = binding()
    profile = values["profile_key"]
    folders = values["google_drive"]
    root = drive_folder(folders["storage_root"]["id"], "Root")
    receipt = drive_folder(folders["receipt_folder"]["id"], "Receipts", parent_id=root["id"],
        profile_key=profile, kind="receipts", storage_root_id=root["id"])
    backup = drive_folder(folders["backup_folder"]["id"], "Ledger Backups", parent_id=root["id"],
        profile_key=profile, kind="ledger-backups", storage_root_id=root["id"])
    if failure in {"profile", "kind"}:
        receipt["appProperties"]["tabulaRasaProfile" if failure == "profile" else "tabulaRasaKind"] = "foreign"
    elif failure == "parent":
        receipt["parents"] = ["foreign-root"]
    elif failure == "trashed":
        receipt["trashed"] = True
    session = DriveSession([FakeResponse(200, root), FakeResponse(200, receipt), FakeResponse(200, backup)])
    if failure == "revoked":
        session.post = Mock(return_value=FakeResponse(400, {"error": "private grant response"}))
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", lambda config, grant: GoogleDriveClient(config, grant, session=session))
    environment = {alpha_documents.FILE_ENV: write_binding(tmp_path, values)}
    if failure:
        with pytest.raises(RuntimeError) as caught:
            alpha_documents.load_alpha_document_store(settings(), environment)
        assert caught.value.__context__ is None
    else:
        assert alpha_documents.load_alpha_document_store(settings(), environment).scope_key == receipt["id"]
        assert session.refresh_tokens == ["synthetic-" + profile]
    assert all(method == "GET" for method, _, _ in session.requests)


def test_default_runtime_binds_only_trusted_alpha_context(tmp_path, monkeypatch):
    monkeypatch.setattr("tabula_rasa.infrastructure.postgres.documents.PostgresReceiptRepository.validate_binding", Mock())
    monkeypatch.setenv(alpha_documents.FILE_ENV, write_binding(tmp_path))
    database = Mock()
    monkeypatch.setattr(composition, "open_alpha_database", lambda _: database)
    monkeypatch.setattr(alpha_documents, "GoogleDriveClient", Mock(return_value=SyntheticDrive("stage-receipts")))
    factory = Mock()
    monkeypatch.setattr(composition, "create_postgres_services", factory)
    runtime = composition.open_runtime(settings())
    context, = runtime.resolve_context.contexts
    runtime.services(context)
    assert factory.call_args.kwargs["document_store"].profile_key == "stage-receipts"
    assert factory.call_args.kwargs["document_store_kind"] == "google_drive"
    factory.reset_mock()
    for invalid in (replace(context, entity_id="beta-synthetic"), replace(context, trusted_development=False)):
        with pytest.raises(Exception):
            runtime.services(invalid)
    factory.assert_not_called()
    runtime.close()


def test_database_allocation_failure_retains_no_private_error(monkeypatch):
    monkeypatch.setattr(composition, "open_alpha_database", Mock(side_effect=ValueError("private connection")))
    with pytest.raises(RuntimeError, match="startup failed") as caught:
        composition.open_runtime(settings())
    assert caught.value.__context__ is None


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_startup_interrupt_propagates_after_pool_cleanup(monkeypatch, interrupt):
    database = Mock()
    monkeypatch.setattr(composition, "open_alpha_database", lambda _: database)
    monkeypatch.setattr(alpha_documents, "load_alpha_document_store", Mock(side_effect=interrupt()))
    with pytest.raises(interrupt):
        composition.open_runtime(settings())
    database.dispose.assert_called_once()


def test_preflight_is_read_only_and_sanitizes_cli_failure(monkeypatch, capsys):
    from tabula_rasa.deployment import documents
    store = Mock()
    store.inventory.return_value = SimpleNamespace(needing_integrity=0)
    loader = Mock(return_value=store)
    monkeypatch.setattr(documents, "load_alpha_document_store", loader)
    environment = {"TABULA_RASA_ENVIRONMENT": "staging", "TABULA_RASA_PUBLIC_ORIGIN": settings().public_origin,
        "TABULA_RASA_TRUSTED_ENTITY_ID": "alpha-synthetic", "TABULA_RASA_ALPHA_USERNAME": "operator",
        "TABULA_RASA_ALPHA_PASSWORD_HASH": HASH}
    documents.check(environment)
    store.inventory.assert_called_once_with("alpha-synthetic", fresh=True)
    store.upload.assert_not_called()
    store.delete.assert_not_called()
    store.inventory.return_value = SimpleNamespace(needing_integrity=1)
    with pytest.raises(ValueError, match="integrity"):
        documents.check(environment)
    monkeypatch.setattr(documents, "check", Mock(side_effect=ValueError("private receipt")))
    with pytest.raises(SystemExit) as caught:
        documents.main()
    assert caught.value.__context__ is None and "private receipt" not in str(caught.value)
    assert not capsys.readouterr().out
