"""Convert a supported legacy backup archive into the current v10 format.

This is an explicit, offline migration tool.  The running application accepts
only v10 archives; conversion always writes a new archive and leaves the
source untouched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.quickbooks_import import suggested_account_classification
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets import (
    ACCOUNT_CLASSIFICATIONS,
    ACCOUNT_TYPES,
    BACKUP_FORMAT_VERSION,
    FIXED_TYPE_CLASSIFICATIONS,
    WORKSHEET_HEADERS,
    _legacy_payee_id,
    normalize_payee_name,
)


_V1_ACCOUNTS = (
    "id", "name", "type", "opening_balance", "active", "created_at"
)
_V2_ACCOUNTS = (*_V1_ACCOUNTS[:3], "classification", *_V1_ACCOUNTS[3:])
_CATEGORIES = ("id", "name", "kind")
_TRANSACTIONS_V2 = (
    "id", "txn_date", "kind", "amount", "account_id", "to_account_id",
    "category_id", "payee", "description", "reference", "created_at",
)
_MILEAGE = (
    "id", "trip_date", "miles", "vehicle", "start_location",
    "destination", "business_purpose", "notes", "created_at",
)
_TRANSACTIONS_V4 = (*_TRANSACTIONS_V2[:-1], "receipt_references", "created_at")
_V6_ACCOUNTS = (*_V2_ACCOUNTS, "parent_id")
_V6_CATEGORIES = (*_CATEGORIES, "parent_id")
_TRANSACTIONS_V7 = tuple(
    "payee_id" if header == "payee" else header for header in _TRANSACTIONS_V4
)
_PAYEES = ("id", "name", "active", "created_at")
_TAGS = _PAYEES
_TRANSACTIONS_V8 = (*_TRANSACTIONS_V7, "tag_ids")
_MILEAGE_V8 = (*_MILEAGE, "tag_ids")
_TRANSACTIONS_V9 = (*_TRANSACTIONS_V7, "source_type", "source_id", "tag_ids")
_MIXED_USE_V9 = tuple(
    header for header in WORKSHEET_HEADERS["MixedUseExpenses"] if header != "tag_ids"
)
_MAX_ARCHIVE_EXPANSION_BYTES = 100 * 1024 * 1024

SOURCE_HEADERS: dict[int, dict[str, tuple[str, ...]]] = {
    1: {"Accounts": _V1_ACCOUNTS, "Categories": _CATEGORIES, "Transactions": _TRANSACTIONS_V2},
    2: {"Accounts": _V2_ACCOUNTS, "Categories": _CATEGORIES, "Transactions": _TRANSACTIONS_V2},
    3: {"Accounts": _V2_ACCOUNTS, "Categories": _CATEGORIES, "Transactions": _TRANSACTIONS_V2, "Mileage": _MILEAGE},
    4: {"Accounts": _V2_ACCOUNTS, "Categories": _CATEGORIES, "Transactions": _TRANSACTIONS_V4, "Mileage": _MILEAGE},
    5: {"Accounts": _V2_ACCOUNTS, "Categories": _CATEGORIES, "Transactions": _TRANSACTIONS_V4, "Mileage": _MILEAGE},
    6: {"Accounts": _V6_ACCOUNTS, "Categories": _V6_CATEGORIES, "Transactions": _TRANSACTIONS_V4, "Mileage": _MILEAGE},
    7: {"Accounts": _V6_ACCOUNTS, "Categories": _V6_CATEGORIES, "Payees": _PAYEES, "Transactions": _TRANSACTIONS_V7, "Mileage": _MILEAGE},
    8: {"Accounts": _V6_ACCOUNTS, "Categories": _V6_CATEGORIES, "Payees": _PAYEES, "Tags": _TAGS, "Transactions": _TRANSACTIONS_V8, "Mileage": _MILEAGE_V8},
    9: {"Accounts": _V6_ACCOUNTS, "Categories": _V6_CATEGORIES, "Payees": _PAYEES, "Tags": _TAGS, "Transactions": _TRANSACTIONS_V9, "Mileage": _MILEAGE_V8, "MixedUseExpenses": _MIXED_USE_V9},
}


def _read_csv(
    content: bytes,
    title: str,
    expected: tuple[str, ...],
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise StorageValidationError(f"{title} backup CSV is invalid") from exc
    actual_headers = tuple(header.strip() for header in rows[0]) if rows else ()
    required_headers = set(expected)
    if not rows or not actual_headers or any(not header for header in actual_headers):
        raise StorageValidationError(f"{title} backup headers are invalid")
    if len(actual_headers) != len(set(actual_headers)) or not required_headers.issubset(actual_headers):
        raise StorageValidationError(f"{title} backup headers are invalid")
    records = []
    for row in rows[1:]:
        if len(row) > len(actual_headers):
            raise StorageValidationError(f"{title} backup has an over-wide row")
        padded = row + [""] * (len(actual_headers) - len(row))
        if any(value.strip() for value in padded):
            records.append(dict(zip(actual_headers, padded)))
    return actual_headers, records


def _read_source(backup: bytes) -> tuple[int, dict[str, Any], dict[str, list[dict[str, str]]], bytes | None]:
    try:
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise StorageValidationError("Backup files are duplicated")
            if sum(item.file_size for item in archive.infolist()) > _MAX_ARCHIVE_EXPANSION_BYTES:
                raise StorageValidationError("Backup is too large to migrate safely")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict):
                raise StorageValidationError("Backup manifest must be a JSON object")
            version = manifest.get("format_version")
            if version not in SOURCE_HEADERS:
                raise StorageValidationError("Only backup formats 1 through 9 can be migrated")
            schemas = SOURCE_HEADERS[version]
            names = set(names)
            expected_names = {f"{title}.csv" for title in schemas} | {"manifest.json"}
            optional_payees = version < 7 and "Payees.csv" in names
            if optional_payees:
                expected_names.add("Payees.csv")
            if version >= 5:
                expected_names.add("receipts.json")
            if names != expected_names:
                raise StorageValidationError("Backup contains unexpected legacy files")
            tables = {}
            checksums = manifest.get("sha256")
            row_counts = manifest.get("row_counts")
            worksheet_headers = manifest.get("worksheet_headers")
            if not all(
                isinstance(value, dict)
                for value in (checksums, row_counts, worksheet_headers)
            ):
                raise StorageValidationError("Backup manifest is missing validation metadata")
            expected_checksum_names = {f"{title}.csv" for title in schemas}
            if optional_payees:
                expected_checksum_names.add("Payees.csv")
            if version >= 5:
                expected_checksum_names.add("receipts.json")
            if set(checksums) != expected_checksum_names:
                raise StorageValidationError("Backup manifest checksum entries are invalid")
            expected_row_count_names = {title for title in schemas}
            if optional_payees:
                expected_row_count_names.add("Payees")
            if not expected_row_count_names.issubset(row_counts):
                raise StorageValidationError("Backup manifest row count entries are invalid")
            for title, headers in schemas.items():
                content = archive.read(f"{title}.csv")
                expected_hash = checksums.get(f"{title}.csv")
                if not expected_hash or hashlib.sha256(content).hexdigest() != expected_hash:
                    raise StorageValidationError(f"{title} backup checksum does not match")
                actual_headers, rows = _read_csv(content, title, headers)
                if worksheet_headers.get(title) != list(actual_headers):
                    raise StorageValidationError(f"{title} backup headers are invalid")
                if row_counts[title] != len(rows):
                    raise StorageValidationError(f"{title} backup row count does not match")
                tables[title] = rows
            if optional_payees:
                content = archive.read("Payees.csv")
                expected_hash = checksums.get("Payees.csv")
                if not expected_hash or hashlib.sha256(content).hexdigest() != expected_hash:
                    raise StorageValidationError("Payees backup checksum does not match")
                actual_headers, payees = _read_csv(content, "Payees", _PAYEES)
                if worksheet_headers.get("Payees") != list(actual_headers):
                    raise StorageValidationError("Payees backup headers are invalid")
                if row_counts["Payees"] != len(payees):
                    raise StorageValidationError("Payees backup row count does not match")
                tables["Payees"] = payees
            receipts = archive.read("receipts.json") if version >= 5 else None
            if receipts is not None:
                expected_hash = checksums.get("receipts.json")
                if not expected_hash or hashlib.sha256(receipts).hexdigest() != expected_hash:
                    raise StorageValidationError("receipts.json backup checksum does not match")
    except StorageValidationError:
        raise
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise StorageValidationError("Backup is not a readable legacy ZIP archive") from exc
    return version, manifest, tables, receipts


def _active(value: object, label: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return "TRUE"
    if normalized in {"false", "0", "no"}:
        return "FALSE"
    raise StorageValidationError(f"{label} active value is invalid")


def _accounts(records: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for source in records:
        row = dict(source)
        account_type = row.get("type", "").strip()
        if account_type == "Loan":
            account_type = "Short-term debt"
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError(f"Unknown legacy account type '{account_type}'")
        classification = row.get("classification", "").strip().title()
        if classification not in ACCOUNT_CLASSIFICATIONS:
            classification = suggested_account_classification(row.get("name", ""), account_type)
        fixed = FIXED_TYPE_CLASSIFICATIONS.get(account_type)
        if fixed is not None:
            classification = fixed
        row.update({"type": account_type, "classification": classification, "active": _active(row.get("active", ""), "Account")})
        output.append(row)
    return output


def _payees_and_transactions(
    tables: dict[str, list[dict[str, str]]], version: int, manifest: dict[str, Any]
) -> None:
    if version >= 7:
        tables["Payees"] = [
            {header: str(row.get(header, "")) for header in _PAYEES}
            for row in tables["Payees"]
        ]
        for row in tables["Payees"]:
            row["active"] = _active(row.get("active", "TRUE"), "Payee")
        return
    payees: dict[str, dict[str, str]] = {}
    for source in tables.get("Payees", []):
        name = " ".join(str(source.get("name", "")).split())
        key = normalize_payee_name(name)
        if key:
            payees[key] = {
                "id": str(source.get("id", "")).strip(),
                "name": name,
                "active": _active(source.get("active", "TRUE"), "Payee"),
                "created_at": str(source.get("created_at") or ""),
            }
    fallback_created_at = str(manifest.get("backup_time") or "1970-01-01T00:00:00+00:00")
    for row in tables["Transactions"]:
        name = str(row.pop("payee", "")).strip()
        key = normalize_payee_name(name)
        if not key:
            row["payee_id"] = ""
            continue
        if key not in payees:
            payees[key] = {
                "id": _legacy_payee_id(name),
                "name": " ".join(name.split()),
                "active": "TRUE",
                "created_at": str(row.get("created_at") or fallback_created_at),
            }
        row["payee_id"] = payees[key]["id"]
    tables["Payees"] = list(payees.values())


def _current_tables(version: int, manifest: dict[str, Any], source: dict[str, list[dict[str, str]]]) -> dict[str, tuple[list[str], list[dict[str, str]]]]:
    tables: dict[str, list[dict[str, str]]] = {title: [dict(row) for row in rows] for title, rows in source.items()}
    tables["Accounts"] = _accounts(tables["Accounts"])
    for title in ("Accounts", "Categories"):
        for row in tables[title]:
            row.setdefault("parent_id", "")
    _payees_and_transactions(tables, version, manifest)
    if "Tags" not in tables:
        tables["Tags"] = []
    for row in tables["Tags"]:
        row["active"] = _active(row.get("active", "TRUE"), "Tag")
    if "Mileage" not in tables:
        tables["Mileage"] = []
    if "MixedUseExpenses" not in tables:
        tables["MixedUseExpenses"] = []

    for row in tables["Transactions"]:
        if version < 5:
            # Pre-inventory archives cannot prove receipt identity or retain
            # the integrity metadata required by v10. Keep the source archive
            # intact, but unlink those historical associations in the output.
            row["receipt_references"] = ""
        row.setdefault("receipt_references", "")
        if version < 9:
            # Provenance was introduced with the mixed-use backup format.
            # Discard extra legacy columns rather than restoring untrusted links.
            row["source_type"] = ""
            row["source_id"] = ""
        else:
            row.setdefault("source_type", "")
            row.setdefault("source_id", "")
        row.setdefault("tag_ids", "[]")
    for row in tables["Mileage"]:
        row.setdefault("tag_ids", "[]")
    for row in tables["MixedUseExpenses"]:
        row.setdefault("tag_ids", "[]")

    transactions_by_id = {str(row.get("id")): row for row in tables["Transactions"]}
    for source_row in tables["MixedUseExpenses"]:
        linked = transactions_by_id.get(str(source_row.get("linked_transaction_id")))
        if linked is not None:
            source_row["tag_ids"] = linked.get("tag_ids", "[]")

    return {
        title: ([*WORKSHEET_HEADERS[title]], [
            {header: str(row.get(header, "")) for header in WORKSHEET_HEADERS[title]}
            for row in tables[title]
        ])
        for title in WORKSHEET_HEADERS
    }


def _encode_csv(headers: list[str], records: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([[record.get(header, "") for header in headers] for record in records])
    return buffer.getvalue().encode("utf-8")


def migrate_legacy_backup(backup: bytes, *, profile_key: str | None = None) -> bytes:
    """Return a validated v10 archive converted from a v1-v9 archive."""
    version, source_manifest, source_tables, source_receipts = _read_source(backup)
    if version < 5 and profile_key is None:
        raise StorageValidationError(
            "Ledger-only legacy migrations require an explicit profile key"
        )
    profile_key = profile_key or "legacy"
    tables = _current_tables(version, source_manifest, source_tables)
    csv_files = {
        f"{title}.csv": _encode_csv(headers, records)
        for title, (headers, records) in tables.items()
    }
    if source_receipts is None:
        receipt_manifest = {
            "schema_version": 1,
            "business_profile_key": profile_key,
            "receipts": [],
        }
        receipts_bytes = (json.dumps(receipt_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    else:
        receipts_bytes = source_receipts
    output_manifest = dict(source_manifest)
    output_manifest.update({
        "format_version": BACKUP_FORMAT_VERSION,
        "row_counts": {title: len(records) for title, (_, records) in tables.items()},
        "sha256": {
            **{name: hashlib.sha256(content).hexdigest() for name, content in csv_files.items()},
            "receipts.json": hashlib.sha256(receipts_bytes).hexdigest(),
        },
        "worksheet_headers": {title: headers for title, (headers, _) in tables.items()},
        "conversion": {
            "source_archive_sha256": hashlib.sha256(backup).hexdigest(),
            "source_format_version": version,
            "target_format_version": BACKUP_FORMAT_VERSION,
            "tool": "scripts/migrate_legacy_backup.py",
        },
    })
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in csv_files.items():
            archive.writestr(name, content)
        archive.writestr("receipts.json", receipts_bytes)
        archive.writestr("manifest.json", (json.dumps(output_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    converted = output.getvalue()
    validated = GoogleSheetsStorage.validate_backup_zip(converted)
    if validated.get("format_version") != BACKUP_FORMAT_VERSION:
        raise StorageValidationError("Converted backup did not validate as format version 10")
    return converted


def default_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}-format10.zip")


def migrate_backup_file(
    source: Path,
    output: Path | None = None,
    *,
    profile_key: str | None = None,
) -> Path:
    source = source.resolve()
    destination = (output or default_output_path(source)).resolve()
    if source == destination:
        raise StorageValidationError("Migration output must differ from the source archive")
    converted = migrate_legacy_backup(source.read_bytes(), profile_key=profile_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output_file:
        output_file.write(converted)
    GoogleSheetsStorage.validate_backup_zip(destination.read_bytes())
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Legacy v1-v9 backup ZIP")
    parser.add_argument("--output", type=Path, help="Separate v10 output ZIP (never overwritten)")
    parser.add_argument("--profile", help="Profile key for a ledger-only archive's empty receipt inventory")
    args = parser.parse_args()
    try:
        profile_key = args.profile
        if profile_key is None:
            version, _, _, _ = _read_source(args.backup.read_bytes())
            if version < 5:
                raise StorageValidationError(
                    "Ledger-only legacy migrations require --profile PROFILE_KEY"
                )
            profile_key = "legacy"
        destination = migrate_backup_file(args.backup, args.output, profile_key=profile_key)
    except (OSError, StorageValidationError) as error:
        raise SystemExit(f"Migration failed: {error}") from error
    print(f"Validated format-10 backup created: {destination}")


if __name__ == "__main__":
    main()
