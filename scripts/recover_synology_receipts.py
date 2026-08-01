"""Recover verified receipt files after restoring a matching ledger backup."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import (
    BusinessProfile,
    configured_spreadsheet_ids,
    load_business_profiles,
    select_profile_secrets,
)
from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.receipt_recovery import recover_receipts_from_synology
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.storage.google_sheets import SHEETS_SCOPE


def _drive_destination(profile_secrets: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        raise ValueError("Google Drive is not connected for this business profile.")
    receipt_folder = drive_settings.get("receipt_folder")
    if not isinstance(receipt_folder, Mapping):
        raise ValueError("No Google Drive receipt folder is selected for this profile.")
    return drive_settings, str(receipt_folder.get("id") or "")


def validate_recovery_target(
    profiles: Iterable[BusinessProfile],
    target_spreadsheet_id: str,
) -> str:
    """Return a target ID that is not any configured profile's live workbook."""
    target = str(target_spreadsheet_id).strip()
    if not target:
        raise ValueError("A recovery target spreadsheet ID is required.")
    if target in configured_spreadsheet_ids(profiles):
        raise ValueError(
            "Refusing to remap recovered receipts in a configured live workbook."
        )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Matching validated ledger backup ZIP")
    parser.add_argument(
        "receipt_directory",
        type=Path,
        help="Synology recovery directory containing the receipt files",
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument("--profile", help="Business profile key to recover")
    parser.add_argument(
        "--target-spreadsheet-id",
        required=True,
        help="ID of the newly restored non-live ledger workbook",
    )
    args = parser.parse_args()

    all_secrets = load_business_profile_document(args.secrets)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    profile_key = args.profile or profiles[0].key
    profile_secrets = select_profile_secrets(all_secrets, profile_key)
    drive_settings, folder_id = _drive_destination(profile_secrets)
    try:
        target_spreadsheet_id = validate_recovery_target(
            profiles,
            args.target_spreadsheet_id,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    try:
        backup = args.backup.read_bytes()
    except OSError as exc:
        raise SystemExit("The ledger backup could not be read.") from exc
    credentials = Credentials.from_service_account_info(
        dict(profile_secrets["gcp_service_account"]),
        scopes=[SHEETS_SCOPE],
    )
    workbook = gspread.authorize(credentials).open_by_key(target_spreadsheet_id)
    storage = GoogleSheetsStorage(workbook)
    drive = GoogleDriveClient(load_oauth_config(all_secrets), drive_settings)
    try:
        report = recover_receipts_from_synology(
            backup,
            args.receipt_directory,
            profile_key=profile_key,
            folder_id=folder_id,
            storage=storage,
            drive=drive,
        )
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(
        "Receipt recovery: "
        f"total={report['total']}, restored={report['restored']}, "
        f"reused={report['reused']}, remapped={report['references_remapped']}, "
        f"unreferenced={report['unreferenced_preserved']}, "
        f"missing={report['missing']}, corrupt={report['corrupt']}, "
        f"conflicts={report['conflicts']}, errors={report['errors']}"
    )
    for issue in report["issues"]:
        print(f"{issue['receipt_id']}: {issue['status']}")
    if report["skipped"]:
        raise SystemExit("Receipt recovery finished with skipped entries.")


if __name__ == "__main__":
    main()
