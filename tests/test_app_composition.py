from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.application import AccountService
from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.business_profiles import BusinessProfileConfigurationError
from tabula_rasa.composition import create_sheets_application
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tabula_rasa.page_renderers.data_backup.exports import prepared_exports_key
from tests.app_support import (
    authenticated_app,
    build_app_test,
    by_label,
    navigate_to,
    profile_config,
)
from tests.fakes import FakeWorkbook


PAGE_RENDERERS = {
    "Dashboard": "dashboard.render_dashboard",
    "Transactions": "transactions.render_transactions",
    "Assets": "assets.render_assets",
    "Mileage": "mileage.render_mileage",
    "Accounts": "accounts.render_accounts",
    "Categories": "categories.render_categories",
    "Reports": "reports.render_reports",
    "Data & backup": "data_backup.render_data_backup",
}


def test_account_renderer_uses_the_selected_profile_service_for_create_and_edit() -> None:
    """The management page can operate on reference data supplied by a port."""
    class AccountRepository:
        def __init__(self) -> None:
            self.records = []

        def list(self, *, active_only=True):
            return [dict(record) for record in self.records if not active_only or record["active"]]

        def create(self, name, account_type, opening_balance, *, classification, parent_id):
            record = {
                "id": "service-account",
                "name": name,
                "type": account_type,
                "classification": classification,
                "opening_balance": float(opening_balance),
                "active": True,
                "created_at": "2026-10-03T00:00:00Z",
                "parent_id": parent_id,
            }
            self.records.append(record)
            return dict(record)

        def update(self, account_id, *, changes):
            record = next(item for item in self.records if item["id"] == account_id)
            record.update(changes)
            return dict(record)

    repository = AccountRepository()

    def compose(profile_key, secrets):
        application = create_sheets_application(profile_key, secrets)
        return replace(application, services=replace(
            application.services, accounts=AccountService(repository)
        ))

    storage = GoogleSheetsStorage(FakeWorkbook())
    with (
        patch("tabula_rasa.composition.create_sheets_application", side_effect=compose),
        authenticated_app(storage) as app,
        patch.object(storage, "list_accounts", side_effect=AssertionError("Reference read bypassed service")),
        patch.object(storage, "create_account", side_effect=AssertionError("Reference create bypassed service")),
        patch.object(storage, "edit_account", side_effect=AssertionError("Reference update bypassed service")),
        patch.object(storage, "list_transactions", return_value=[]),
        patch.object(storage, "list_journal_entries", return_value=[]),
    ):
        navigate_to(app, "Accounts")
        by_label(app.text_input, "Account name").set_value("Service checking")
        by_label(app.button, "Add account").click().run()
        assert not app.exception
        assert any(str(item.value) == "Account added." for item in app.success)
        assert repository.records[0]["name"] == "Service checking"

        by_label(app.text_input, "Edit account name").set_value("Renamed through service")
        by_label(app.checkbox, "Active").uncheck()
        by_label(app.button, "Save account changes").click().run()
        assert not app.exception
        assert any(str(item.value) == "Account updated." for item in app.success)
        assert repository.records[0]["name"] == "Renamed through service"
        assert repository.records[0]["active"] is False


