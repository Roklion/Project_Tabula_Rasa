from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest

import tabula_rasa.local_profile_admin as local_profile_admin
from tabula_rasa.local_profile_admin import (
    _initialize_candidate_storage,
    _profile_rows,
    _profile_setup_error_message,
    _validate_profile_edit_action,
)
from tabula_rasa.local_profile_store import LocalProfileStoreError
from tabula_rasa.storage import (
    StorageAuthenticationError,
    StorageInitializationError,
    StorageError,
    StorageValidationError,
    StorageWorkbookAccessError,
)
from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
    GoogleDriveConfigurationError,
)


SETTINGS = {
    "spreadsheet_id": "abcdefghij1234567890",
    "gcp_service_account": {
        "client_email": "ledger@example.test",
        "private_key": "credential-content-must-not-leak",
    },
}


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (
            StorageAuthenticationError("safe"),
            "Service-account authentication failed",
        ),
        (
            StorageWorkbookAccessError("safe"),
            "Workbook access failed",
        ),
        (
            StorageInitializationError("safe"),
            "workbook opened, but initialization failed",
        ),
        (
            StorageValidationError("Accounts is missing headers: id"),
            "Accounts is missing headers: id",
        ),
    ),
)
def test_profile_setup_error_identifies_stage_without_exposing_secrets(
    error: Exception,
    expected: str,
) -> None:
    message = _profile_setup_error_message(error, SETTINGS)

    assert expected.casefold() in message.casefold()
    assert "…34567890" in message
    assert "ledger@example.test" in message
    assert SETTINGS["spreadsheet_id"] not in message
    assert "credential-content-must-not-leak" not in message
    assert message.endswith("No profile was saved.")


def test_profile_edit_rejects_a_credential_upload_on_settings_save() -> None:
    with pytest.raises(LocalProfileStoreError, match="rotate credential"):
        _validate_profile_edit_action(True, False, object())

    with pytest.raises(LocalProfileStoreError, match="Upload a replacement"):
        _validate_profile_edit_action(False, True, None)


def test_profile_rows_use_a_safe_fallback_for_null_backup_paths() -> None:
    rows = _profile_rows(
        {
            "business_profiles": {
                "north": {
                    **SETTINGS,
                    "name": "North Shop",
                    "backup_folder_path": None,
                }
            }
        },
        {"north": {}},
    )

    assert rows[0]["Local backup folder"] == "Not configured"


@pytest.mark.parametrize(
    "error",
    (StorageWorkbookAccessError("access"), StorageValidationError("invalid")),
)
def test_candidate_storage_preserves_specific_storage_errors(
    error: StorageError,
) -> None:
    candidate = Mock()
    candidate.ensure_defaults.side_effect = error
    with patch(
        "tabula_rasa.local_profile_admin.GoogleSheetsStorage.from_secrets",
        return_value=candidate,
    ):
        with pytest.raises(type(error)) as raised:
            _initialize_candidate_storage(SETTINGS)

    assert raised.value is error


def test_profile_root_enablement_revalidates_drive_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    north_root = {
        "id": "northroot123",
        "name": "North Storage",
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
        "parents": ["southroot123"],
    }
    south_root = {
        "id": "southroot123",
        "name": "South Storage",
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
    }

    class Client:
        def __init__(self, folders: dict[str, dict[str, Any]]) -> None:
            self.folders = folders

        def folder(self, folder_id: str) -> dict[str, Any]:
            return self.folders[folder_id]

    client = Client({"northroot123": north_root, "southroot123": south_root})
    monkeypatch.setattr(local_profile_admin, "load_oauth_config", lambda _secrets: object())
    monkeypatch.setattr(
        local_profile_admin,
        "GoogleDriveClient",
        lambda _config, _settings: client,
    )

    profiles = {
        "north": {
            "google_drive": {
                "authorized_email": "same@example.com",
                "storage_root": {"id": "northroot123", "name": "North Storage"},
            }
        },
        "south": {
            "google_drive": {
                "authorized_email": "same@example.com",
                "storage_root": {"id": "southroot123", "name": "South Storage"},
            }
        },
    }

    with pytest.raises(GoogleDriveConfigurationError, match="cannot be nested"):
        local_profile_admin._validate_profile_root_storage_root(
            {},
            "north",
            profiles,
        )


def test_profile_root_enablement_requires_current_storage_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = {
        "id": "northroot123",
        "name": "North Storage",
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
        "appProperties": {
            "tabulaRasaKind": "storage-root",
            "tabulaRasaProfile": "north",
        },
    }

    class Client:
        def folder(self, folder_id: str) -> dict[str, Any]:
            if folder_id == "northroot123":
                return root
            raise GoogleDriveAccessError("child unavailable")

    monkeypatch.setattr(local_profile_admin, "load_oauth_config", lambda _secrets: object())
    monkeypatch.setattr(
        local_profile_admin,
        "GoogleDriveClient",
        lambda _config, _settings: Client(),
    )

    profiles = {
        "north": {
            "google_drive": {
                "authorized_email": "north@example.com",
                "storage_root": {"id": "northroot123", "name": "North Storage"},
                "receipt_folder": {"id": "receiptchild123", "name": "Receipts"},
                "backup_folder": {
                    "id": "backupchild123",
                    "name": "Ledger Backups",
                },
            }
        }
    }

    with pytest.raises(GoogleDriveConfigurationError, match="both child folders"):
        local_profile_admin._validate_profile_root_storage_root(
            {},
            "north",
            profiles,
        )
