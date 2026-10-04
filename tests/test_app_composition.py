from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from tabula_rasa.application import AccountService
from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.composition import create_sheets_application
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
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


def test_service_assembly_failure_stops_before_page_rendering() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    safe_message = "The selected ledger is temporarily unavailable."
    with (
        patch("tabula_rasa.page_renderers.dashboard.render_dashboard") as render,
        patch(
            "tabula_rasa.composition.create_sheets_application",
            side_effect=StorageUnavailableError(safe_message),
        ),
        authenticated_app(storage) as app,
    ):
        assert not app.exception
        assert safe_message in {str(error.value) for error in app.error}
        render.assert_not_called()