def test_every_page_receives_selected_profile_services_and_shared_legacy_storage() -> None:
    north_storage = GoogleSheetsStorage(FakeWorkbook())
    north_storage._workbook.title = "North Ledger"
    south_storage = GoogleSheetsStorage(FakeWorkbook())
    south_storage._workbook.title = "South Ledger"
    storages = {"north-sheet": north_storage, "south-sheet": south_storage}
    profiles = {
        "north": profile_config(name="North", spreadsheet_id="north-sheet"),
        "south": profile_config(name="South", spreadsheet_id="south-sheet"),
    }

    with ExitStack() as stack:
        rendered = {
            page: stack.enter_context(
                patch(f"tabula_rasa.page_renderers.{renderer}")
            )
            for page, renderer in PAGE_RENDERERS.items()
        }
        compose = stack.enter_context(
            patch(
                "tabula_rasa.composition.create_sheets_application",
                wraps=create_sheets_application,
            )
        )
        app = stack.enter_context(
            authenticated_app(storages=storages, profiles=profiles)
        )
        services_by_profile: dict[str, ApplicationServices] = {}
        for profile_key, expected_storage, expected_name in (
            ("north", north_storage, "North Ledger"),
            ("south", south_storage, "South Ledger"),
            ("north", north_storage, "North Ledger"),
        ):
            by_label(app.selectbox, "Business").set_value(profile_key).run()
            for page in PAGE_RENDERERS:
                navigate_to(app, page)
                assert not app.exception
                context = rendered[page].call_args.args[0]
                assert context.profile_key == profile_key
                assert context.storage is expected_storage
                assert context.services.profile_key == profile_key
                assert context.services.ledger.get_info().name == expected_name
                if profile_key in services_by_profile:
                    assert context.services is services_by_profile[profile_key]
                else:
                    services_by_profile[profile_key] = context.services
                assert f"Workbook: {expected_name}" in {
                    str(caption.value) for caption in app.caption
                }

        assert services_by_profile["north"] is not services_by_profile["south"]
        assert compose.call_count == 2
        assert [call.args[0] for call in compose.call_args_list] == ["north", "south"]


def test_configuration_revision_rebuilds_selected_profile_services() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    with (
        patch("tabula_rasa.page_renderers.dashboard.render_dashboard") as render,
        patch(
            "tabula_rasa.composition.create_sheets_application",
            wraps=create_sheets_application,
        ) as compose,
        patch(
            "tabula_rasa.local_profile_store.local_profile_revision",
            return_value="configuration-1",
        ) as revision,
        authenticated_app(storage) as app,
    ):
        original_services = render.call_args.args[0].services
        app.run()
        assert render.call_args.args[0].services is original_services
        revision.return_value = "configuration-2"
        app.run()

        assert not app.exception
        refreshed_context = render.call_args.args[0]
        assert refreshed_context.services is not original_services
        assert refreshed_context.services.profile_key == "test"
        assert refreshed_context.storage is storage
        assert compose.call_count == 2


def test_nested_transaction_context_receives_selected_profile_services() -> None:
    storages = {
        f"{key}-sheet": GoogleSheetsStorage(FakeWorkbook())
        for key in ("north", "south")
    }
    profiles = {
        key: profile_config(name=key.title(), spreadsheet_id=f"{key}-sheet")
        for key in ("north", "south")
    }
    with (
        patch(
            "tabula_rasa.page_renderers.transactions.renderer.render_payees_tags"
        ) as render,
        authenticated_app(storages=storages, profiles=profiles) as app,
    ):
        navigate_to(app, "Transactions")
        for profile_key in ("north", "south"):
            by_label(app.selectbox, "Business").set_value(profile_key).run()
            assert not app.exception
            context = render.call_args.args[0]
            assert context.profile_key == profile_key
            assert context.services.profile_key == profile_key
            assert context.storage is storages[f"{profile_key}-sheet"]


def test_unauthenticated_app_does_not_assemble_profile_services() -> None:
    with patch("tabula_rasa.composition.create_sheets_application") as compose:
        app = build_app_test()
        app.run()

    assert not app.exception
    compose.assert_not_called()


@pytest.mark.parametrize("failure", [StorageUnavailableError, BusinessProfileConfigurationError])
def test_service_assembly_failure_stops_before_page_rendering(failure) -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    safe_message = "The selected ledger is temporarily unavailable."
    with (
        patch("tabula_rasa.page_renderers.dashboard.render_dashboard") as render,
        patch(
            "tabula_rasa.composition.create_sheets_application",
            side_effect=failure(safe_message),
        ),
        authenticated_app(storage) as app,
    ):
        assert not app.exception
        expected = (
            safe_message if failure is StorageUnavailableError
            else "The business-profile configuration is invalid or changed. "
            "Reload the app and check the selected profile settings."
        )
        assert expected in {str(error.value) for error in app.error}
        render.assert_not_called()


