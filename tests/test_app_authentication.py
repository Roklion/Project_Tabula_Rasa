from __future__ import annotations

import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password
from storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


class AppAuthenticationTests(unittest.TestCase):
    def test_unauthorized_login_success_and_logout(self) -> None:
        st.cache_resource.clear()
        app = AppTest.from_file("app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
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

            logout_button = next(
                button for button in app.button if button.label == "Log out"
            )
            logout_button.click().run()
            self.assertEqual(app.text_input[0].label, "Password")
            self.assertNotIn("authenticated", app.session_state)


if __name__ == "__main__":
    unittest.main()
