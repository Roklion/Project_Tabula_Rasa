from __future__ import annotations

import pytest

from tabula_rasa.local_profile_admin import _profile_setup_error_message
from tabula_rasa.storage import (
    StorageAuthenticationError,
    StorageInitializationError,
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
