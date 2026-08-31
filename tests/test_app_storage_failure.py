from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.google_drive import GoogleDriveClient
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tests.app_support import authenticated_app, navigate_to
from tests.fakes import FakeWorkbook

TEST_PASSWORD = "test-password-123"
SAFE_MESSAGE = "Google Sheets is temporarily unavailable; no success was reported"


@pytest.fixture(autouse=True)
def isolate_local_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
        tmp_path / "business_profiles.json",
    )


class TestAppStorageFailure:
    @pytest.mark.parametrize(
        ("page", "failing_method"),
        [
            ("Mileage", "list_mileage_trips"),
            ("Transactions", "list_transactions"),
        ],
    )
    def test_tab_read_failure_keeps_one_page_scope_legal_footer(
        self,
        page: str,
        failing_method: str,
    ) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook())

        with authenticated_app(storage) as app:
            setattr(
                storage,
                failing_method,
                Mock(side_effect=StorageUnavailableError(SAFE_MESSAGE)),
            )
            navigate_to(app, page)

        markdown = [str(item.value) for item in app.markdown]
        footer = (
            "[Terms of Use](?legal=terms) | "
            "[Privacy Policy](?legal=privacy)"
        )
        assert len(app.exception) == 0
        assert any(error.value == SAFE_MESSAGE for error in app.error)
        assert markdown.count(footer) == 1

    def test_downloadable_backup_prepares_receipts_before_export(self) -> None:
        st.cache_resource.clear()
        storage = GoogleSheetsStorage(FakeWorkbook())
        app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
        app.secrets["google_drive_oauth"] = {
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "client-secret",
            "redirect_uris": ["https://tabula-rasa.streamlit.app/"],
            "picker_api_key": "picker-key",
            "project_number": "123456789",
        }
        app.secrets["business_profiles"] = {
            "test": {
                "name": "Test Business",
                "spreadsheet_id": "test-sheet",
                "gcp_service_account": {"type": "service_account"},
                "google_drive": {
                    "refresh_token": "refresh-token",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": ["https://www.googleapis.com/auth/drive.file"],
                    "storage_root": {
                        "id": "rootfolder123456",
                        "name": "Test Storage",
                    },
                    "receipt_folder": {
                        "id": "receiptsfolder123",
                        "name": "Receipts",
                    },
                },
            }
        }

        with (
            patch.object(
                GoogleSheetsStorage,
                "from_secrets",
                return_value=storage,
            ),
            patch.object(
                GoogleDriveClient,
                "list_profile_receipts",
                return_value=[],
            ) as list_receipts,
        ):
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()
            app.radio[0].set_value("Data & backup").run()
            next(
                button
                for button in app.button
                if button.label == "Prepare downloadable exports"
            ).click().run()

        assert list_receipts.call_count == 2
        list_receipts.assert_called_with(
            profile_key="test",
            folder_id="receiptsfolder123",
            _force_refresh=True,
        )
        assert any(
            success.value == "Fresh downloadable exports are ready."
            for success in app.success
        )

    def test_csv_exports_remain_available_without_a_receipt_folder(self) -> None:
        st.cache_resource.clear()
        storage = GoogleSheetsStorage(FakeWorkbook())
        app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
        app.secrets["business_profiles"] = {
            "test": {
                "name": "Test Business",
                "spreadsheet_id": "test-sheet",
                "gcp_service_account": {"type": "service_account"},
            }
        }

        with (
            patch.object(
                GoogleSheetsStorage,
                "from_secrets",
                return_value=storage,
            ),
            patch(
                "tabula_rasa.local_profile_store.load_local_profiles",
                return_value={},
            ),
        ):
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()
            app.radio[0].set_value("Data & backup").run()
            next(
                button
                for button in app.button
                if button.label == "Prepare downloadable exports"
            ).click().run()

        assert any(
            success.value == "Fresh CSV exports are ready."
            for success in app.success
        )
        assert any(
            "requires a selected Google Drive receipt folder" in warning.value
            for warning in app.warning
        )
        download_labels = {button.label for button in app.get("download_button")}
        assert "Download transactions CSV" in download_labels
        assert "Download mileage CSV" in download_labels
        assert "Download complete workbook backup" not in download_labels

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
        assert app.radio[0].label == "Workspace"
        assert len(app.metric) == 0

    def test_cloud_verification_does_not_require_live_sheets_export(self) -> None:
        st.cache_resource.clear()
        storage = GoogleSheetsStorage(FakeWorkbook())
        backup = storage.export_backup_zip(build_receipt_manifest("test", [], []))
        backup_name = "tabula-rasa-backup-20260728T120000Z.zip"
        unavailable_export = Mock(
            side_effect=StorageUnavailableError(SAFE_MESSAGE)
        )
        storage.export_backup_zip = unavailable_export
        cloud_backups = [
            {
                "id": "cloud-backup-id",
                "name": backup_name,
                "createdTime": "2026-07-28T12:00:00Z",
                "appProperties": {
                    "tabulaRasaSha256": hashlib.sha256(backup).hexdigest()
                },
            }
        ]
        download_file = Mock(return_value=backup)

        app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
        app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
        app.secrets["google_drive_oauth"] = {
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "client-secret",
            "redirect_uris": ["https://tabula-rasa.streamlit.app/"],
            "picker_api_key": "picker-key",
            "project_number": "123456789",
        }
        app.secrets["business_profiles"] = {
            "test": {
                "name": "Test Business",
                "spreadsheet_id": "test-sheet",
                "gcp_service_account": {"type": "service_account"},
                "google_drive": {
                    "refresh_token": "refresh-token",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": ["https://www.googleapis.com/auth/drive.file"],
                    "storage_root": {
                        "id": "rootfolder123456",
                        "name": "Test Storage",
                    },
                    "backup_folder": {
                        "id": "backupfolder123",
                        "name": "Backups",
                    },
                },
            }
        }

        with (
            patch.object(
                GoogleSheetsStorage,
                "from_secrets",
                return_value=storage,
            ),
            patch.object(
                GoogleDriveClient,
                "list_backups",
                return_value=cloud_backups,
            ),
            patch.object(
                GoogleDriveClient,
                "download_file",
                download_file,
            ),
        ):
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()
            app.radio[0].set_value("Data & backup").run()
            assert unavailable_export.call_count == 0

            next(
                button
                for button in app.button
                if button.label == "Verify latest cloud backup"
            ).click().run()

        assert unavailable_export.call_count == 0
        assert any(
            "Latest cloud backup downloaded and verified" in success.value
            for success in app.success
        )
        download_file.assert_called_once_with("cloud-backup-id")
