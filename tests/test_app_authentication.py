from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password


TEST_PASSWORD = "test-password-123"


class AppAuthenticationTests(unittest.TestCase):
    def test_unauthorized_login_success_and_logout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, patch.dict(
            os.environ,
            {"LEDGER_DB_PATH": str(Path(temporary_directory) / "ledger.db")},
        ):
            app = AppTest.from_file("app.py", default_timeout=30)
            app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)

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
