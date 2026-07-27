from __future__ import annotations

from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError

TEST_PASSWORD = "test-password-123"
SAFE_MESSAGE = "Google Sheets is temporarily unavailable; no success was reported"


class TestAppStorageFailure:
    def test_availability_error_is_safe_and_blocks_data_pages(self) -> None:
        st.cache_resource.clear()
        unavailable_storage = Mock(spec=GoogleSheetsStorage)
        unavailable_storage.ensure_defaults.side_effect = StorageUnavailableError(
            SAFE_MESSAGE
        )
        app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
        app.secrets["business_profiles"] = {
            "test": {
                "name": "Test Business",
                "spreadsheet_id": "test-sheet",
                "gcp_service_account": {"type": "service_account"},
            }
        }

        with patch.object(
            GoogleSheetsStorage,
            "from_secrets",
            return_value=unavailable_storage,
        ):
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()

        assert len(app.exception) == 0
        assert app.error[0].value == SAFE_MESSAGE
        assert len(app.success) == 0
        assert app.radio[0].label == "Navigate"
        assert len(app.metric) == 0
