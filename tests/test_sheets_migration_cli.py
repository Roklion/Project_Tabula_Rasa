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


def test_cli_selected_profile_inventory_is_read_only_and_complete_before_database_construction(monkeypatch):
    from tabula_rasa.application.documents import ReceiptInventory
    from tests.migration_support import document
    workbook = ReadOnlyWorkbook(values_with_records())
    calls = []

    class Store:
        scope_key = "folder-alpha"

        def inventory(self, profile, *, fresh):
            calls.append((profile, fresh))
            return ReceiptInventory((document(profile, "unreferenced-file"),))

    monkeypatch.setattr(cli.GoogleSheetsStorage, "from_secrets_read_only", lambda _: SimpleNamespace(_workbook=workbook))
    monkeypatch.setattr(cli, "Database", lambda _: (_ for _ in ()).throw(AssertionError("No dry-run DB")))
    settings = {"business_profiles": {"alpha": {"name": "Alpha", "spreadsheet_id": workbook.id},
                                      "beta": {"name": "Beta", "spreadsheet_id": "workbook-beta"}}}
    result = cli.run_migration(settings, profile_key="alpha", entity_id="target-alpha", document_store=Store())
    assert calls == [("alpha", True)]
    assert result["unit_counts"]["documents"] == 1 and result["missing_loaders"] == []


def test_cli_returns_nonzero_on_reconciliation_failure_and_does_not_claim_acceptance(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_business_profile_document", lambda _: {})
    monkeypatch.setattr(cli, "run_migration", lambda *_, **__: {
        "reconciliation": {"passed": False, "whole_profile_accepted": False, "cutover_authorized": False}})
    assert cli.main(["--profile", "alpha", "--entity", "alpha", "--reconcile"]) == 1
    assert json.loads(capsys.readouterr().out)["reconciliation"]["passed"] is False
