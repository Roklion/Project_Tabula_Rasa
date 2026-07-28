from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path

import pytest

from scripts.export_streamlit_secrets import (
    EXPORT_DIRECTORY,
    EXPORT_PREFIX,
    PROJECT_ROOT,
    SecretsExportError,
    build_streamlit_secrets_toml,
    write_secure_export,
)


class TestExportStreamlitSecrets:
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
                    "backup_folder": {
                        "id": "northbackupfolder123",
                        "name": "Backups",
                    },
                },
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
            },
            profiles,
        )
        parsed = tomllib.loads(exported)

        assert parsed["app_password_hash"] == "scrypt$hash"
        assert "spreadsheet_id" not in {
            key: value for key, value in parsed.items() if key != "business_profiles"
        }
        assert set(parsed["business_profiles"]) == {"north-shop", "south_shop"}
        assert (
            parsed["business_profiles"]["north-shop"]["backup_folder_path"]
            == r"G:\My Drive\North"
        )
        assert (
            "\nsecret\n"
            in parsed["business_profiles"]["north-shop"]["gcp_service_account"][
                "private_key"
            ]
        )
        assert (
            parsed["google_drive_oauth"]["client_secret"] == "oauth-secret"
        )
        assert (
            parsed["business_profiles"]["north-shop"]["google_drive"][
                "refresh_token"
            ]
            == "north-refresh-token"
        )

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
