from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_ADMIN_ENV,
    LocalProfileStoreError,
    build_profile_settings,
    load_local_profiles,
    local_profile_admin_available,
    local_profile_admin_enabled,
    merged_profile_secrets,
    parse_service_account_json,
    save_local_profile,
    update_local_profile_google_drive,
    update_local_profile_synology_recovery,
)


def credential(private_key: str = "test-private-key") -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": (
            "-----BEGIN PRIVATE KEY-----\n"
            f"{private_key}\n"
            "-----END PRIVATE KEY-----\n"
        ),
        "client_email": "ledger@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": ("https://www.googleapis.com/oauth2/v1/certs"),
        "client_x509_cert_url": "https://example.test/certificate",
    }


def settings(name: str = "North Shop") -> dict:
    return build_profile_settings(
        name,
        "https://docs.google.com/spreadsheets/d/abcdefghij1234567890/edit",
        json.dumps(credential()).encode("utf-8"),
        r"G:\My Drive\Tabula Rosa Backups\north",
    )


class TestLocalProfileStore:
    def test_admin_flag_is_strict_and_fail_closed(self) -> None:
        assert not local_profile_admin_enabled({})
        assert not local_profile_admin_enabled({LOCAL_PROFILE_ADMIN_ENV: "true"})
        assert local_profile_admin_enabled({LOCAL_PROFILE_ADMIN_ENV: "1"})
        assert not local_profile_admin_available(
            "0.0.0.0",
            {LOCAL_PROFILE_ADMIN_ENV: "1"},
        )
        assert local_profile_admin_available(
            "127.0.0.1",
            {LOCAL_PROFILE_ADMIN_ENV: "1"},
        )
        assert local_profile_admin_available(
            "::1",
            {LOCAL_PROFILE_ADMIN_ENV: "1"},
        )

    def test_rejects_malformed_credential_without_echoing_secret(self) -> None:
        secret = "credential-content-must-not-leak"
        upload = json.dumps({"type": "service_account", "private_key": secret}).encode(
            "utf-8"
        )

        with pytest.raises(LocalProfileStoreError) as raised:
            parse_service_account_json(upload)

        assert secret not in str(raised.value)

    def test_blank_backup_path_is_not_stored(self) -> None:
        configured = build_profile_settings(
            "Cloud Shop",
            "abcdefghij1234567890",
            json.dumps(credential()).encode("utf-8"),
            "   ",
        )

        assert "backup_folder_path" not in configured

    def test_atomically_saves_and_loads_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"

            save_local_profile("north", settings(), path=path)

            stored = load_local_profiles(path)
            assert stored["north"]["name"] == "North Shop"
            assert (
                stored["north"]["gcp_service_account"]["client_email"]
                == "ledger@test-project.iam.gserviceaccount.com"
            )
            assert "credential-content-must-not-leak" not in path.read_text(
                encoding="utf-8"
            )

    def test_requires_explicit_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)

            with pytest.raises(LocalProfileStoreError):
                save_local_profile("north", settings("Replacement"), path=path)

            save_local_profile(
                "north",
                settings("Replacement"),
                replace=True,
                path=path,
            )
            assert load_local_profiles(path)["north"]["name"] == "Replacement"

    def test_json_profiles_are_merged_with_app_secrets(self) -> None:
        base = {"app_password_hash": "hash"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)

            merged = merged_profile_secrets(base, path=path)
            profiles = load_business_profiles(merged)

        assert [profile.key for profile in profiles] == ["north"]
        assert merged["business_profiles"]["north"]["name"] == "North Shop"

    def test_refuses_corrupt_store_instead_of_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            path.write_text('{"private_key": "do-not-overwrite"}', encoding="utf-8")

            with pytest.raises(LocalProfileStoreError):
                save_local_profile("north", settings(), path=path)

            assert "do-not-overwrite" in path.read_text(encoding="utf-8")

    def test_persists_and_disconnects_profile_scoped_drive_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)
            drive = {
                "authorized_email": "north@example.test",
                "authorized_name": "North Owner",
                "refresh_token": "durable-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/drive.file"],
                "receipt_folder": {
                    "id": "receiptfolder123",
                    "name": "Receipts",
                },
            }

            update_local_profile_google_drive("north", drive, path=path)
            stored = load_local_profiles(path)
            assert stored["north"]["google_drive"] == drive

            update_local_profile_google_drive("north", None, path=path)
            assert "google_drive" not in load_local_profiles(path)["north"]

    def test_synology_recovery_is_optional_and_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)
            drive = {
                "authorized_email": "north@example.test",
                "authorized_name": "North Owner",
                "refresh_token": "durable-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/drive.file"],
                "backup_folder": {
                    "id": "backupfolder123",
                    "name": "North Backups",
                },
            }
            update_local_profile_google_drive("north", drive, path=path)
            recovery = {
                "destination_path": "/volume1/Backups/TabulaRasa/north",
                "schedule": "Continuous",
                "retention_policy": "Retain until manual review.",
            }

            update_local_profile_synology_recovery("north", recovery, path=path)
            assert load_local_profiles(path)["north"]["synology_recovery"] == recovery

            update_local_profile_synology_recovery("north", None, path=path)
            assert "synology_recovery" not in load_local_profiles(path)["north"]

    def test_synology_recovery_requires_a_drive_backup_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)

            with pytest.raises(
                LocalProfileStoreError,
                match="Google Drive backup folder",
            ):
                update_local_profile_synology_recovery(
                    "north",
                    {
                        "destination_path": "/volume1/Backups/north",
                        "schedule": "Continuous",
                        "retention_policy": "Keep all.",
                    },
                    path=path,
                )
