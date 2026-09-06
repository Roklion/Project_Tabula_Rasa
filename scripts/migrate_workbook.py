"""Upgrade a standard legacy Tabula Rasa workbook to the current schema.

This command is intentionally separate from normal application startup. It
changes the selected workbook in place and is safe to rerun after an
interrupted header/data write. The workbook is validated with the production
current-schema validator before the command reports success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import select_profile_secrets  # noqa: E402
from tabula_rasa.local_profile_store import load_business_profile_document  # noqa: E402
from tabula_rasa.storage.google_sheets import (  # noqa: E402
    MIXED_USE_WORKSHEET_HEADERS,
    PRE_MIXED_USE_WORKSHEET_HEADERS,
    SHEETS_SCOPE,
    LEGACY_TAGS_WORKBOOK_HEADERS,
    VERSION_3_WORKSHEET_HEADERS,
    VERSION_5_WORKSHEET_HEADERS,
    VERSION_6_WORKSHEET_HEADERS,
    VERSION_7_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
    GoogleSheetsStorage,
    StorageError,
    StorageValidationError,
    decode_receipt_references,
    _looks_like_partial_blank_workbook,
    _validate_hierarchy_records,
)
from scripts.migrate_payees import migrate_workbook as migrate_payees  # noqa: E402

LEGACY_MIXED_USE_TAG_MIGRATION_HEADER = "tag_ids__migration_pending"


def _values(workbook: Any) -> dict[str, list[list[Any]]]:
    return {
        worksheet.title: worksheet.get_all_values()
        for worksheet in workbook.worksheets()
    }


def _headers(rows: list[list[Any]]) -> list[str]:
    return [str(value).strip() for value in rows[0]] if rows else []


def _ensure_sheet(
    workbook: Any,
    title: str,
    worksheets: list[Any] | None = None,
    initial: dict[str, list[list[Any]]] | None = None,
) -> Any:
    sheets = worksheets if worksheets is not None else workbook.worksheets()
    for worksheet in sheets:
        if worksheet.title == title:
            return worksheet
    headers = WORKSHEET_HEADERS[title]
    worksheet = workbook.add_worksheet(title=title, rows=1000, cols=len(headers))
    worksheet.update([list(headers)], range_name="A1", raw=True)
    if worksheets is not None:
        worksheets.append(worksheet)
    if initial is not None:
        initial[title] = [list(headers)]
    return worksheet


def _ensure_headers(
    worksheet: Any,
    expected: tuple[str, ...],
    *,
    rows: list[list[Any]] | None = None,
) -> list[str]:
    if rows is None:
        rows = worksheet.get_all_values()
    if not rows or not any(str(value).strip() for row in rows for value in row):
        worksheet.update([list(expected)], range_name="A1", raw=True)
        return list(expected)
    headers = _headers(rows)
    if any(not value for value in headers):
        raise ValueError(f"{worksheet.title} worksheet has a blank header")
    if len(headers) != len(set(headers)):
        raise ValueError(f"{worksheet.title} worksheet has duplicate headers")
    return headers


def _append_columns(worksheet: Any, headers: list[str], additions: list[str]) -> list[str]:
    additions = [header for header in additions if header not in headers]
    if not additions:
        return headers
    _assert_headers_unchanged(worksheet, headers)
    updated_headers = [*headers, *additions]
    # A retry after an interrupted add_cols call may already have enough
    # trailing capacity. Reuse it instead of appending duplicate blank columns.
    column_count = getattr(worksheet, "col_count", None)
    if isinstance(column_count, int):
        if column_count < len(updated_headers):
            worksheet.add_cols(len(updated_headers) - column_count)
    else:
        worksheet.add_cols(len(additions))
    _assert_headers_unchanged(
        worksheet, [*headers, *([""] * len(additions))]
    )
    worksheet.update([updated_headers], range_name="A1", raw=True)
    return updated_headers


def _assert_headers_unchanged(worksheet: Any, expected: list[str]) -> None:
    current = [str(value).strip() for value in worksheet.row_values(1)]
    while current and not current[-1]:
        current.pop()
    expected = list(expected)
    while expected and not expected[-1]:
        expected.pop()
    if current != expected:
        raise ValueError(
            f"{worksheet.title} worksheet headers changed during migration; "
            "aborting before header update"
        )


def _validate_receipt_ownership(transactions: list[dict[str, Any]]) -> None:
    owners: dict[str, str] = {}
    for transaction in transactions:
        transaction_id = str(transaction["id"])
        for reference in decode_receipt_references(
            transaction.get("receipt_references", "")
        ):
            receipt_id = str(reference["id"])
            previous_owner = owners.get(receipt_id)
            if previous_owner is not None and previous_owner != transaction_id:
                raise ValueError("A receipt is referenced by more than one transaction")
            owners[receipt_id] = transaction_id


def _preflight(workbook: Any) -> dict[str, list[list[Any]]]:
    """Validate every existing tab before any migration write is attempted."""
    values = _values(workbook)
    if not any(
        str(value).strip()
        for rows in values.values()
        for row in rows
        for value in row
    ):
        return values
    if _looks_like_partial_blank_workbook(values):
        return values
    missing_core = sorted(
        {"Accounts", "Categories", "Transactions"} - set(values)
    )
    if missing_core:
        raise ValueError(
            "Cannot migrate a partial workbook; missing core worksheets: "
            + ", ".join(missing_core)
        )
    allowed: dict[str, set[frozenset[str]]] = {
        "Accounts": {
            frozenset(VERSION_5_WORKSHEET_HEADERS["Accounts"]),
            frozenset(VERSION_6_WORKSHEET_HEADERS["Accounts"]),
            frozenset(WORKSHEET_HEADERS["Accounts"]),
        },
        "Categories": {
            frozenset(VERSION_5_WORKSHEET_HEADERS["Categories"]),
            frozenset(VERSION_6_WORKSHEET_HEADERS["Categories"]),
            frozenset(WORKSHEET_HEADERS["Categories"]),
        },
        "Transactions": {
            frozenset(VERSION_3_WORKSHEET_HEADERS["Transactions"]),
            frozenset(VERSION_5_WORKSHEET_HEADERS["Transactions"]),
            frozenset(VERSION_6_WORKSHEET_HEADERS["Transactions"]),
            frozenset(VERSION_7_WORKSHEET_HEADERS["Transactions"]),
            frozenset(LEGACY_TAGS_WORKBOOK_HEADERS["Transactions"]),
            frozenset(PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"]),
            frozenset(WORKSHEET_HEADERS["Transactions"]),
        },
        "Mileage": {
            frozenset(VERSION_3_WORKSHEET_HEADERS["Mileage"]),
            frozenset(VERSION_5_WORKSHEET_HEADERS["Mileage"]),
            frozenset(LEGACY_TAGS_WORKBOOK_HEADERS["Mileage"]),
            frozenset(WORKSHEET_HEADERS["Mileage"]),
        },
        "Payees": {frozenset(WORKSHEET_HEADERS["Payees"])},
        "Tags": {frozenset(WORKSHEET_HEADERS["Tags"])},
        "MixedUseExpenses": {
            frozenset(
                header
                for header in MIXED_USE_WORKSHEET_HEADERS
                if header != "tag_ids"
            ),
            frozenset(MIXED_USE_WORKSHEET_HEADERS),
            frozenset(
                "tag_ids__migration_pending"
                if header == "tag_ids"
                else header
                for header in MIXED_USE_WORKSHEET_HEADERS
            ),
        },
    }
    for title, rows in values.items():
        if title not in allowed or not rows:
            continue
        headers = [str(value).strip() for value in rows[0]]
        if not headers or any(not value for value in headers):
            raise ValueError(f"{title} worksheet has a blank header")
        if len(headers) != len(set(headers)):
            raise ValueError(f"{title} worksheet has duplicate headers")
        if frozenset(headers) not in allowed[title]:
            if title == "Transactions" and "MixedUseExpenses" not in values:
                collision_layouts = {
                    frozenset(layout["Transactions"]) | frozenset(collision)
                    for layout in (
                        VERSION_3_WORKSHEET_HEADERS,
                        VERSION_5_WORKSHEET_HEADERS,
                        VERSION_6_WORKSHEET_HEADERS,
                        VERSION_7_WORKSHEET_HEADERS,
                        LEGACY_TAGS_WORKBOOK_HEADERS,
                    )
                    for collision in (
                        ("source_type",),
                        ("source_id",),
                        ("source_type", "source_id"),
                    )
                }
                if frozenset(headers) in collision_layouts:
                    continue
            raise ValueError(
                f"{title} worksheet does not match a recognized standard layout"
            )
    return values


def _clear_colliding_legacy_provenance(
    workbook: Any,
    initial: dict[str, list[list[Any]]],
) -> None:
    """Clear custom provenance-name columns before they gain current meaning."""
    if "MixedUseExpenses" in initial:
        return
    rows = initial.get("Transactions")
    if not rows:
        return
    headers = _headers(rows)
    colliding_headers = [
        header for header in ("source_type", "source_id") if header in headers
    ]
    if not colliding_headers:
        return
    indexes = {header: headers.index(header) for header in colliding_headers}
    has_orphaned_provenance = any(
        (
            "source_id" in indexes
            and len(row) > indexes["source_id"]
            and str(row[indexes["source_id"]]).strip()
        )
        or (
            "source_type" in indexes
            and len(row) > indexes["source_type"]
            and str(row[indexes["source_type"]]).strip()
            == "mixed_use_expense"
        )
        for row in rows[1:]
    )
    if has_orphaned_provenance:
        raise StorageValidationError(
            "Transactions contain mixed-use provenance, but the "
            "MixedUseExpenses worksheet is missing"
        )
    has_custom_values = any(
        "source_type" in indexes
        and len(row) > indexes["source_type"]
        and str(row[indexes["source_type"]]).strip()
        for row in rows[1:]
    )
    if not has_custom_values:
        return
    worksheet = workbook.worksheet("Transactions")
    fresh_rows = worksheet.get_all_values()
    if fresh_rows != rows:
        raise ValueError("Transactions changed during migration; aborting before write")
    cleared_rows = [
        list(row) + [""] * (len(headers) - len(row)) for row in fresh_rows
    ]
    for row in cleared_rows[1:]:
        for index in indexes.values():
            row[index] = ""
    worksheet.update(cleared_rows, range_name="A1", raw=True)
    initial["Transactions"] = cleared_rows


def _backfill_mixed_use_source_tags(workbook: Any) -> int:
    source_sheet = workbook.worksheet("MixedUseExpenses")
    transaction_sheet = workbook.worksheet("Transactions")
    def collect_updates(
        source_values: list[list[Any]],
        transaction_values: list[list[Any]],
    ) -> tuple[str, list[str], list[dict[str, object]]] | None:
        source_headers = _headers(source_values)
        transaction_headers = _headers(transaction_values)
        source_tag_header = (
            "tag_ids"
            if "tag_ids" in source_headers
            else LEGACY_MIXED_USE_TAG_MIGRATION_HEADER
        )
        required = {
            source_tag_header,
            "linked_transaction_id",
            "id",
        }
        if not required.issubset(source_headers) or not {
            "id",
            "tag_ids",
        }.issubset(transaction_headers):
            return None
        source_tag_index = source_headers.index(source_tag_header)
        linked_index = source_headers.index("linked_transaction_id")
        transaction_id_index = transaction_headers.index("id")
        transaction_tag_index = transaction_headers.index("tag_ids")
        transaction_tags = {
            str(row[transaction_id_index]).strip(): str(
                row[transaction_tag_index]
            ).strip()
            for row in transaction_values[1:]
            if len(row) > transaction_id_index
            and len(row) > transaction_tag_index
            and str(row[transaction_id_index]).strip()
        }
        updates: list[dict[str, object]] = []
        for row_number, row in enumerate(source_values[1:], start=2):
            padded = list(row) + [""] * (len(source_headers) - len(row))
            if str(padded[source_tag_index]).strip():
                continue
            tags = transaction_tags.get(str(padded[linked_index]).strip(), "")
            if tags:
                updates.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(
                            row_number, source_tag_index + 1
                        ),
                        "values": [[tags]],
                    }
                )
        return source_tag_header, source_headers, updates

    collected = collect_updates(
        source_sheet.get_all_values(), transaction_sheet.get_all_values()
    )
    if collected is None:
        return 0
    source_tag_header, source_headers, updates = collected
    if updates:
        # Re-read both worksheets immediately before writing so an edit made
        # after the initial snapshot cannot be overwritten by stale backfill.
        collected = collect_updates(
            source_sheet.get_all_values(), transaction_sheet.get_all_values()
        )
        if collected is None:
            return 0
        source_tag_header, source_headers, updates = collected
    if updates:
        source_sheet.batch_update(updates, raw=True)
    if source_tag_header == LEGACY_MIXED_USE_TAG_MIGRATION_HEADER:
        source_tag_index = source_headers.index(source_tag_header)
        _assert_headers_unchanged(source_sheet, source_headers)
        source_sheet.update(
            [["tag_ids"]],
            range_name=gspread.utils.rowcol_to_a1(1, source_tag_index + 1),
            raw=True,
        )
    return len(updates)


def migrate_workbook(workbook: Any) -> dict[str, int]:
    """Upgrade one recognized standard historical workbook in place."""
    initial = _preflight(workbook)
    worksheets = workbook.worksheets()
    is_blank = not any(
        str(value).strip()
        for rows in initial.values()
        for row in rows
        for value in row
    )
    if is_blank or _looks_like_partial_blank_workbook(initial):
        for title, headers in WORKSHEET_HEADERS.items():
            worksheet = _ensure_sheet(workbook, title, worksheets, initial)
            _ensure_headers(worksheet, headers, rows=initial.get(title))
        GoogleSheetsStorage(workbook)
        return {"worksheets": len(WORKSHEET_HEADERS), "source_tags": 0}

    _clear_colliding_legacy_provenance(workbook, initial)

    # Core hierarchy columns were introduced together in the standard v6
    # layout. Existing rows are extended by Sheets when columns are appended.
    for title in ("Accounts", "Categories"):
        worksheet = _ensure_sheet(workbook, title, worksheets, initial)
        headers = _ensure_headers(
            worksheet,
            VERSION_5_WORKSHEET_HEADERS[title],
            rows=initial.get(title),
        )
        _append_columns(worksheet, headers, ["parent_id"])

    transactions = _ensure_sheet(workbook, "Transactions", worksheets, initial)
    transaction_headers = _ensure_headers(
        transactions,
        PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        rows=initial.get("Transactions"),
    )
    transaction_headers = _append_columns(
        transactions, transaction_headers, ["receipt_references"]
    )

    # Managed payees are part of the standard historical conversion, rather
    # than an implicit production-startup migration.
    payee_result = migrate_payees(workbook)
    transaction_headers = [
        "payee_id" if header == "payee" else header for header in transaction_headers
    ]
    _append_columns(transactions, transaction_headers, ["source_type", "source_id", "tag_ids"])

    mileage = _ensure_sheet(workbook, "Mileage", worksheets, initial)
    mileage_headers = _ensure_headers(
        mileage, WORKSHEET_HEADERS["Mileage"], rows=initial.get("Mileage")
    )
    _append_columns(mileage, mileage_headers, ["tag_ids"])

    tags = _ensure_sheet(workbook, "Tags", worksheets, initial)
    _ensure_headers(
        tags,
        LEGACY_TAGS_WORKBOOK_HEADERS["Tags"],
        rows=initial.get("Tags"),
    )

    mixed = _ensure_sheet(workbook, "MixedUseExpenses", worksheets, initial)
    mixed_headers = _ensure_headers(
        mixed,
        MIXED_USE_WORKSHEET_HEADERS,
        rows=initial.get("MixedUseExpenses"),
    )
    if LEGACY_MIXED_USE_TAG_MIGRATION_HEADER in mixed_headers:
        original_mixed_headers = list(mixed_headers)
        _assert_headers_unchanged(mixed, original_mixed_headers)
        marker_index = mixed_headers.index(LEGACY_MIXED_USE_TAG_MIGRATION_HEADER)
        mixed_headers[marker_index] = "tag_ids"
        missing_columns = [
            header
            for header in ("receipt_references", "tag_ids")
            if header not in mixed_headers
        ]
        if missing_columns:
            mixed.add_cols(len(missing_columns))
            mixed_headers.extend(missing_columns)
            _assert_headers_unchanged(
                mixed,
                [
                    *original_mixed_headers,
                    *([""] * len(missing_columns)),
                ],
            )
        _assert_headers_unchanged(
            mixed,
            [
                *original_mixed_headers,
                *( [""] * len(missing_columns)),
            ],
        )
        if missing_columns:
            mixed.update([mixed_headers], range_name="A1", raw=True)
        else:
            mixed.update(
                [["tag_ids"]],
                range_name=gspread.utils.rowcol_to_a1(1, marker_index + 1),
                raw=True,
            )
    else:
        _append_columns(mixed, mixed_headers, ["receipt_references", "tag_ids"])

    source_tags = _backfill_mixed_use_source_tags(workbook)
    # This read-only validation also checks current relationship, domain, and
    # reference invariants before success is reported.
    storage = GoogleSheetsStorage(workbook)
    storage.prefetch_worksheets(*WORKSHEET_HEADERS, force_refresh=True)
    accounts = storage.list_accounts(active_only=False)
    categories = storage.list_categories()
    _validate_hierarchy_records(
        accounts,
        compatibility_field="classification",
        item_label="Account",
    )
    _validate_hierarchy_records(
        categories,
        compatibility_field="kind",
        item_label="Category",
    )
    storage.list_payees()
    storage.list_tags()
    transactions = storage.list_transactions()
    _validate_receipt_ownership(transactions)
    storage.list_mileage_trips()
    storage.list_mixed_use_expenses()
    return {
        "payees": int(payee_result.get("payees", 0)),
        "transactions": int(payee_result.get("transactions", 0)),
        "source_tags": source_tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", type=Path, default=Path(".streamlit/secrets.toml"))
    parser.add_argument("--profile", help="Saved business-profile key from --secrets")
    parser.add_argument(
        "--spreadsheet-id",
        help="Candidate workbook ID for a profile that has not been saved yet",
    )
    parser.add_argument(
        "--service-account-file",
        type=Path,
        help="Local service-account JSON file for --spreadsheet-id",
    )
    args = parser.parse_args()
    candidate_mode = (
        args.spreadsheet_id is not None or args.service_account_file is not None
    )
    if args.profile and candidate_mode:
        parser.error("--profile cannot be combined with candidate workbook options")
    if not args.profile and not candidate_mode:
        parser.error(
            "pass --profile, or pass both --spreadsheet-id and --service-account-file"
        )

    if args.profile:
        document = load_business_profile_document(args.secrets)
        secrets = select_profile_secrets(document, args.profile)
    else:
        if not args.spreadsheet_id or args.service_account_file is None:
            parser.error(
                "candidate mode requires both --spreadsheet-id and "
                "--service-account-file"
            )
        try:
            credential_info = json.loads(
                args.service_account_file.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parser.error(f"could not read --service-account-file: {exc}")
        if not isinstance(credential_info, dict):
            parser.error("--service-account-file must contain a JSON object")
        secrets = {
            "spreadsheet_id": args.spreadsheet_id,
            "gcp_service_account": credential_info,
        }

    try:
        credentials = Credentials.from_service_account_info(
            secrets["gcp_service_account"], scopes=[SHEETS_SCOPE]
        )
        workbook = gspread.authorize(credentials).open_by_key(
            str(secrets["spreadsheet_id"]).strip()
        )
        result = migrate_workbook(workbook)
    except (gspread.exceptions.GSpreadException, OSError, StorageError, ValueError) as exc:
        raise SystemExit(f"Workbook migration failed: {exc}") from exc
    print(
        "Workbook migration complete: "
        + ", ".join(f"{key}={value}" for key, value in result.items())
    )


if __name__ == "__main__":
    main()
