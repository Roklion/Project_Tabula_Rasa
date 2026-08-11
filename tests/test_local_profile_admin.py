from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

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
