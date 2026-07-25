from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from business_profiles import load_business_profiles
from local_profile_store import (
    LOCAL_PROFILE_ADMIN_ENV,
    LocalProfileStoreError,
    build_profile_settings,
    load_local_profiles,
    local_profile_admin_available,
    local_profile_admin_enabled,
    merged_profile_secrets,
    parse_service_account_json,
    save_local_profile,
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
        "auth_provider_x509_cert_url": (
            "https://www.googleapis.com/oauth2/v1/certs"
        ),
        "client_x509_cert_url": "https://example.test/certificate",
    }


def settings(name: str = "North Shop") -> dict:
    return build_profile_settings(
        name,
        "https://docs.google.com/spreadsheets/d/abcdefghij1234567890/edit",
        json.dumps(credential()).encode("utf-8"),
        "https://drive.google.com/drive/folders/receiptfolder123456",
        r"G:\My Drive\Tabula Rosa Backups\north",
    )


class LocalProfileStoreTests(unittest.TestCase):
    def test_admin_flag_is_strict_and_fail_closed(self) -> None:
        self.assertFalse(local_profile_admin_enabled({}))
        self.assertFalse(
            local_profile_admin_enabled({LOCAL_PROFILE_ADMIN_ENV: "true"})
        )
        self.assertTrue(local_profile_admin_enabled({LOCAL_PROFILE_ADMIN_ENV: "1"}))
        self.assertFalse(
            local_profile_admin_available(
                "0.0.0.0",
                {LOCAL_PROFILE_ADMIN_ENV: "1"},
            )
        )
        self.assertTrue(
            local_profile_admin_available(
                "127.0.0.1",
                {LOCAL_PROFILE_ADMIN_ENV: "1"},
            )
        )
        self.assertTrue(
            local_profile_admin_available(
                "::1",
                {LOCAL_PROFILE_ADMIN_ENV: "1"},
            )
        )

    def test_rejects_malformed_credential_without_echoing_secret(self) -> None:
        secret = "credential-content-must-not-leak"
        upload = json.dumps(
            {"type": "service_account", "private_key": secret}
        ).encode("utf-8")

        with self.assertRaises(LocalProfileStoreError) as raised:
            parse_service_account_json(upload)

        self.assertNotIn(secret, str(raised.exception))

    def test_atomically_saves_and_loads_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"

            save_local_profile("north", settings(), path=path)

            stored = load_local_profiles(path)
            self.assertEqual(stored["north"]["name"], "North Shop")
            self.assertEqual(
                stored["north"]["gcp_service_account"]["client_email"],
                "ledger@test-project.iam.gserviceaccount.com",
            )
            self.assertNotIn(
                "credential-content-must-not-leak",
                path.read_text(encoding="utf-8"),
            )

    def test_requires_explicit_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)

            with self.assertRaises(LocalProfileStoreError):
                save_local_profile("north", settings("Replacement"), path=path)

            save_local_profile(
                "north",
                settings("Replacement"),
                replace=True,
                path=path,
            )
            self.assertEqual(
                load_local_profiles(path)["north"]["name"],
                "Replacement",
            )

    def test_json_profiles_replace_legacy_streamlit_profiles(self) -> None:
        base = {
            "app_password_hash": "hash",
            "business_name": "Original Business",
            "spreadsheet_id": "legacy-sheet",
            "gcp_service_account": {"client_email": "legacy@example.test"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            save_local_profile("north", settings(), path=path)

            merged = merged_profile_secrets(base, include_local=True, path=path)
            profiles = load_business_profiles(merged)

        self.assertEqual(
            [profile.key for profile in profiles],
            ["north"],
        )
        self.assertEqual(
            merged["business_profiles"]["north"]["name"],
            "North Shop",
        )

    def test_refuses_corrupt_store_instead_of_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_business_profiles.json"
            path.write_text('{"private_key": "do-not-overwrite"}', encoding="utf-8")

            with self.assertRaises(LocalProfileStoreError):
                save_local_profile("north", settings(), path=path)

            self.assertIn(
                "do-not-overwrite",
                path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
