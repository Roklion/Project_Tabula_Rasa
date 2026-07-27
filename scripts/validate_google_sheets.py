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
    secrets_path: Path, write_test: bool = False, profile_key: str | None = None
) -> None:
    all_secrets = load_business_profile_document(secrets_path)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not profile_key:
        raise RuntimeError("Multiple profiles are configured; pass --profile PROFILE_KEY")
    secrets = select_profile_secrets(all_secrets, profile_key)

    credentials = Credentials.from_service_account_info(
        secrets["gcp_service_account"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
            if write_test
            else "https://www.googleapis.com/auth/spreadsheets.readonly"
        ],
    )
    client = gspread.authorize(credentials)
    workbook = client.open_by_key(secrets["spreadsheet_id"])
    GoogleSheetsStorage(workbook)

    print(f"Workbook access verified: {workbook.title}")
    print("Worksheet headers verified: Accounts, Categories, Transactions, Mileage")

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
    args = parser.parse_args()
    validate(args.secrets, write_test=args.write_test, profile_key=args.profile)


if __name__ == "__main__":
    main()
