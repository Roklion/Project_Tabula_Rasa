"""Validate read access and worksheet headers without displaying ledger rows."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

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


def validate(secrets_path: Path) -> None:
    with secrets_path.open("rb") as secrets_file:
        secrets = tomllib.load(secrets_file)

    credentials = Credentials.from_service_account_info(
        secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets", type=Path, default=Path(".streamlit/secrets.toml")
    )
    args = parser.parse_args()
    validate(args.secrets)


if __name__ == "__main__":
    main()
