from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

import ast
import csv
from dataclasses import fields
import importlib
import io
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.page_renderers.data_backup.exports import (
    prepare_csv_exports,
    prepared_exports_key,
)
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import TEST_PASSWORD
from tests.fakes import FakeWorkbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _imports_app_bootstrap(tree: ast.AST) -> bool:
    """Match the executable app module without rejecting application services."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "tabula_rasa.app" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (
            node.module == "tabula_rasa.app"
            or (
                node.module == "tabula_rasa"
                and any(alias.name == "app" for alias in node.names)
            )
        ):
            return True
    return False


@pytest.fixture(autouse=True)
def isolate_local_profiles(
    profile_store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
        profile_store_path,
    )


def _logged_in_data_page(profile: dict[str, object]) -> tuple[AppTest, GoogleSheetsStorage]:
    st.cache_resource.clear()
    storage = GoogleSheetsStorage(FakeWorkbook())
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["business_profiles"] = {"test": profile}
    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Data & backup").run()
    return app, storage


def test_data_backup_import_is_side_effect_free_and_uses_explicit_context() -> None:
    package_path = (
        PROJECT_ROOT / "tabula_rasa" / "page_renderers" / "data_backup"
    )
    for path in package_path.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not _imports_app_bootstrap(tree)
        assert not any(
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            for node in tree.body
        )
    for module_name in (
        "cloud_recovery",
        "exports",
        "imports",
        "renderer",
    ):
        module = importlib.import_module(
            f"tabula_rasa.page_renderers.data_backup.{module_name}"
        )
        assert module is not None

    context_fields = {field.name for field in fields(DataBackupContext)}
    assert context_fields >= {
        "profile_key",
        "workbook_admin",
        "services",
        "drive_settings",
        "synology_recovery_settings",
        "configuration_revision",
        "get_drive_client",
        "receipt_manifest_for_backup",
        "confirmed_write",
        "report_storage_error",
    }
    assert "profile_secrets" not in context_fields


def test_extracted_page_imports_are_bootstrap_free_and_one_way() -> None:
    """Page modules may be imported by tests/tools without starting Streamlit."""
    package_root = PROJECT_ROOT / "tabula_rasa" / "page_renderers"
    module_names: list[str] = []
    for path in package_root.rglob("*.py"):
        relative = path.relative_to(PROJECT_ROOT).with_suffix("")
        module_name = ".".join(relative.parts)
        module_names.append(module_name)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not _imports_app_bootstrap(tree)
        assert not any(
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            for node in tree.body
        ), f"{module_name} executes a call while importing"

    for module_name in sorted(module_names):
        assert importlib.import_module(module_name) is not None


def test_prepared_exports_key_isolated_by_profile_configuration_and_data_revision() -> None:
    assert prepared_exports_key("north", "config-1", 0) == (
        "prepared-live-exports:north:config-1:0"
    )
    assert prepared_exports_key("north", "config-1", 1) != (
        prepared_exports_key("north", "config-1", 0)
    )
    assert prepared_exports_key("south", "config-1", 0) != (
        prepared_exports_key("north", "config-1", 0)
    )
    assert prepared_exports_key("north", "config-2", 0) != (
        prepared_exports_key("north", "config-1", 0)
    )


def test_csv_exports_include_resolved_transaction_and_mileage_tags() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Travel", "Expense")
    tag = storage.create_tag("Client project")
    storage.create_transaction(
        txn_date="2026-09-02",
        kind="Expense",
        amount="12.50",
        account_id=account["id"],
        category_id=category["id"],
        tag_ids=[tag["id"]],
    )
    storage.create_mileage_trip(
        trip_date="2026-09-02",
        miles="8.5",
        start_location="Office",
        destination="Client",
        business_purpose="Meeting",
        tag_ids=[tag["id"]],
    )

    from tabula_rasa.composition import create_sheets_application
    from tests.app_support import profile_config

    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        services = create_sheets_application(
            "test", {"business_profiles": {"test": profile_config()}}
        ).services
    exports = prepare_csv_exports(services, accounts=services.accounts.list(active_only=False), tags=services.tags.list())
    transaction = next(
        csv.DictReader(io.StringIO(exports["transactions"].decode("utf-8")))
    )
    mileage = next(
        csv.DictReader(io.StringIO(exports["mileage"].decode("utf-8")))
    )

    assert transaction["Tags"] == "Client project"
    assert mileage["Tags"] == "Client project"


def test_unconfigured_drive_and_missing_local_synology_states_are_explicit() -> None:
    app, _ = _logged_in_data_page(
        {
            "name": "Test Business",
            "spreadsheet_id": "test-sheet",
            "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        }
    )

    subheaders = {item.value for item in app.subheader}
    assert {"Cloud backup", "Recovery status", "Exports", "Imports"} <= subheaders
    assert any("select a backup folder" in item.value for item in app.info)
    assert any("No local Synology recovery record" in item.value for item in app.info)
    assert not app.exception


def test_synology_status_keeps_profile_root_children_and_operational_guidance() -> None:
    app, _ = _logged_in_data_page(
        {
            "name": "Test Business",
            "spreadsheet_id": "test-sheet",
            "google_drive": google_grant('owner@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
            "synology_recovery": {
                "layout": "profile-root",
                "destination_path": "/volume1/Tabula_Rasa_Backups/test",
                "schedule": "Continuous",
                "retention_policy": "Keep quarterly versions",
            },
        }
    )

    body = "\n".join(
        [str(item.value) for item in app.markdown]
        + [str(item.value) for item in app.caption]
    )
    warnings = "\n".join(str(item.value) for item in app.warning)
    assert "Expected NAS children" in body
    assert "Receipts and Ledger Backups" in body
    assert "Download remote changes only" in body
    assert "Destination deletions" in body
    assert "Disabled" in body
    assert "/volume1/Tabula_Rasa_Backups/test" in body
    assert "does not connect to the NAS" in body
    assert "backup folder selected" in warnings
    assert "receipt folder selected" in warnings
    assert "storage root selected" in warnings


def test_import_workflows_keep_separate_profile_keys_and_explicit_writes() -> None:
    source = (
        PROJECT_ROOT
        / "tabula_rasa"
        / "page_renderers"
        / "data_backup"
        / "imports.py"
    ).read_text(encoding="utf-8")
    assert 'key=f"transaction_csv_upload_{context.profile_key}"' in source
    assert 'key=f"quickbooks_transaction_upload_{context.profile_key}"' in source
    assert 'key=f"quickbooks_mileage_upload_{context.profile_key}"' in source
    assert "context.services.imports.preview_quickbooks" in source
    assert "preview_quickbooks_mileage" in source
    assert source.count('encoding="utf-8-sig"') == 3
    assert source.count('.fillna("")') == 3
    assert source.count("context.confirmed_write(") == 3
    assert "Import rows" in source
    assert "Import validated rows" in source
    assert "Import validated mileage" in source
    assert "except ValueError as error:" in source
    assert "st.error(str(error))" in source


def test_action_spinners_cover_only_explicit_backup_export_and_import_actions() -> None:
    package_path = PROJECT_ROOT / "tabula_rasa" / "page_renderers" / "data_backup"
    cloud_source = (package_path / "cloud_recovery.py").read_text(encoding="utf-8")
    export_source = (package_path / "exports.py").read_text(encoding="utf-8")
    import_source = (package_path / "imports.py").read_text(encoding="utf-8")

    assert cloud_source.count("with st.spinner(") == 2
    assert export_source.count("with st.spinner(") == 1
    assert import_source.count("with st.spinner(") == 3
    assert import_source.count("context.confirmed_write(") == 3


def test_page_export_filenames_use_tabula_rasa() -> None:
    source = (
        PROJECT_ROOT
        / "tabula_rasa"
        / "page_renderers"
        / "data_backup"
        / "exports.py"
    ).read_text(encoding="utf-8")
    assert 'f"tabula-rasa-{date.today()}.csv"' in source
    assert 'f"tabula-rasa-mileage-{date.today()}.csv"' in source
    assert 'f"tabula-rasa-backup-{date.today()}.zip"' in source

    mileage_source = (
        PROJECT_ROOT / "tabula_rasa" / "page_renderers" / "mileage_ledger.py"
    ).read_text(encoding="utf-8")
    assert 'f"tabula-rasa-mileage-{start}-to-{end}.csv"' in mileage_source

    ledger_source = (
        PROJECT_ROOT
        / "tabula_rasa"
        / "page_renderers"
        / "transactions"
        / "ledger_bulk.py"
    ).read_text(encoding="utf-8")
    assert 'f"tabula-rasa-selected-{date.today()}.csv"' in ledger_source
