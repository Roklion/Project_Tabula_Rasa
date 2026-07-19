"""Validate read access and worksheet headers without displaying ledger rows."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from uuid import uuid4

import gspread
from google.oauth2.service_account import Credentials


EXPECTED_HEADERS = {
    "Accounts": ["id", "name", "type", "opening_balance", "active", "created_at"],
    "Categories": ["id", "name", "kind"],
    "Transactions": [
        "id",
        "txn_date",
        "kind",
        "amount",
        "account_id",
        "to_account_id",
        "category_id",
        "payee",
        "description",
        "reference",
        "created_at",
    ],
}


def validate(secrets_path: Path, write_test: bool = False) -> None:
    with secrets_path.open("rb") as secrets_file:
        secrets = tomllib.load(secrets_file)

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

    errors: list[str] = []
    actual_titles = {worksheet.title for worksheet in workbook.worksheets()}
    for title, expected in EXPECTED_HEADERS.items():
        if title not in actual_titles:
            errors.append(f"Missing worksheet: {title}")
            continue
        actual = workbook.worksheet(title).row_values(1)
        if actual != expected:
            errors.append(f"Header mismatch in worksheet: {title}")

    if errors:
        raise RuntimeError("; ".join(errors))

    print(f"Workbook access verified: {workbook.title}")
    print("Worksheet headers verified: Accounts, Categories, Transactions")

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
    args = parser.parse_args()
    validate(args.secrets, write_test=args.write_test)


if __name__ == "__main__":
    main()
