"""Restore a verified ledger backup into a different, blank Google workbook."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from storage import GoogleSheetsStorage, StorageValidationError
from storage.google_sheets import SHEETS_SCOPE, WORKSHEET_HEADERS
from business_profiles import load_business_profiles, select_profile_secrets


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

    with args.secrets.open("rb") as secrets_file:
        all_secrets = tomllib.load(secrets_file)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    secrets = select_profile_secrets(all_secrets, args.profile)
    if args.target_spreadsheet_id == str(secrets["spreadsheet_id"]):
        raise SystemExit("Refusing to restore into the configured live workbook")

    credentials = Credentials.from_service_account_info(
        dict(secrets["gcp_service_account"]), scopes=[SHEETS_SCOPE]
    )
    workbook = gspread.authorize(credentials).open_by_key(args.target_spreadsheet_id)
    if args.initialize:
        initialize_blank_ledger_sheets(workbook)
    storage = GoogleSheetsStorage(workbook)
    backup = args.backup.read_bytes()
    manifest = storage.validate_backup_zip(backup)
    counts = storage.restore_backup_zip(backup)
    print(
        "Restore verified from "
        f"{manifest['backup_time']}: "
        + ", ".join(f"{title}={count}" for title, count in counts.items())
    )


if __name__ == "__main__":
    main()
