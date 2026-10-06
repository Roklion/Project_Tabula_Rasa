"""Operator CLI tests never touch actual secrets, OAuth grants or ledgers."""

from types import SimpleNamespace
import json

from scripts import migrate_sheets_to_postgres as cli
from tests.test_sheets_migration_source import ReadOnlyWorkbook, values_with_records


def test_dry_run_requires_explicit_profile_and_never_constructs_database(monkeypatch):
    selected = []
    workbook = ReadOnlyWorkbook(values_with_records())

    def read_only(settings):
        selected.append(settings["spreadsheet_id"])
        return SimpleNamespace(_workbook=workbook)

    def no_database(_):
        raise AssertionError("Dry-run must not construct a DB pool.")

    monkeypatch.setattr(cli.GoogleSheetsStorage, "from_secrets_read_only", read_only)
    monkeypatch.setattr(cli, "Database", no_database)
    settings = {"business_profiles": {
        "alpha": {"name": "Alpha", "spreadsheet_id": "workbook-alpha"},
        "beta": {"name": "Beta", "spreadsheet_id": "workbook-beta"}}}
    report = cli.run_migration(settings, profile_key="alpha", entity_id="target-alpha")
    assert selected == ["workbook-alpha"]
    assert report["dry_run"] and report["missing_loaders"] == []
    assert not report["cutover_authorized"]


def test_cli_private_configuration_failures_emit_fixed_json_without_exception_content(monkeypatch, capsys):
    def fail(_):
        raise ValueError("private synthetic password and ledger contents")

    monkeypatch.setattr(cli, "load_business_profile_document", fail)
    assert cli.main(["--profile", "alpha", "--entity", "target-alpha"]) == 1
    output = capsys.readouterr().out
    assert "password" not in output and "ledger contents" not in output
    assert json.loads(output)["cutover_authorized"] is False
