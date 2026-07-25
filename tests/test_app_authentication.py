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
    load_local_profiles,
)
from storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


class AppAuthenticationTests(unittest.TestCase):
    def test_unauthorized_login_success_and_logout(self) -> None:
        st.cache_resource.clear()
        app = AppTest.from_file("app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
        app.secrets["spreadsheet_id"] = "test-sheet"
        app.secrets["gcp_service_account"] = {"type": "service_account"}
        fake_storage = GoogleSheetsStorage(FakeWorkbook())

        with patch.object(
            GoogleSheetsStorage, "from_secrets", return_value=fake_storage
        ):
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input[0].label, "Password")
            self.assertEqual(len(app.radio), 0, "Navigation must be blocked before login")

            app.text_input[0].input("incorrect-password")
            app.button[0].click().run()
            self.assertEqual(app.error[0].value, "Incorrect password.")
            self.assertEqual(len(app.radio), 0)

            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.radio[0].label, "Navigate")
            self.assertNotIn("Business profiles", app.radio[0].options)

            logout_button = next(
                button for button in app.button if button.label == "Log out"
            )
            logout_button.click().run()
            self.assertEqual(app.text_input[0].label, "Password")
            self.assertNotIn("authenticated", app.session_state)

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
                app.secrets["spreadsheet_id"] = "test-sheet"
                app.secrets["gcp_service_account"] = {"type": "service_account"}

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
                    if field.label == "Google Drive receipt folder URL or folder ID"
                ).input("receiptfolder123456")
                next(
                    field
                    for field in app.text_input
                    if field.label == "Google Drive Desktop backup folder path"
                ).input(r"G:\My Drive\Tabula Rosa Backups\north")
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
