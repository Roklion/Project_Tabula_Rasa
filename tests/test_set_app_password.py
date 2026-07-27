from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from tabula_rasa.ledger_auth import verify_password
from scripts.set_app_password import set_password


class SetAppPasswordTests(unittest.TestCase):
    def test_updates_app_only_secrets_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secrets_path = Path(directory) / "secrets.toml"
            secrets_path.write_text(
                'app_password_hash = "old-hash"\n',
                encoding="utf-8",
            )

            with patch(
                "scripts.set_app_password.getpass.getpass",
                side_effect=["new-password", "new-password"],
            ):
                set_password(secrets_path)

            with secrets_path.open("rb") as secrets_file:
                parsed = tomllib.load(secrets_file)
            self.assertTrue(
                verify_password(
                    "new-password",
                    parsed["app_password_hash"],
                )
            )


if __name__ == "__main__":
    unittest.main()