def test_assembly_and_renderers_share_one_snapshot_and_cache_rebuilds_on_change() -> None:
    storages = {
        f"{key}-sheet": GoogleSheetsStorage(FakeWorkbook())
        for key in ("north", "south", "replacement")
    }
    profiles = {
        key: profile_config(name=key.title(), spreadsheet_id=f"{key}-sheet")
        for key in ("north", "south")
    }
    original = {"business_profiles": profiles}
    replacement = profile_config(name="North", spreadsheet_id="replacement-sheet")
    replacement["google_drive"] = {**profiles["north"]["google_drive"], "receipt_folder": {"id": "new-folder"}}
    updated = {"business_profiles": {"north": replacement, "south": profiles["south"]}}
    with (
        patch("tabula_rasa.page_renderers.transactions.render_transactions") as render,
        patch("tabula_rasa.page_renderers.data_backup.render_data_backup") as backup_render,
        patch("tabula_rasa.google_drive.GoogleDriveClient", side_effect=lambda config, settings: dict(settings)) as drive_factory,
        patch("tabula_rasa.google_drive.load_oauth_config", return_value=object()),
        patch(
            "tabula_rasa.local_profile_store.merged_profile_secrets",
            return_value=original,
        ) as configuration,
        patch("tabula_rasa.local_profile_store.local_profile_revision", return_value="same-revision"),
        patch("tabula_rasa.composition.create_sheets_application", wraps=create_sheets_application) as compose,
        authenticated_app(storages=storages, profiles=profiles) as app,
    ):
        def change_during_assembly(key, snapshot):
            configuration.return_value = updated
            return create_sheets_application(key, snapshot)

        # Rebuild the graph while simulating a settings replacement after the
        # shell has loaded its snapshot. Assembly must not read it again.
        st.cache_resource.clear()
        compose.side_effect = change_during_assembly
        reads = configuration.call_count
        navigate_to(app, "Transactions")
        assert not app.exception
        assert configuration.call_count == reads + 1
        context = render.call_args.args[0]
        assert context.storage is storages["north-sheet"]
        assert context.services.profile_key == "north"
        assert context.profile_secrets["spreadsheet_id"] == "north-sheet"
        assert context.profile_secrets["google_drive"] == profiles["north"]["google_drive"]
        # Lazy Drive creation must retain the original snapshot even though
        # the next configuration read would now return replacement settings.
        original_drive = context.get_drive_client("north", context.configuration_revision)
        assert original_drive == profiles["north"]["google_drive"]
        assert context.get_drive_client("north", context.configuration_revision) is original_drive
        assert configuration.call_count == reads + 1
        old_revision = context.configuration_revision
        old_exports = prepared_exports_key("north", old_revision, 0)
        app.session_state[old_exports] = {"synthetic": b"old workbook"}
        before = context.services
        calls = compose.call_count
        app.run()
        assert not app.exception
        changed = render.call_args.args[0]
        assert changed.storage is storages["replacement-sheet"]
        assert changed.profile_secrets["google_drive"] == replacement["google_drive"]
        assert changed.services is not before
        assert compose.call_count == calls + 1
        assert changed.configuration_revision != old_revision
        changed_drive = changed.get_drive_client("north", changed.configuration_revision)
        assert changed_drive == replacement["google_drive"]
        assert changed_drive is not original_drive
        assert drive_factory.call_count == 2
        assert storages["replacement-sheet"].list_accounts()
        assert storages["replacement-sheet"].list_categories()
        navigate_to(app, "Data & backup")
        backup = backup_render.call_args.args[0]
        assert backup.storage is storages["replacement-sheet"]
        new_exports = prepared_exports_key("north", backup.configuration_revision, 0)
        assert new_exports != old_exports
        assert new_exports not in app.session_state
        assert backup.get_drive_client("north", backup.configuration_revision) is changed_drive
        manifest = Mock(return_value={"synthetic": "manifest"})
        with patch.dict(backup.receipt_manifest_for_backup.func.__globals__, prepare_backup_receipt_manifest=manifest):
            result = backup.receipt_manifest_for_backup(
                backup.storage, profile_key="north", drive_settings=backup.drive_settings,
                configuration_revision=backup.configuration_revision,
            )
        assert result == {"synthetic": "manifest"}
        assert manifest.call_args.args == (backup.storage, changed_drive)
        assert manifest.call_args.kwargs["folder_id"] == "new-folder"
        assert storages["south-sheet"].list_accounts() == []
