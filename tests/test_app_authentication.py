from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password
from local_profile_store import (
    LOCAL_PROFILE_ADMIN_ENV,
    build_profile_settings,
    load_local_profiles,
    save_local_profile,
)
from storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


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


class AppAuthenticationTests(unittest.TestCase):
    def test_hosted_streamlit_secrets_work_without_local_profile_file(self) -> None:
        st.cache_resource.clear()
        fake_storage = GoogleSheetsStorage(FakeWorkbook())
        with tempfile.TemporaryDirectory() as directory:
            absent_local_store = Path(directory) / "business_profiles.json"
            with (
                patch(
                    "local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    absent_local_store,
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ) as from_secrets,
            ):
                app = AppTest.from_file("app.py", default_timeout=30)
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
                app.secrets["business_profiles"] = {
                    "hosted": {
                        "name": "Hosted Business",
                        "spreadsheet_id": "hosted-sheet-id",
                        "gcp_service_account": {"type": "service_account"},
                    }
                }

                app.run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.text_input[0].label, "Password")
                self.assertEqual(
                    len(app.radio),
                    0,
                    "Navigation must be blocked before login",
                )

                app.text_input[0].input("incorrect-password")
                app.button[0].click().run()
                self.assertEqual(app.error[0].value, "Incorrect password.")
                self.assertEqual(len(app.radio), 0)

                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.radio[0].label, "Navigate")
                self.assertNotIn("Business profiles", app.radio[0].options)
                self.assertEqual(
                    from_secrets.call_args.args[0]["spreadsheet_id"],
                    "hosted-sheet-id",
                )

                logout_button = next(
                    button for button in app.button if button.label == "Log out"
                )
                logout_button.click().run()
                self.assertEqual(app.text_input[0].label, "Password")
                self.assertNotIn("authenticated", app.session_state)

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
                    "local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ) as from_secrets,
            ):
                app = AppTest.from_file("app.py", default_timeout=30)
                app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)

                app.run()
                app.text_input[0].input(TEST_PASSWORD)
                app.button[0].click().run()

                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.radio[0].label, "Navigate")
                self.assertEqual(
                    from_secrets.call_args.args[0]["spreadsheet_id"],
                    "local-sheet-id",
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
                    "local_profile_store.LOCAL_PROFILE_STORE_PATH",
                    local_store,
                ),
                patch.object(
                    st,
                    "get_option",
                    side_effect=lambda name: (
                        "127.0.0.1"
                        if name == "server.address"
                        else None
                    ),
                ),
                patch.object(
                    GoogleSheetsStorage,
                    "from_secrets",
                    return_value=fake_storage,
                ),
            ):
                app = AppTest.from_file("app.py", default_timeout=30)
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
                self.assertIn("Business profiles", app.radio[0].options)

                app.radio[0].set_value("Business profiles").run()
                self.assertTrue(
                    any(
                        field.label == "Application password"
                        for field in app.text_input
                    )
                )
                self.assertEqual(len(app.file_uploader), 0)

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

                self.assertEqual(
                    app.file_uploader[0].label,
                    "Google service-account JSON",
                )

                next(
                    field
                    for field in app.text_input
                    if field.label == "Business name"
                ).input("North Shop")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Profile key"
                ).input("north")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Google Sheets URL or spreadsheet ID"
                ).input("abcdefghij1234567890")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Google Drive Desktop backup folder path"
                ).input(r"G:\My Drive\Tabula Rosa Backups\north")
                next(
                    button
                    for button in app.button
                    if button.label == "Validate and save"
                ).click().run()
                self.assertTrue(
                    any(
                        "Upload the Google service-account JSON" in str(item.value)
                        for item in app.error
                    )
                )
                self.assertEqual(
                    next(
                        field
                        for field in app.text_input
                        if field.label == "Business name"
                    ).value,
                    "North Shop",
                )
                self.assertEqual(
                    next(
                        field
                        for field in app.text_input
                        if field.label == "Profile key"
                    ).value,
                    "north",
                )
                self.assertEqual(
                    next(
                        field
                        for field in app.text_input
                        if field.label
                        == "Google Sheets URL or spreadsheet ID"
                    ).value,
                    "abcdefghij1234567890",
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

                self.assertEqual(
                    load_local_profiles(local_store)["north"]["name"],
                    "North Shop",
                )
                self.assertTrue(
                    any(
                        "validated and saved locally" in str(item.value)
                        for item in app.success
                    )
                )


if __name__ == "__main__":
    unittest.main()
