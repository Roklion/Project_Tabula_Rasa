"""Convert a validated Project Tabula Rasa format-1 backup to format 2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.quickbooks_import import suggested_account_classification
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets import (
    ACCOUNT_CLASSIFICATIONS,
    ACCOUNT_TYPES,
    FIXED_TYPE_CLASSIFICATIONS,
    LEGACY_BACKUP_HEADERS,
)


SOURCE_FORMAT_VERSION = 1
TARGET_FORMAT_VERSION = 2
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _parse_csv(
    title: str,
    content: bytes,
    manifest: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        parsed_rows = list(
            csv.reader(io.StringIO(content.decode("utf-8"), newline=""))
        )
    except (UnicodeDecodeError, csv.Error) as error:
        raise StorageValidationError(
            f"{title} backup CSV is invalid"
        ) from error
    if not parsed_rows:
        raise StorageValidationError(f"{title} backup has no header row")

    headers = [value.strip() for value in parsed_rows[0]]
    required_headers = set(LEGACY_BACKUP_HEADERS[title])
    if title == "Accounts":
        required_headers.discard("classification")
    worksheet_headers = manifest["worksheet_headers"]
    if (
        any(not value for value in headers)
        or len(headers) != len(set(headers))
        or not required_headers.issubset(headers)
        or worksheet_headers.get(title) != headers
    ):
        raise StorageValidationError(f"{title} backup headers are invalid")

    records: list[dict[str, str]] = []
    for raw_row in parsed_rows[1:]:
        if len(raw_row) > len(headers):
            raise StorageValidationError(
                f"{title} backup has an over-wide row"
            )
        padded = raw_row + [""] * (len(headers) - len(raw_row))
        if any(value.strip() for value in padded):
            records.append(dict(zip(headers, padded)))

    if manifest["row_counts"].get(title) != len(records):
        raise StorageValidationError(
            f"{title} backup row count does not match"
        )
    record_ids = [record.get("id", "").strip() for record in records]
    if any(not record_id for record_id in record_ids) or len(
        record_ids
    ) != len(set(record_ids)):
        raise StorageValidationError(
            f"{title} backup IDs are missing or duplicated"
        )
    return headers, records


def _read_format1_backup(
    backup: bytes,
) -> tuple[dict[str, Any], dict[str, tuple[list[str], list[dict[str, str]]]]]:
    required_files = {
        f"{title}.csv" for title in LEGACY_BACKUP_HEADERS
    } | {"manifest.json"}
    try:
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != required_files:
                raise StorageValidationError(
                    "Format-1 backup must contain exactly Accounts.csv, "
                    "Categories.csv, Transactions.csv, and manifest.json"
                )
            if (
                sum(item.file_size for item in archive.infolist())
                > MAX_UNCOMPRESSED_BYTES
            ):
                raise StorageValidationError(
                    "Backup is too large to convert safely"
                )
            manifest_bytes = archive.read("manifest.json")
            csv_files = {
                title: archive.read(f"{title}.csv")
                for title in LEGACY_BACKUP_HEADERS
            }
    except (zipfile.BadZipFile, OSError) as error:
        raise StorageValidationError(
            "Backup is not a readable ZIP archive"
        ) from error

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StorageValidationError(
            "Backup manifest is not valid UTF-8 JSON"
        ) from error
    if not isinstance(manifest, dict):
        raise StorageValidationError("Backup manifest must be a JSON object")
    if manifest.get("format_version") != SOURCE_FORMAT_VERSION:
        raise StorageValidationError(
            "Only backup format version 1 can be converted"
        )
    if not all(
        isinstance(manifest.get(field), dict)
        for field in ("row_counts", "sha256", "worksheet_headers")
    ):
        raise StorageValidationError(
            "Backup manifest is missing validation metadata"
        )

    tables: dict[
        str, tuple[list[str], list[dict[str, str]]]
    ] = {}
    for title, content in csv_files.items():
        expected_hash = manifest["sha256"].get(f"{title}.csv")
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise StorageValidationError(
                f"{title} backup checksum does not match"
            )
        tables[title] = _parse_csv(title, content, manifest)

    account_ids = {
        record["id"] for record in tables["Accounts"][1]
    }
    category_ids = {
        record["id"] for record in tables["Categories"][1]
    }
    for transaction in tables["Transactions"][1]:
        if transaction.get("account_id") not in account_ids:
            raise StorageValidationError(
                "Backup contains an unknown transaction account"
            )
        destination = transaction.get("to_account_id", "")
        if destination and destination not in account_ids:
            raise StorageValidationError(
                "Backup contains an unknown transfer account"
            )
        category = transaction.get("category_id", "")
        if category and category not in category_ids:
            raise StorageValidationError(
                "Backup contains an unknown transaction category"
            )
    return manifest, tables


def _normalized_active(value: Any) -> str:
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return "TRUE"
    if text in {"false", "0", "no"}:
        return "FALSE"
    raise StorageValidationError(
        "Account active value must be true, false, 1, 0, yes, or no"
    )


def _normalize_accounts(
    headers: list[str],
    records: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    output_headers = list(headers)
    if "classification" not in output_headers:
        output_headers.append("classification")

    normalized: list[dict[str, str]] = []
    for record in records:
        item = dict(record)
        account_type = item.get("type", "").strip()
        if account_type == "Loan":
            account_type = "Short-term debt"
        if account_type not in ACCOUNT_TYPES:
            raise StorageValidationError(
                f"Unknown legacy account type '{account_type}'"
            )
        classification = item.get("classification", "").strip().title()
        if classification not in ACCOUNT_CLASSIFICATIONS:
            classification = suggested_account_classification(
                item.get("name", ""),
                account_type,
            )
        required_classification = FIXED_TYPE_CLASSIFICATIONS.get(account_type)
        if (
            required_classification is not None
            and classification != required_classification
        ):
            classification = required_classification
        item["type"] = account_type
        item["classification"] = classification
        item["active"] = _normalized_active(item.get("active", ""))
        normalized.append(item)
    return output_headers, normalized


def _encode_csv(
    headers: list[str],
    records: list[dict[str, str]],
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for record in records:
        writer.writerow([record.get(header, "") for header in headers])
    return buffer.getvalue().encode("utf-8")


def convert_backup_v1_to_v2(backup: bytes) -> bytes:
    """Return a validated format-2 archive without changing the source bytes."""
    source_manifest, source_tables = _read_format1_backup(backup)
    output_tables = dict(source_tables)
    output_tables["Accounts"] = _normalize_accounts(
        *source_tables["Accounts"]
    )
    csv_files = {
        f"{title}.csv": _encode_csv(headers, records)
        for title, (headers, records) in output_tables.items()
    }
    converted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output_manifest = dict(source_manifest)
    output_manifest.update(
        {
            "format_version": TARGET_FORMAT_VERSION,
            "row_counts": {
                title: len(records)
                for title, (_, records) in output_tables.items()
            },
            "sha256": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in csv_files.items()
            },
            "worksheet_headers": {
                title: headers
                for title, (headers, _) in output_tables.items()
            },
            "conversion": {
                "converted_at": converted_at,
                "source_archive_sha256": hashlib.sha256(backup).hexdigest(),
                "source_format_version": SOURCE_FORMAT_VERSION,
                "target_format_version": TARGET_FORMAT_VERSION,
                "tool": "scripts/convert_backup_v1_to_v2.py",
            },
        }
    )

    output = io.BytesIO()
    with zipfile.ZipFile(
        output, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for name, content in csv_files.items():
            archive.writestr(name, content)
        archive.writestr(
            "manifest.json",
            (
                json.dumps(output_manifest, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
    converted = output.getvalue()
    validated = GoogleSheetsStorage.validate_backup_zip(converted)
    if validated.get("format_version") != TARGET_FORMAT_VERSION:
        raise StorageValidationError(
            "Converted backup did not validate as format version 2"
        )
    return converted


def default_output_path(source: Path) -> Path:
    """Return a separate output name that retention scripts will not treat as new."""
    return source.with_name(f"{source.stem}-format2.zip")


def convert_backup_file(
    source: Path,
    output: Path | None = None,
) -> Path:
    """Convert one file while refusing to overwrite either source or output."""
    source = source.resolve()
    destination = (output or default_output_path(source)).resolve()
    if source == destination:
        raise StorageValidationError(
            "Conversion output must differ from the source archive"
        )
    converted = convert_backup_v1_to_v2(source.read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output_file:
        output_file.write(converted)
    GoogleSheetsStorage.validate_backup_zip(destination.read_bytes())
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Format-1 backup ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Separate output ZIP; defaults to SOURCE-format2.zip and is never "
            "overwritten"
        ),
    )
    args = parser.parse_args()
    try:
        destination = convert_backup_file(args.backup, args.output)
    except (OSError, StorageValidationError) as error:
        raise SystemExit(f"Conversion failed: {error}") from error
    print(f"Validated format-2 backup created: {destination}")


if __name__ == "__main__":
    main()
