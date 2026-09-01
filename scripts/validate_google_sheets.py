"""Validate read access and worksheet headers without displaying ledger rows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

import gspread
from google.oauth2.service_account import Credentials


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import load_business_profiles, select_profile_secrets
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.storage import GoogleSheetsStorage


def validate(
    secrets_path: Path,
    write_test: bool = False,
    profile_key: str | None = None,
    spreadsheet_id: str | None = None,
) -> None:
    if spreadsheet_id is not None and write_test:
        raise ValueError("--spreadsheet-id cannot be combined with --write-test")

    all_secrets = load_business_profile_document(secrets_path)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not profile_key:
        raise RuntimeError("Multiple profiles are configured; pass --profile PROFILE_KEY")
    secrets = select_profile_secrets(all_secrets, profile_key)
    target_spreadsheet_id = (
        spreadsheet_id.strip()
        if spreadsheet_id is not None
        else str(secrets["spreadsheet_id"]).strip()
    )
    if not target_spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty")

    credentials = Credentials.from_service_account_info(
        secrets["gcp_service_account"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
            if write_test
            else "https://www.googleapis.com/auth/spreadsheets.readonly"
        ],
    )
    client = gspread.authorize(credentials)
    workbook = client.open_by_key(target_spreadsheet_id)
    storage = GoogleSheetsStorage(
        workbook,
        _allow_legacy_hierarchy_headers=True,
    )
    row_counts = {
        "Accounts": len(storage.list_accounts(active_only=False)),
        "Categories": len(storage.list_categories()),
        "Payees": len(storage.list_payees()),
        "Transactions": len(storage.list_transactions()),
        "Mileage": len(storage.list_mileage_trips()),
    }

    print(f"Workbook access verified: {workbook.title}")
    print(
        "Worksheet headers verified: Accounts, Categories, Payees, "
        "Transactions, Mileage"
    )
    print(
        "Ledger rows readable: "
        + ", ".join(f"{title}={count}" for title, count in row_counts.items())
    )
    if spreadsheet_id is not None:
        print("Explicit workbook override verified; business profile unchanged")

    if write_test:
        title = f"_access_test_{uuid4().hex[:8]}"
        worksheet = None
        try:
            worksheet = workbook.add_worksheet(title=title, rows=2, cols=1)
            worksheet.update_acell("A1", "created")
            if worksheet.acell("A1").value != "created":
                raise RuntimeError("Create/read verification failed")
            worksheet.update_acell("A1", "updated")
            if worksheet.acell("A1").value != "updated":
                raise RuntimeError("Update verification failed")
        finally:
            if worksheet is not None:
                workbook.del_worksheet(worksheet)
        print("Disposable worksheet create/read/update/delete test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets", type=Path, default=Path(".streamlit/secrets.toml")
    )
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Run a reversible CRUD test using a disposable worksheet",
    )
    parser.add_argument("--profile", help="Business profile key to validate")
    parser.add_argument(
        "--spreadsheet-id",
        help=(
            "Read-only workbook ID override; uses the selected profile's "
            "service-account credential without changing the profile"
        ),
    )
    args = parser.parse_args()
    validate(
        args.secrets,
        write_test=args.write_test,
        profile_key=args.profile,
        spreadsheet_id=args.spreadsheet_id,
    )


if __name__ == "__main__":
    main()
