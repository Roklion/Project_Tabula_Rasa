from __future__ import annotations

import io
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.backup_google_sheets import (
    build_backup_receipt_manifest,
    PROJECT_ROOT,
    resolve_backup_output_dir,
    verified_backup_for_week,
    verified_drive_backup_for_week,
    write_versioned_backup,
)
from tabula_rasa.google_drive import GoogleDriveConfigurationError
from scripts.restore_google_sheets_backup import (
    validate_restore_backup,
    validate_restore_target,
)
from scripts.validate_google_sheets_backup import (
    validate_backup_file,
    validation_report,
)
from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.storage.google_sheets import BACKUP_FORMAT_VERSION
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tests.fakes import FakeWorkbook


def _ledger_only_backup(storage: GoogleSheetsStorage) -> bytes:
    current = storage.export_backup_zip(
        build_receipt_manifest("test", [], [])
    )
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(current)) as source, zipfile.ZipFile(
        output,
        "w",
    ) as destination:
        manifest = json.loads(source.read("manifest.json"))
        manifest["format_version"] = 4
        manifest["sha256"].pop("receipts.json")
        for name in source.namelist():
            if name == "receipts.json":
                continue
            content = source.read(name)
            if name == "manifest.json":
                content = json.dumps(manifest).encode("utf-8")
            destination.writestr(name, content)
    return output.getvalue()


class TestBackupScripts:
    def test_current_backup_inventories_the_configured_receipt_folder(self) -> None:
        storage = Mock(spec=GoogleSheetsStorage)
        storage.list_transactions.return_value = []
        client = Mock()
        client.list_profile_receipts.return_value = []

        manifest = build_backup_receipt_manifest(
            "north",
            {
                "google_drive": {
                    "receipt_folder": {"id": "folder123456"},
                }
            },
            storage,
            client=client,
        )

        assert manifest == build_receipt_manifest("north", [], [])
        assert storage.list_transactions.call_count == 2
        storage.list_transactions.assert_called_with(_force_refresh=True)
        assert client.list_profile_receipts.call_count == 2
        client.list_profile_receipts.assert_called_with(
            profile_key="north",
            folder_id="folder123456",
            _force_refresh=True,
        )

    def test_current_backup_requires_a_configured_receipt_folder(self) -> None:
        storage = Mock(spec=GoogleSheetsStorage)

        with pytest.raises(
            GoogleDriveConfigurationError,
            match="requires a selected Google Drive receipt folder",
        ):
            build_backup_receipt_manifest("north", {}, storage)

        storage.list_transactions.assert_not_called()

    def test_restore_refuses_a_receipt_backup_from_another_profile(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        backup = storage.export_backup_zip(
            build_receipt_manifest("north", [], [])
        )

        with pytest.raises(ValueError, match="different business profile"):
            validate_restore_backup(backup, "south")

        manifest = validate_restore_backup(backup, "north")
        assert manifest["business_profile_key"] == "north"

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
            resolve_backup_output_dir(
                {"backup_folder_path": str(configured)}, None, "north"
            )
            == configured
        )
        assert (
            resolve_backup_output_dir(
                {"backup_folder_path": str(configured)}, override, "north"
            )
            == override
        )
        assert resolve_backup_output_dir({}, None, "north") == PROJECT_ROOT / "backups" / "north"

    def test_profile_fallbacks_are_isolated_and_require_a_profile_key(self) -> None:
        assert resolve_backup_output_dir({}, None, "north") != resolve_backup_output_dir(
            {}, None, "south"
        )
        with pytest.raises(ValueError, match="profile key"):
            resolve_backup_output_dir({}, None)

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

    def test_weekly_local_backup_requires_current_receipt_format(self) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        current = storage.export_backup_zip(
            build_receipt_manifest("test", [], [])
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            legacy = output_dir / "tabula-rosa-backup-20260728T120000Z.zip"
            legacy.write_bytes(_ledger_only_backup(storage))

            assert (
                verified_backup_for_week(
                    output_dir,
                    local_date=datetime(2026, 7, 29).date(),
                )
                is None
            )

            current_path = (
                output_dir / "tabula-rosa-backup-20260729T120000Z.zip"
            )
            current_path.write_bytes(current)
            assert (
                verified_backup_for_week(
                    output_dir,
                    local_date=datetime(2026, 7, 29).date(),
                )
                == current_path
            )

    def test_weekly_drive_backup_downloads_and_requires_current_format(
        self,
    ) -> None:
        storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        legacy_backup = _ledger_only_backup(storage)
        current_backup = storage.export_backup_zip(
            build_receipt_manifest("test", [], [])
        )
        legacy = {
            "id": "backup123456",
            "name": "tabula-rosa-backup-20260728T120000Z.zip",
        }
        current = {
            "id": "backup234567",
            "name": "tabula-rosa-backup-20260729T120000Z.zip",
        }
        client = Mock()
        client.list_backups.return_value = [legacy, current]
        client.download_file.side_effect = [legacy_backup, current_backup]

        with (
            patch(
                "scripts.backup_google_sheets.GoogleDriveClient",
                return_value=client,
            ),
            patch("scripts.backup_google_sheets.load_oauth_config"),
        ):
            verified = verified_drive_backup_for_week(
                {},
                "test",
                {"google_drive": {"backup_folder": {"id": "folder123456"}}},
                local_date=datetime(2026, 7, 29, tzinfo=timezone.utc),
            )

        assert verified == current
        assert client.download_file.call_args_list == [
            (("backup123456",),),
            (("backup234567",),),
        ]

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
