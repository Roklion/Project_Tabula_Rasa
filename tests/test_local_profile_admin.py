from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.local_profile_admin import (
    _initialize_candidate_storage,
    _profile_rows,
    _profile_setup_error_message,
    _fresh_profile_readiness,
    _readiness_for_display,
    _validate_profile_edit_action,
)
from tabula_rasa.profile_readiness import ProfileReadiness, profile_settings_fingerprint
from tabula_rasa.local_profile_store import LocalProfileStoreError
from tabula_rasa.storage import (
    StorageAuthenticationError,
    StorageInitializationError,
    StorageError,
    StorageValidationError,
    StorageWorkbookAccessError,
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


def test_profile_rows_allow_clean_install_without_hosted_profiles() -> None:
    assert _profile_rows({"app_password_hash": "configured"}, {}) == []


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


def test_fresh_readiness_reports_sheets_failure_without_secret_values() -> None:
    with patch(
        "tabula_rasa.local_profile_admin.GoogleSheetsStorage.from_secrets_read_only",
        side_effect=StorageWorkbookAccessError("contains no secret"),
    ), patch(
        "tabula_rasa.local_profile_admin.validate_google_drive_profile"
    ) as validate_drive:
        report = _fresh_profile_readiness(
            "north",
            {
                **SETTINGS,
                "name": "North Shop",
            },
            app_secrets={},
            hosted_profiles=None,
        )

    assert report.status == "incomplete"
    assert report.validation_errors == (
        "Sheets workbook validation failed. Confirm sharing and the workbook ID.",
    )
    validate_drive.assert_not_called()


def test_fresh_readiness_skips_drive_validation_without_a_storage_root() -> None:
    with patch(
        "tabula_rasa.local_profile_admin.GoogleSheetsStorage.from_secrets_read_only"
    ), patch(
        "tabula_rasa.local_profile_admin.validate_google_drive_profile"
    ) as validate_drive:
        report = _fresh_profile_readiness(
            "north",
            {
                **SETTINGS,
                "name": "North Shop",
                "google_drive": {"authorized_email": "owner@example.test"},
            },
            app_secrets={},
            hosted_profiles=None,
        )

    assert report.status == "incomplete"
    assert report.missing_steps == (
        "Select or create the Google Drive storage root.",
        "Provision the Receipts and Ledger Backups folders under the root.",
    )
    assert report.validation_errors == ()
    validate_drive.assert_not_called()


def test_fresh_readiness_uses_visible_drive_parent_ids_only() -> None:
    drive = {
        "storage_root": {"id": "northroot123", "name": "North Storage"},
        "receipt_folder": {"id": "receipts123", "name": "Receipts"},
        "backup_folder": {"id": "backups1234", "name": "Ledger Backups"},
    }
    settings = {**SETTINGS, "name": "North Shop", "google_drive": drive}
    local_profiles = {
        "north": settings,
        "south": {
            **SETTINGS,
            "name": "South Shop",
            "spreadsheet_id": "southsheet123",
            "google_drive": {
                "storage_root": {"id": "southroot123"},
            },
        },
    }
    with patch(
        "tabula_rasa.local_profile_admin.GoogleSheetsStorage.from_secrets_read_only"
    ), patch(
        "tabula_rasa.local_profile_admin.validate_google_drive_profile"
    ) as validate_drive:
        report = _fresh_profile_readiness(
            "north",
            settings,
            app_secrets={},
            hosted_profiles=None,
            local_profiles=local_profiles,
        )

    assert report.status == "ready-local"
    validate_drive.assert_called_once_with(
        {},
        "north",
        drive,
        local_profiles=local_profiles,
    )


def test_readiness_cache_is_ignored_after_profile_settings_change() -> None:
    original = {"name": "North Shop", **SETTINGS}
    changed = {**original, "backup_folder_path": r"G:\\Backups\\north"}
    cached = ProfileReadiness(status="ready-hosted")
    with patch.object(
        st,
        "session_state",
        {
            "profile-readiness:north": (
                profile_settings_fingerprint(original),
                cached,
            )
        },
    ):
        report = _readiness_for_display(
            "north",
            changed,
        )

    assert report.status == "incomplete"
    assert report.missing_steps == (
        "Run the readiness check to verify current Sheets and Drive settings.",
    )
