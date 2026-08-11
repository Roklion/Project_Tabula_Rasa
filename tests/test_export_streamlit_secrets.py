from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from tabula_rasa.google_drive import GoogleDriveConfigurationError
from scripts.export_streamlit_secrets import (
    EXPORT_DIRECTORY,
    EXPORT_PREFIX,
    PROJECT_ROOT,
    SecretsExportError,
    build_streamlit_secrets_toml,
    project_hosted_profiles,
    write_secure_export,
)


class TestExportStreamlitSecrets:
    def test_hosted_projection_error_preserves_profile_context(self) -> None:
        with patch(
            "scripts.export_streamlit_secrets._project_hosted_profiles",
            side_effect=GoogleDriveConfigurationError(
                "Google Drive settings for profile 'north' are invalid: "
                "missing storage root"
            ),
        ):
            with pytest.raises(
                SecretsExportError,
                match="profile 'north'.*missing storage root",
            ):
                project_hosted_profiles({})

    def test_combines_app_secrets_and_multiple_profiles(self) -> None:
        profiles = {
            "north-shop": {
                "name": "North Shop",
                "spreadsheet_id": "north-sheet-id",
                "backup_folder_path": r"G:\My Drive\North",
                "gcp_service_account": {
                    "type": "service_account",
                    "private_key": (
                        "-----BEGIN PRIVATE KEY-----\nsecret\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                    "client_email": "north@example.test",
                },
                "google_drive": {
                    "authorized_email": "north-owner@example.test",
                    "authorized_name": "North Owner",
                    "refresh_token": "north-refresh-token",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": ["https://www.googleapis.com/auth/drive.file"],
                    "storage_root": {
                        "id": "northrootfolder123",
                        "name": "North Storage",
                    },
                    "receipt_folder": {
                        "id": "northreceiptfolder123",
                        "name": "Receipts",
                    },
                    "backup_folder": {
                        "id": "northbackupfolder123",
                        "name": "Backups",
                    },
                },
                "synology_recovery": {
                    "layout": "profile-root",
                    "destination_path": "/volume1/Backups/TabulaRasa/north-shop",
                    "schedule": "Continuous",
                    "retention_policy": "Retain until manual review.",
                },
                "future_local_operations": {"enabled": True},
            },
            "south_shop": {
                "name": "South Shop",
                "spreadsheet_id": "south-sheet-id",
                "gcp_service_account": {
                    "type": "service_account",
                    "private_key": (
                        "-----BEGIN PRIVATE KEY-----\nsecret\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                    "client_email": "south@example.test",
                },
            },
        }

        exported = build_streamlit_secrets_toml(
            {
                "app_password_hash": "scrypt$hash",
                "business_name": "Legacy Name",
                "spreadsheet_id": "legacy-sheet",
                "gcp_service_account": {"private_key": "legacy-secret"},
                "google_drive_oauth": {
                    "client_id": "client.apps.googleusercontent.com",
                    "client_secret": "oauth-secret",
                    "redirect_uris": ["https://tabula-rasa.streamlit.app/"],
                    "picker_api_key": "picker-key",
                    "project_number": "123456789",
                },
                "synology_recovery_defaults": {
                    "base_path": "/volume1/Tabula_Rosa_Backups",
                    "schedule": "Continuous",
                    "retention_policy": "Quarterly manual review.",
                },
            },
            profiles,
        )
        parsed = tomllib.loads(exported)

        assert parsed["app_password_hash"] == "scrypt$hash"
        assert "spreadsheet_id" not in {
            key: value for key, value in parsed.items() if key != "business_profiles"
        }
        assert set(parsed["business_profiles"]) == {"north-shop", "south_shop"}
        hosted_north = parsed["business_profiles"]["north-shop"]
        assert set(hosted_north) == {
            "name",
            "spreadsheet_id",
            "gcp_service_account",
            "google_drive",
        }
        assert (
            "\nsecret\n"
            in parsed["business_profiles"]["north-shop"]["gcp_service_account"][
                "private_key"
            ]
        )
        assert (
            parsed["google_drive_oauth"]["client_secret"] == "oauth-secret"
        )
        assert hosted_north["google_drive"]["refresh_token"] == (
            "north-refresh-token"
        )
        assert hosted_north["google_drive"]["storage_root"]["id"] == (
            "northrootfolder123"
        )
        assert hosted_north["google_drive"]["receipt_folder"]["id"] == (
            "northreceiptfolder123"
        )
        assert hosted_north["google_drive"]["backup_folder"]["id"] == (
            "northbackupfolder123"
        )
        assert "backup_folder_path" not in hosted_north
        assert "synology_recovery" not in hosted_north
        assert "future_local_operations" not in hosted_north
        assert "synology_recovery_defaults" not in parsed

    def test_local_only_edits_leave_hosted_export_unchanged(self) -> None:
        app_secrets = {
            "app_password_hash": "scrypt$hash",
            "synology_recovery_defaults": {
                "base_path": "/volume1/Recovery",
                "schedule": "Continuous",
                "retention_policy": "Keep all.",
            },
        }
        profile = {
            "name": "North Shop",
            "spreadsheet_id": "north-sheet-id",
            "gcp_service_account": {"type": "service_account"},
            "backup_folder_path": r"G:\Backups\North",
            "synology_recovery": {
                "layout": "profile-root",
                "destination_path": "/volume1/Recovery/north",
                "schedule": "Continuous",
                "retention_policy": "Keep all.",
            },
        }
        before = build_streamlit_secrets_toml(
            app_secrets,
            {"north": profile},
        )

        app_secrets["synology_recovery_defaults"] = {
            "base_path": "/volume2/New-Recovery",
            "schedule": "Nightly",
            "retention_policy": "Keep quarterly versions.",
        }
        profile["backup_folder_path"] = r"H:\New\North"
        profile["synology_recovery"] = {
            "layout": "profile-root",
            "destination_path": "/volume2/New-Recovery/north",
            "schedule": "Nightly",
            "retention_policy": "Keep quarterly versions.",
        }
        after = build_streamlit_secrets_toml(
            app_secrets,
            {"north": profile},
        )

        assert after == before

    def test_secure_writer_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "streamlit-secrets.toml"
            output.write_text("existing", encoding="utf-8")

            with pytest.raises(SecretsExportError):
                write_secure_export("replacement", output)

    def test_secure_writer_refuses_project_destination(self) -> None:
        output = PROJECT_ROOT / "tabula-rasa-streamlit-secrets-test.toml"

        with pytest.raises(SecretsExportError):
            write_secure_export("secret", output)

        assert not output.exists()

    def test_default_export_is_created_in_ignored_streamlit_directory(self) -> None:
        output = write_secure_export('app_password_hash = "test"\n')
        try:
            assert output.parent == EXPORT_DIRECTORY
            assert output.name.startswith(EXPORT_PREFIX)
        finally:
            output.unlink(missing_ok=True)
