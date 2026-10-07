"""Trusted backend selection never falls back to a different backend/profile."""

from types import SimpleNamespace

import pytest

from tabula_rasa.business_profiles import BusinessProfileConfigurationError
from tabula_rasa.composition import create_application, create_sheets_application
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


def profiles():
    return {"business_profiles": {key: {"name": key, "spreadsheet_id": key + "-sheet"} for key in ("alpha", "beta")},
            "bookkeeping_backends": {"alpha": {"backend": "sheets"}, "beta": {"backend": "maintenance"}}}


def test_explicit_sheets_composition_preserves_selected_profile_and_other_profile_maintenance(monkeypatch):
    config = profiles()
    selected = []
    def storage(settings):
        selected.append(settings["spreadsheet_id"])
        return GoogleSheetsStorage(FakeWorkbook())
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets", storage)
    application = create_application("alpha", config)
    assert application.services.profile_key == "alpha"
    with pytest.raises(BusinessProfileConfigurationError, match="maintenance"):
        create_application("beta", config)
    with pytest.raises(BusinessProfileConfigurationError, match="not configured"):
        create_sheets_application("beta", config)
    assert selected == ["alpha-sheet"]


@pytest.mark.parametrize("configuration", [None, {}, {"backend": {}}, {"backend": "unknown"}, {"backend": "postgres"},
                                         {"backend": "postgres", "entity_id": "beta", "mode": "production"}])
def test_missing_or_malformed_authority_configuration_does_not_initialize_sheets(configuration, monkeypatch):
    config = profiles()
    config["bookkeeping_backends"]["alpha"] = configuration
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets", lambda _: pytest.fail("No fallback"))
    with pytest.raises(BusinessProfileConfigurationError):
        create_application("alpha", config)


def test_postgres_without_database_is_not_a_reason_to_initialize_sheets(monkeypatch):
    config = profiles()
    config["bookkeeping_backends"]["alpha"] = {"backend": "postgres", "entity_id": "alpha", "mode": "rehearsal"}
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets", lambda _: pytest.fail("No fallback"))
    with pytest.raises(BusinessProfileConfigurationError, match="requires its configured database"):
        create_application("alpha", config)


def test_backend_map_survives_local_profile_merge(monkeypatch, tmp_path):
    from tabula_rasa.local_profile_store import merged_profile_secrets
    config = profiles()
    monkeypatch.setattr("tabula_rasa.local_profile_store.load_local_profiles", lambda _: config["business_profiles"])
    assert merged_profile_secrets(config, path=tmp_path / "synthetic.json")["bookkeeping_backends"] == config["bookkeeping_backends"]


def test_legacy_sheets_composition_remains_lazy_and_profile_bound(monkeypatch):
    config = profiles()
    del config["bookkeeping_backends"]
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets", lambda _: GoogleSheetsStorage(FakeWorkbook()))
    assert create_sheets_application("beta", config).services.profile_key == "beta"


def test_invalid_explicit_entry_cannot_reenable_the_legacy_sheets_path(monkeypatch):
    config = profiles()
    config["bookkeeping_backends"]["alpha"] = None
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets", lambda _: pytest.fail("No legacy fallback"))
    with pytest.raises(BusinessProfileConfigurationError):
        create_sheets_application("alpha", config)


@pytest.mark.parametrize("command", ["accept", "prepare", "rollback"])
def test_actual_cli_preflight_rejects_retired_format_before_allocating_database(command, monkeypatch):
    from scripts import migrate_sheets_to_postgres as migration_cli, cutover_bookkeeping as cutover_cli
    from tabula_rasa.migration.model import MigrationError
    from tests.test_sheets_migration_source import ReadOnlyWorkbook, values_with_records
    source = values_with_records()
    source["Transactions"][0][7] = "payee"
    workbook = ReadOnlyWorkbook(source)
    config = {"business_profiles": {"alpha": {"spreadsheet_id": workbook.id}}}
    monkeypatch.setattr(GoogleSheetsStorage, "from_secrets_read_only", lambda _: SimpleNamespace(_workbook=workbook))
    monkeypatch.setattr(migration_cli, "Database", lambda _: pytest.fail("No target allocation before preflight"))
    if command == "accept":
        with pytest.raises(MigrationError):
            migration_cli.run_migration(config, profile_key="alpha", entity_id="alpha", accept=True)
    else:
        monkeypatch.setattr(cutover_cli, "load_business_profile_document", lambda _: config)
        monkeypatch.setattr(cutover_cli, "Database", lambda _: pytest.fail("No target allocation before preflight"))
        args = [command, "--profile", "alpha", "--entity", "alpha"]
        if command == "prepare":
            args += ["--mode", "rehearsal", "--evidence", "not-read.json"]
        assert cutover_cli.main(args) == 1
