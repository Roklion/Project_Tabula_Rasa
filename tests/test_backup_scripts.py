from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.backup_google_sheets import (
    PROJECT_ROOT,
    resolve_backup_output_dir,
    verified_backup_for_week,
    write_versioned_backup,
)
from scripts.restore_google_sheets_backup import validate_restore_target
from scripts.validate_google_sheets_backup import (
    validate_backup_file,
    validation_report,
)
from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.storage.google_sheets import BACKUP_FORMAT_VERSION
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tests.fakes import FakeWorkbook


class TestBackupScripts:
    def test_restore_refuses_every_profiles_live_workbook(self) -> None:
        profiles = load_business_profiles(
            {
                "business_profiles": {
                    "north": {
                        "spreadsheet_id": "north-live-sheet",
                        "gcp_service_account": {},
                    },
                    "south": {
                        "spreadsheet_id": "south-live-sheet",
                        "gcp_service_account": {},
                    },
                }
            }
        )

        with pytest.raises(ValueError, match="configured live workbook"):
            validate_restore_target(profiles, "north-live-sheet")
        with pytest.raises(ValueError, match="configured live workbook"):
            validate_restore_target(profiles, "south-live-sheet")

        assert (
            validate_restore_target(profiles, "restored-sheet")
            == "restored-sheet"
        )

    def test_profile_backup_path_is_default_and_cli_override_wins(self) -> None:
        configured = Path(r"G:\My Drive\Backups\north")
        override = Path(r"D:\Emergency Backups")

        assert (
            resolve_backup_output_dir({"backup_folder_path": str(configured)}, None)
            == configured
        )
        assert (
            resolve_backup_output_dir({"backup_folder_path": str(configured)}, override)
            == override
        )
        assert resolve_backup_output_dir({}, None) == PROJECT_ROOT / "backups"

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

            created = write_versioned_backup(
                storage,
                output_dir,
                build_receipt_manifest("test", [], []),
                keep=2,
            )

            remaining = sorted(path.name for path in output_dir.iterdir())
            assert remaining == [old_names[-1], created.name]
            assert GoogleSheetsStorage.validate_backup_zip(created.read_bytes())[
                "row_counts"
            ] == {
                "Accounts": 0,
                "Categories": 0,
                "Transactions": 0,
                "Mileage": 0,
            }
            timestamp = created.name.removeprefix("tabula-rosa-backup-").removesuffix(
                ".zip"
            )
            created_local_date = (
                datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=timezone.utc)
                .astimezone()
                .date()
            )
            assert (
                verified_backup_for_week(output_dir, local_date=created_local_date)
                == created
            )

    def test_retention_refuses_fewer_than_two_generations(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            with pytest.raises(ValueError):
                write_versioned_backup(
                    storage,
                    Path(temporary_directory),
                    build_receipt_manifest("test", [], []),
                    keep=1,
                )

    def test_standalone_validator_reports_manifest_and_rows(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_path = Path(temporary_directory) / "backup.zip"
            backup_path.write_bytes(
                storage.export_backup_zip(build_receipt_manifest("test", [], []))
            )

            manifest = validate_backup_file(backup_path)
            report = validation_report(backup_path, manifest)

        assert f"Format version: {BACKUP_FORMAT_VERSION}" in report
        assert "Accounts=0" in report
        assert "Mileage=0" in report
        assert "Manifest checksums: verified" in report
