"""Restore a verified ledger backup into a different, blank Google workbook."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

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
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets import SHEETS_SCOPE, WORKSHEET_HEADERS


def validate_restore_target(
    profiles: Iterable[BusinessProfile],
    target_spreadsheet_id: str,
) -> str:
    """Return a target ID that is not any configured profile's live workbook."""
    target = str(target_spreadsheet_id).strip()
    if not target:
        raise ValueError("A restore target spreadsheet ID is required.")
    if target in configured_spreadsheet_ids(profiles):
        raise ValueError("Refusing to restore into a configured live workbook")
    return target


def validate_restore_backup(
    backup: bytes,
    profile_key: str,
) -> dict[str, object]:
    """Validate a backup and refuse profile-scoped archives from another profile."""
    manifest = GoogleSheetsStorage.validate_backup_zip(backup)
    backup_profile_key = manifest.get("business_profile_key")
    if backup_profile_key is not None and backup_profile_key != profile_key:
        raise ValueError(
            "Refusing to restore a backup created for a different business profile."
        )
    return manifest


def initialize_blank_ledger_sheets(workbook: object) -> None:
    """Add ledger headers while refusing to alter a populated required sheet."""
    actual = {worksheet.title: worksheet for worksheet in workbook.worksheets()}
    for title, headers in WORKSHEET_HEADERS.items():
        worksheet = actual.get(title)
        if worksheet is None:
            worksheet = workbook.add_worksheet(
                title=title, rows=1000, cols=len(headers)
            )
            worksheet.update([list(headers)], range_name="A1", raw=True)
            continue
        values = worksheet.get_all_values()
        if values and values != [list(headers)]:
            raise StorageValidationError(
                f"Refusing to initialize populated or incompatible {title} sheet"
            )
        if not values:
            worksheet.update([list(headers)], range_name="A1", raw=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore a ledger ZIP into a different blank Google workbook"
    )
    parser.add_argument("backup", type=Path, help="Backup ZIP to restore")
    parser.add_argument(
        "--target-spreadsheet-id",
        required=True,
        help="ID of a blank workbook shared with the service account",
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Create or header missing ledger sheets in an otherwise blank workbook",
    )
    parser.add_argument(
        "--profile", help="Business profile whose Google credential should be used"
    )
    args = parser.parse_args()

    all_secrets = load_business_profile_document(args.secrets)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    profile_key = args.profile or profiles[0].key
    secrets = select_profile_secrets(all_secrets, profile_key)
    try:
        target_spreadsheet_id = validate_restore_target(
            profiles,
            args.target_spreadsheet_id,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    try:
        backup = args.backup.read_bytes()
        manifest = validate_restore_backup(backup, profile_key)
    except (OSError, StorageValidationError, ValueError) as error:
        raise SystemExit(str(error)) from error

    credentials = Credentials.from_service_account_info(
        dict(secrets["gcp_service_account"]), scopes=[SHEETS_SCOPE]
    )
    workbook = gspread.authorize(credentials).open_by_key(target_spreadsheet_id)
    if args.initialize:
        initialize_blank_ledger_sheets(workbook)
    storage = GoogleSheetsStorage(workbook)
    counts = storage.restore_backup_zip(backup)
    print(
        "Restore verified from "
        f"{manifest['backup_time']}: "
        + ", ".join(f"{title}={count}" for title, count in counts.items())
    )


if __name__ == "__main__":
    main()
