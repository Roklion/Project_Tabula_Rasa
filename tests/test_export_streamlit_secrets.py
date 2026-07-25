from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.export_streamlit_secrets import (
    EXPORT_DIRECTORY,
    EXPORT_PREFIX,
    PROJECT_ROOT,
    SecretsExportError,
    build_streamlit_secrets_toml,
    write_secure_export,
)


class ExportStreamlitSecretsTests(unittest.TestCase):
    def test_combines_app_secrets_and_multiple_profiles(self) -> None:
        profiles = {
            "north-shop": {
                "name": "North Shop",
                "spreadsheet_id": "north-sheet-id",
                "receipt_folder_id": "north-folder-id",
                "backup_folder_path": r"G:\My Drive\North",
                "gcp_service_account": {
                    "type": "service_account",
                    "private_key": (
                        "-----BEGIN PRIVATE KEY-----\nsecret\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                    "client_email": "north@example.test",
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
            },
            profiles,
        )
        parsed = tomllib.loads(exported)

        self.assertEqual(parsed["app_password_hash"], "scrypt$hash")
        self.assertNotIn("spreadsheet_id", {
            key: value
            for key, value in parsed.items()
            if key != "business_profiles"
        })
        self.assertEqual(
            set(parsed["business_profiles"]),
            {"north-shop", "south_shop"},
        )
        self.assertEqual(
            parsed["business_profiles"]["north-shop"]["backup_folder_path"],
            r"G:\My Drive\North",
        )
        self.assertIn(
            "\nsecret\n",
            parsed["business_profiles"]["north-shop"]["gcp_service_account"][
                "private_key"
            ],
        )

    def test_secure_writer_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "streamlit-secrets.toml"
            output.write_text("existing", encoding="utf-8")

            with self.assertRaises(SecretsExportError):
                write_secure_export("replacement", output)

    def test_secure_writer_refuses_project_destination(self) -> None:
        output = PROJECT_ROOT / "tabula-rasa-streamlit-secrets-test.toml"

        with self.assertRaises(SecretsExportError):
            write_secure_export("secret", output)

        self.assertFalse(output.exists())

    def test_default_export_is_created_in_ignored_streamlit_directory(self) -> None:
        output = write_secure_export("app_password_hash = \"test\"\n")
        try:
            self.assertEqual(output.parent, EXPORT_DIRECTORY)
            self.assertTrue(output.name.startswith(EXPORT_PREFIX))
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
