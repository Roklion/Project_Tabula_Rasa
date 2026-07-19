from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password
from storage import GoogleSheetsStorage, StorageUnavailableError


TEST_PASSWORD = "test-password-123"
SAFE_MESSAGE = "Google Sheets is temporarily unavailable; no success was reported"


class AppStorageFailureTests(unittest.TestCase):
    def test_availability_error_is_safe_and_blocks_data_pages(self) -> None:
        st.cache_resource.clear()
        unavailable_storage = Mock(spec=GoogleSheetsStorage)
        unavailable_storage.ensure_defaults.side_effect = StorageUnavailableError(
            SAFE_MESSAGE
        )
        app = AppTest.from_file("app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)

        with patch.object(
            GoogleSheetsStorage,
            "from_secrets",
            return_value=unavailable_storage,
        ):
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.error[0].value, SAFE_MESSAGE)
        self.assertEqual(len(app.success), 0)
        self.assertEqual(len(app.radio), 0)


if __name__ == "__main__":
    unittest.main()
