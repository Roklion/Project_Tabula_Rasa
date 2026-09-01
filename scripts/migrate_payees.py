"""One-time migration from transaction payee text to managed Payees."""

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

from tabula_rasa.storage.google_sheets import (  # noqa: E402
    SHEETS_SCOPE,
    WORKSHEET_HEADERS,
    _legacy_payee_id,
    _utc_now,
    _validate_payee_records,
    normalize_payee_name,
)


def migrate_payee_rows(
    transactions: Iterable[Mapping[str, Any]],
    existing_payees: Iterable[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return deduplicated payees and transactions with stable payee IDs."""
    payees_by_key = {
        normalize_payee_name(item.get("name")): {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "active": str(item.get("active", "TRUE")),
            "created_at": str(item.get("created_at", "")),
        }
        for item in existing_payees
        if normalize_payee_name(item.get("name"))
    }
    migrated: list[dict[str, str]] = []
    for source in transactions:
        row = {
            str(key): str(value) if value is not None else ""
            for key, value in source.items()
        }
        legacy_name = row.pop("payee", "").strip()
        payee_id = row.get("payee_id", "").strip()
        if not payee_id and legacy_name:
            key = normalize_payee_name(legacy_name)
            payee = payees_by_key.get(key)
            if payee is None:
                payee = {
                    "id": _legacy_payee_id(legacy_name),
                    "name": " ".join(legacy_name.split()),
                    "active": "TRUE",
                    "created_at": _utc_now(),
                }
                payees_by_key[key] = payee
            payee_id = payee["id"]
        row["payee_id"] = payee_id
        migrated.append(row)
    return list(payees_by_key.values()), migrated


def migrate_workbook(workbook: Any) -> dict[str, int]:
    """Migrate one legacy workbook in place; safe to rerun."""
    transactions_sheet = workbook.worksheet("Transactions")
    transaction_values = transactions_sheet.get_all_values()
    if not transaction_values:
        return {"payees": 0, "transactions": 0}
    headers = [str(value).strip() for value in transaction_values[0]]
    payee_sheet = next((sheet for sheet in workbook.worksheets() if sheet.title == "Payees"), None)
    if "payee_id" not in headers and "payee" not in headers:
        raise ValueError("Transactions worksheet has neither payee nor payee_id")

    if payee_sheet is None:
        payee_sheet = workbook.add_worksheet("Payees", rows=1000, cols=4)
        payee_sheet.update([list(WORKSHEET_HEADERS["Payees"])], range_name="A1", raw=True)
        payee_values = [list(WORKSHEET_HEADERS["Payees"])]
    else:
        payee_values = payee_sheet.get_all_values()
    if not payee_values:
        payee_sheet.update(
            [list(WORKSHEET_HEADERS["Payees"])], range_name="A1", raw=True
        )
        payee_values = [list(WORKSHEET_HEADERS["Payees"])]
    payee_headers = [str(value).strip() for value in payee_values[0]]
    required_payee_headers = set(WORKSHEET_HEADERS["Payees"])
    missing_headers = required_payee_headers - set(payee_headers)
    if missing_headers:
        missing = ", ".join(sorted(missing_headers))
        raise ValueError(f"Payees worksheet is missing required headers: {missing}")
    payee_rows: list[list[str]] = []
    payees_changed = False
    active_index = payee_headers.index("active")
    for source_row in payee_values[1:]:
        row = list(source_row) + [""] * (len(payee_headers) - len(source_row))
        if any(str(value).strip() for value in row) and not row[active_index].strip():
            row[active_index] = "TRUE"
            payees_changed = True
        payee_rows.append(row[: len(payee_headers)])
    existing = [
        dict(zip(payee_headers, row))
        for row in payee_rows
        if any(str(value).strip() for value in row)
    ]
    _validate_payee_records(existing)
    if payees_changed:
        payee_sheet.update(
            [payee_headers, *payee_rows], range_name="A1", raw=True
        )
    rows = [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in transaction_values[1:]]
    if "payee" not in headers:
        known_payee_ids = {str(item.get("id", "")).strip() for item in existing}
        legacy_rows = []
        for row in rows:
            value = str(row.get("payee_id", "")).strip()
            if value and value not in known_payee_ids:
                legacy_rows.append(row)
                row["payee"] = value
                row["payee_id"] = ""
        if not legacy_rows:
            return {
                "payees": 0,
                "transactions": 0,
            }
    payees, migrated = migrate_payee_rows(rows, existing)
    new_headers = ["payee_id" if header == "payee" else header for header in headers]
    existing_ids = {str(item.get("id", "")).strip() for item in existing}
    new_payees = [item for item in payees if item["id"] not in existing_ids]
    if new_payees:
        payee_sheet.append_rows(
            [
                [item.get(header, "") for header in payee_headers]
                for item in new_payees
            ],
            value_input_option="RAW",
        )
    transactions_sheet.update(
        [new_headers]
        + [[row.get(header, "") for header in new_headers] for row in migrated],
        range_name="A1",
        raw=True,
    )
    return {"payees": len(new_payees), "transactions": len(migrated)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", type=Path, default=Path(".streamlit/secrets.toml"))
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    from tabula_rasa.business_profiles import select_profile_secrets
    from tabula_rasa.local_profile_store import load_business_profile_document

    document = load_business_profile_document(args.secrets)
    secrets = select_profile_secrets(document, args.profile)
    credentials = Credentials.from_service_account_info(
        secrets["gcp_service_account"],
        scopes=[SHEETS_SCOPE],
    )
    workbook = gspread.authorize(credentials).open_by_key(str(secrets["spreadsheet_id"]).strip())
    result = migrate_workbook(workbook)
    print(f"Payee migration complete: created={result['payees']}, transactions={result['transactions']}")


if __name__ == "__main__":
    main()
