from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.backup_google_sheets import verified_backup_for_week, write_versioned_backup
from storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


class BackupScriptTests(unittest.TestCase):
    def test_versioned_backup_retains_newest_generations(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            old_names = (
                "tabula-rosa-backup-20260716T120000Z.zip",
                "tabula-rosa-backup-20260717T120000Z.zip",
                "tabula-rosa-backup-20260718T120000Z.zip",
            )
            for name in old_names:
                (output_dir / name).write_bytes(b"old")

            created = write_versioned_backup(storage, output_dir, keep=2)

            remaining = sorted(path.name for path in output_dir.iterdir())
            self.assertEqual(
                remaining,
                [old_names[-1], created.name],
            )
            self.assertEqual(
                GoogleSheetsStorage.validate_backup_zip(created.read_bytes())[
                    "row_counts"
                ],
                {"Accounts": 0, "Categories": 0, "Transactions": 0},
            )
            timestamp = created.name.removeprefix(
                "tabula-rosa-backup-"
            ).removesuffix(".zip")
            created_local_date = (
                datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=timezone.utc)
                .astimezone()
                .date()
            )
            self.assertEqual(
                verified_backup_for_week(
                    output_dir, local_date=created_local_date
                ),
                created,
            )

    def test_retention_refuses_fewer_than_two_generations(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                write_versioned_backup(storage, Path(temporary_directory), keep=1)


if __name__ == "__main__":
    unittest.main()
