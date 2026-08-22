from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_ADMIN_ENV,
    build_profile_settings,
    load_local_profiles,
    save_local_profile,
    update_local_profile_google_drive,
)
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook

TEST_PASSWORD = "test-password-123"


def select_account_settings(app: AppTest) -> None:
    """Select the utility-area settings destination."""
    settings_navigation = next(
        button for button in app.button if button.label == "Account settings"
    )
    settings_navigation.click().run()


def profile_settings(name: str, spreadsheet_id: str) -> dict:
    credential = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key": (
            "-----BEGIN PRIVATE KEY-----\n"
            "test-private-key\n"
            "-----END PRIVATE KEY-----\n"
        ),
        "client_email": "ledger@test-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return build_profile_settings(
        name,
        spreadsheet_id,
        json.dumps(credential).encode("utf-8"),
    )


class TestAppAuthentication:
    def test_hosted_streamlit_secrets_work_without_local_profile_file(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ) as from_secrets,
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "hosted": {
                        "name": "Hosted Business",
                        "spreadsheet_id": "hosted-sheet-id",
                        "gcp_service_account": {"type": "service_account"},
                    }
                }

                app.run()
                assert len(app.exception) == 0
                assert app.text_input[0].label == "Password"
                assert len(app.radio) == 0, "Navigation must be blocked before login"

                app.text_input[0].input("incorrect-password")
                app.button[0].click().run()
                assert app.error[0].value == "Incorrect password."
                assert len(app.radio) == 0

                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()
                assert len(app.exception) == 0
                assert app.radio[0].label == "Navigate"
                assert "Business profiles" not in app.radio[0].options
                assert any(
                    item.value == "Project Tabula Rasa" for item in app.title
                )
                assert len(app.metric) == 4
                assert len(app.dataframe) >= 1
                dashboard_frames = [frame.value for frame in app.dataframe]
                assert any(
                    list(frame.columns)
                    == ["Account", "Classification", "Type", "Balance"]
                    for frame in dashboard_frames
                )
                assert any(
                    "No transactions yet" in str(item.value) for item in app.info
                )
                assert (
                    from_secrets.call_args.args[0]["spreadsheet_id"]
                    == "hosted-sheet-id"
                )

                logout_button = next(
                    button for button in app.button if button.label == "Log out"
                )
                logout_button.click().run()
                assert app.text_input[0].label == "Password"
                assert "authenticated" not in app.session_state

    def test_zero_profile_local_admin_never_initializes_ledger_storage(self) -> None:
        st.cache_resource.clear()
        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch.dict(
                    os.environ,
                    {LOCAL_PROFILE_ADMIN_ENV: "1"},
                    clear=False,
                ),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "127.0.0.1" if name == "server.address" else None
                    ),
                ),
                patch.object(GoogleSheetsStorage, "from_secrets") as from_secrets,
            ):
                app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                assert len(app.exception) == 0
                assert any(
                    button.label == "Account settings" for button in app.button
                )
                assert not any(
                    "No application page is available" in str(item.value)
                    for item in app.error
                )
                assert any(
                    field.label == "Application password" for field in app.text_input
                )
                from_secrets.assert_not_called()

                next(
                    field
                    for field in app.text_input
                    if field.label == "Application password"
                ).input(TEST_PASSWORD)
                next(
                    button
                    for button in app.button
                    if button.label == "Unlock profile administration"
                ).click().run()

                assert app.file_uploader[0].label == "Google service-account JSON"
                assert not app.tabs
                assert not any(
                    checkbox.label
                    == "Maintain an optional Synology recovery copy for this business"
                    for checkbox in app.checkbox
                )

    def test_stale_account_settings_route_fails_closed_when_local_admin_is_disabled(
        self,
    ) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch.dict(os.environ, {LOCAL_PROFILE_ADMIN_ENV: ""}, clear=False),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "0.0.0.0" if name == "server.address" else None
                    ),
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ),
                patch.object(
                    st,
                    "session_state",
                    {"navigation_page": "Account settings"},
                ),
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "hosted": {
                        "name": "Hosted Business",
                        "spreadsheet_id": "hosted-sheet-id",
                        "gcp_service_account": {"type": "service_account"},
                    }
                }

                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                assert len(app.exception) == 0
                assert app.radio[0].options[0] == "Dashboard"
                assert not any(
                    button.label == "Account settings" for button in app.button
                )

    def test_hosted_missing_profile_configuration_fails_closed(self) -> None:
        st.cache_resource.clear()
        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch.dict(
                    os.environ,
                    {LOCAL_PROFILE_ADMIN_ENV: ""},
                    clear=False,
                ),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "0.0.0.0" if name == "server.address" else None
                    ),
                ),
                patch.object(GoogleSheetsStorage, "from_secrets") as from_secrets,
            ):
                app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                assert len(app.radio) == 0
                assert any("business profile" in str(item.value).lower() for item in app.error)
                from_secrets.assert_not_called()

    def test_profile_switch_rebuilds_visible_business_and_workbook_context(self) -> None:
        st.cache_resource.clear()
        north_storage = GoogleSheetsStorage(FakeWorkbook())
        north_storage._workbook.title = "North Ledger"
        south_storage = GoogleSheetsStorage(FakeWorkbook())
        south_storage._workbook.title = "South Ledger"
        north = profile_settings("North Shop", "north-sheet-id")
        south = profile_settings("South Shop", "south-sheet-id")

        def storage_for_profile(settings: dict) -> GoogleSheetsStorage:
            return {
                "north-sheet-id": north_storage,
                "south-sheet-id": south_storage,
            }[settings["spreadsheet_id"]]

        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    side_effect=storage_for_profile,
                ) as from_secrets,
            ):
                app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "north": north,
                    "south": south,
                }
                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                assert any("North Shop" in str(item.value) for item in app.caption)
                assert any("North Ledger" in str(item.value) for item in app.caption)
                app.selectbox[0].set_value("south").run()

                assert app.session_state["previous_business_profile"] == "south"
                assert any("South Shop" in str(item.value) for item in app.caption)
                assert any("South Ledger" in str(item.value) for item in app.caption)
                assert from_secrets.call_args.args[0]["spreadsheet_id"] == "south-sheet-id"

    def test_split_local_secrets_and_profile_json_work_together(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            local_store = Path(directory) / "business_profiles.json"
            save_local_profile(
                "local",
                profile_settings("Local Business", "local-sheet-id"),
                path=local_store,
            )
            with (
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ) as from_secrets,
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                assert len(app.exception) == 0
                assert app.radio[0].label == "Navigate"
                assert (
                    from_secrets.call_args.args[0]["spreadsheet_id"] == "local-sheet-id"
                )

    def test_local_admin_page_requires_flag_and_reauthentication(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            local_store = Path(directory) / "local_business_profiles.json"
            with (
                patch.dict(
                    os.environ,
                    {LOCAL_PROFILE_ADMIN_ENV: "1"},
                    clear=False,
                ),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "127.0.0.1" if name == "server.address" else None
                    ),
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ),
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "test": {
                        "name": "Test Business",
                        "spreadsheet_id": "test-sheet",
                        "gcp_service_account": {"type": "service_account"},
                    }
                }

                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()
                assert any(
                    button.label == "Account settings" for button in app.button
                )
                assert "operational_navigation_page" not in app.session_state

                select_account_settings(app)
                assert app.session_state["active_page"] == "Account settings"
                next(
                    radio for radio in app.radio if radio.label == "Navigate"
                ).set_value("Transactions").run()
                assert app.session_state["navigation_page"] == "Transactions"
                assert app.session_state["active_page"] == "Transactions"
                assert not any(
                    field.label == "Application password" for field in app.text_input
                )

                select_account_settings(app)
                assert any(
                    field.label == "Application password" for field in app.text_input
                )
                assert len(app.file_uploader) == 0

                next(
                    field
                    for field in app.text_input
                    if field.label == "Application password"
                ).input(TEST_PASSWORD)
                next(
                    button
                    for button in app.button
                    if button.label == "Unlock profile administration"
                ).click().run()

                assert app.file_uploader[0].label == "Google service-account JSON"

                next(
                    field for field in app.text_input if field.label == "Business name"
                ).input("North Shop")
                next(
                    field for field in app.text_input if field.label == "Profile key"
                ).input("north")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Google Sheets URL or spreadsheet ID"
                ).input("abcdefghij1234567890")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Optional local backup folder path"
                ).input(r"G:\My Drive\Project Tabula Rasa Backups\north")
                next(
                    button
                    for button in app.button
                    if button.label == "Validate and save"
                ).click().run()
                assert any(
                    "Upload the Google service-account JSON" in str(item.value)
                    for item in app.error
                )
                assert (
                    next(
                        field
                        for field in app.text_input
                        if field.label == "Business name"
                    ).value
                    == "North Shop"
                )
                assert (
                    next(
                        field
                        for field in app.text_input
                        if field.label == "Profile key"
                    ).value
                    == "north"
                )
                assert (
                    next(
                        field
                        for field in app.text_input
                        if field.label == "Google Sheets URL or spreadsheet ID"
                    ).value
                    == "abcdefghij1234567890"
                )
                credential = {
                    "type": "service_account",
                    "project_id": "test-project",
                    "private_key": (
                        "-----BEGIN PRIVATE KEY-----\n"
                        "credential-content-must-not-leak\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                    "client_email": "ledger@test-project.iam.gserviceaccount.com",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
                app.file_uploader[0].set_value(
                    (
                        "service-account.json",
                        json.dumps(credential).encode("utf-8"),
                        "application/json",
                    )
                )
                next(
                    button
                    for button in app.button
                    if button.label == "Validate and save"
                ).click().run()

                assert load_local_profiles(local_store)["north"]["name"] == "North Shop"
                assert any(
                    "validated and saved locally" in str(item.value)
                    for item in app.success
                )

    def test_local_admin_edit_forms_are_unique_per_profile(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            local_store = Path(directory) / "local_business_profiles.json"
            north = profile_settings("North Shop", "north-spreadsheet-id")
            south = profile_settings("South Shop", "south-spreadsheet-id")
            save_local_profile("north", north, path=local_store)
            save_local_profile("south", south, path=local_store)
            with (
                patch.dict(
                    os.environ,
                    {LOCAL_PROFILE_ADMIN_ENV: "1"},
                    clear=False,
                ),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "127.0.0.1" if name == "server.address" else None
                    ),
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ),
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "north": north,
                    "south": south,
                }

                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()
                select_account_settings(app)
                next(
                    field
                    for field in app.text_input
                    if field.label == "Application password"
                ).input(TEST_PASSWORD)
                next(
                    button
                    for button in app.button
                    if button.label == "Unlock profile administration"
                ).click().run()

                assert [tab.label for tab in app.tabs] == [
                    "Business profiles",
                    "Google Drive storage",
                    "Recovery",
                    "Security & deployment information",
                ]
                assert len(app.exception) == 0
                assert sum(
                    field.label == "Business name" for field in app.text_input
                ) == 2

    def test_local_admin_saves_optional_synology_choice_per_profile(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            local_store = Path(directory) / "local_business_profiles.json"
            save_local_profile(
                "north",
                profile_settings("North Shop", "north-spreadsheet-id"),
                path=local_store,
            )
            update_local_profile_google_drive(
                "north",
                {
                    "authorized_email": "north@example.test",
                    "authorized_name": "North Owner",
                    "refresh_token": "refresh-token",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": ["https://www.googleapis.com/auth/drive.file"],
                    "storage_root": {
                        "id": "rootfolder123",
                        "name": "North Storage",
                    },
                    "backup_folder": {
                        "id": "backupfolder123",
                        "name": "North Backups",
                    },
                    "receipt_folder": {
                        "id": "receiptfolder123",
                        "name": "North Receipts",
                    },
                },
                path=local_store,
            )
            with (
                patch.dict(
                    os.environ,
                    {LOCAL_PROFILE_ADMIN_ENV: "1"},
                    clear=False,
                ),
                patch(
                    "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "127.0.0.1" if name == "server.address" else None
                    ),
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ),
            ):
                app = AppTest.from_file(
                    "tabula_rasa/app.py",
                    default_timeout=30,
                )
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["synology_recovery_defaults"] = {
                    "base_path": "/volume2/Recovery",
                    "schedule": "Nightly",
                    "retention_policy": "Keep quarterly versions.",
                }

                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()
                select_account_settings(app)
                next(
                    field
                    for field in app.text_input
                    if field.label == "Application password"
                ).input(TEST_PASSWORD)
                next(
                    button
                    for button in app.button
                    if button.label == "Unlock profile administration"
                ).click().run()

                next(
                    checkbox
                    for checkbox in app.checkbox
                    if checkbox.label
                    == "Maintain an optional Synology recovery copy for this business"
                ).check()
                assert not any(
                    field.label == "Cloud Sync layout" for field in app.radio
                )
                assert next(
                    field
                    for field in app.text_input
                    if field.label == "NAS destination path"
                ).value == "/volume2/Recovery/north"
                assert next(
                    field
                    for field in app.text_input
                    if field.label == "Cloud Sync schedule"
                ).value == "Nightly"
                assert next(
                    field
                    for field in app.text_area
                    if field.label == "NAS retention policy"
                ).value == "Keep quarterly versions."
                next(
                    field
                    for field in app.text_input
                    if field.label == "NAS destination path"
                ).input("/volume1/Backups/TabulaRasa/north")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Cloud Sync schedule"
                ).input("Daily at 11:00 PM")
                next(
                    field
                    for field in app.text_area
                    if field.label == "NAS retention policy"
                ).input("Retain all generations until manual review.")
                next(
                    button
                    for button in app.button
                    if button.label == "Save Synology recovery choice"
                ).click().run()

                recovery = load_local_profiles(local_store)["north"][
                    "synology_recovery"
                ]
                assert recovery["layout"] == "profile-root"
                assert recovery["destination_path"].endswith("/north")
                assert recovery["schedule"] == "Daily at 11:00 PM"
                assert any(
                    "Synology recovery was enabled" in str(item.value)
                    for item in app.success
                )
