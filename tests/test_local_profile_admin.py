from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import streamlit as st

from tabula_rasa.local_profile_admin import _profile_rows
from tabula_rasa.local_profile_admin_readiness import (
    fresh_profile_readiness,
    readiness_for_display,
)
from tabula_rasa.local_profile_admin_security import (
    export_hosted_secrets_file,
    render_security_deployment_info,
)
from tabula_rasa.local_profile_admin_support import (
    initialize_candidate_storage,
)
from scripts.export_streamlit_secrets import SecretsExportError
from tabula_rasa.profile_readiness import ProfileReadiness, profile_settings_fingerprint
from tabula_rasa.local_profile_store import LocalProfileStoreError
from tabula_rasa.storage import (
    StorageError,
    StorageValidationError,
    StorageWorkbookAccessError,
)
SETTINGS = {
    "spreadsheet_id": "abcdefghij1234567890",
    "google_drive": google_grant('ledger@example.test'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
}


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
    assert rows[0]["Spreadsheet"] == "…34567890"
    assert SETTINGS["spreadsheet_id"] not in repr(rows)


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
        "tabula_rasa.local_profile_admin_support.GoogleSheetsStorage.from_secrets",
        return_value=candidate,
    ):
        with pytest.raises(type(error)) as raised:
            initialize_candidate_storage(SETTINGS)

    assert raised.value is error


def test_fresh_readiness_reports_sheets_failure_without_secret_values() -> None:
    with patch(
        "tabula_rasa.local_profile_admin_readiness.GoogleSheetsStorage.from_secrets_read_only",
        side_effect=StorageWorkbookAccessError("contains no secret"),
    ), patch(
        "tabula_rasa.local_profile_admin_readiness.validate_google_drive_profile"
    ) as validate_drive:
        report = fresh_profile_readiness(
            "north",
            {
                **SETTINGS,
                "name": "North Shop",
            },
            app_secrets={},
        )

    assert report.status == "incomplete"
    assert report.validation_errors == (
        "Sheets workbook validation failed. Confirm sharing and the workbook ID.",
    )
    validate_drive.assert_not_called()


def test_fresh_readiness_skips_drive_validation_without_a_storage_root() -> None:
    with patch(
        "tabula_rasa.local_profile_admin_readiness.GoogleSheetsStorage.from_secrets_read_only"
    ), patch(
        "tabula_rasa.local_profile_admin_readiness.validate_google_drive_profile"
    ) as validate_drive:
        report = fresh_profile_readiness(
            "north",
            {
                **SETTINGS,
                "name": "North Shop",
                "google_drive": {"authorized_email": "owner@example.test"},
            },
            app_secrets={},
        )

    assert report.status == "ready-local"
    assert report.missing_steps == ()
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
        "tabula_rasa.local_profile_admin_readiness.GoogleSheetsStorage.from_secrets_read_only"
    ), patch(
        "tabula_rasa.local_profile_admin_readiness.validate_google_drive_profile"
    ) as validate_drive:
        report = fresh_profile_readiness(
            "north",
            settings,
            app_secrets={},
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
    cached = ProfileReadiness(status="ready-local")
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
        report = readiness_for_display(
            "north",
            changed,
        )

    assert report.status == "incomplete"
    assert report.missing_steps == (
        "Run the readiness check to verify current Sheets and Drive settings.",
    )


def test_hosted_export_reloads_and_includes_every_local_profile() -> None:
    local_profiles = {
        "north": {"name": "North", "spreadsheet_id": "north-sheet"},
        "south": {"name": "South", "spreadsheet_id": "south-sheet"},
    }
    generated = "app_password_hash = \"hash\"\n"
    destination = Path(".streamlit/tabula-rasa-streamlit-secrets-test.toml")
    with patch(
        "tabula_rasa.local_profile_admin_security.load_local_profiles",
        return_value=local_profiles,
    ) as load_profiles, patch(
        "tabula_rasa.local_profile_admin_security.build_streamlit_secrets_toml",
        return_value=generated,
    ) as build_document, patch(
        "tabula_rasa.local_profile_admin_security.write_secure_export",
        return_value=destination,
    ) as write_export:
        result = export_hosted_secrets_file(
            {"app_password_hash": "hash"},
            store_path=Path("profile-store.json"),
        )

    assert result == destination
    load_profiles.assert_called_once_with(Path("profile-store.json"))
    build_document.assert_called_once_with(
        {"app_password_hash": "hash"},
        local_profiles,
    )
    write_export.assert_called_once_with(generated)


def test_hosted_export_refuses_empty_included_profile_set() -> None:
    with patch(
        "tabula_rasa.local_profile_admin_security.load_local_profiles",
        return_value={},
    ), patch(
        "tabula_rasa.local_profile_admin_security.build_streamlit_secrets_toml"
    ) as build_document:
        with pytest.raises(LocalProfileStoreError, match="local business profile"):
            export_hosted_secrets_file({}, store_path=Path("profile-store.json"))

    build_document.assert_not_called()


def test_hosted_export_failure_ui_does_not_echo_secret_values() -> None:
    secret = "-----BEGIN PRIVATE KEY-----do-not-display"
    with patch.object(st, "subheader"), patch.object(st, "write"), patch.object(
        st, "info"
    ), patch.object(st, "markdown"), patch.object(
        st, "button", return_value=True
    ), patch.object(st, "error") as render_error, patch(
        "tabula_rasa.local_profile_admin_security.export_hosted_secrets_file",
        side_effect=SecretsExportError(secret),
    ):
        render_security_deployment_info({"app_password_hash": secret})

    message = str(render_error.call_args.args[0])
    assert "failed" in message.casefold()
    assert secret not in message


def test_hosted_export_success_ui_shows_only_path_and_complete_handoff() -> None:
    secret = "refresh-token-do-not-display"
    destination = Path(".streamlit/tabula-rasa-streamlit-secrets-safe.toml")
    with patch.object(st, "subheader"), patch.object(st, "write") as render_write, patch.object(
        st, "info"
    ) as render_info, patch.object(st, "markdown"), patch.object(
        st, "button", return_value=True
    ), patch.object(st, "success") as render_success, patch(
        "tabula_rasa.local_profile_admin_security.export_hosted_secrets_file",
        return_value=destination,
    ):
        render_security_deployment_info({"refresh_token": secret})

    rendered = " ".join(
        str(call.args[0])
        for mock in (render_write, render_info, render_success)
        for call in mock.call_args_list
        if call.args
    )
    assert str(destination) in rendered
    assert "Streamlit App settings > Secrets" in rendered
    assert "delete the generated local file" in rendered
    assert "Re-run profile readiness" in rendered
    assert "cannot verify hosted Secrets acceptance" in rendered
    assert secret not in rendered


def test_security_deployment_info_links_use_canonical_guides() -> None:
    with patch.object(st, "subheader"), patch.object(st, "write"), patch.object(
        st, "info"
    ), patch.object(st, "markdown") as render_markdown, patch.object(
        st, "button", return_value=False
    ):
        render_security_deployment_info({})

    rendered = " ".join(
        str(call.args[0]) for call in render_markdown.call_args_list if call.args
    )
    assert "/docs/SETUP.md" in rendered
    assert "/docs/BACKUP_RECOVERY.md)" in rendered
    assert "/docs/BACKUP_RECOVERY.md#optional-synology-recovery-copy" in rendered
    assert "/docs/setup/" not in rendered
    assert "/docs/operations/" not in rendered
