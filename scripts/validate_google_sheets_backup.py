"""Validate one local Project Tabula Rasa backup archive without restoring it."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError


def validate_backup_file(path: Path) -> dict[str, Any]:
    """Read and validate one archive using the current backup validator."""
    if not path.is_file():
        raise StorageValidationError("Backup archive does not exist or is not a file.")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise StorageValidationError(
            "Backup archive could not be read safely."
        ) from exc
    return GoogleSheetsStorage.validate_backup_zip(content)


def validation_report(path: Path, manifest: Mapping[str, Any]) -> str:
    """Return a concise human-readable validation record."""
    row_counts = manifest.get("row_counts")
    if not isinstance(row_counts, Mapping):
        raise StorageValidationError("Backup manifest is missing row counts.")
    rows = ", ".join(
        f"{title}={row_counts.get(title, 0)}"
        for title in ("Accounts", "Categories", "Transactions", "Mileage")
        if title in row_counts
    )
    receipt_status = (
        f"verified ({manifest.get('receipt_count', 0)} entries)"
        if manifest.get("receipt_inventory")
        else "not present; ledger-only recovery source"
    )
    return "\n".join(
        (
            f"Validated backup: {path.resolve()}",
            f"Format version: {manifest.get('format_version')}",
            f"Backup time: {manifest.get('backup_time')}",
            f"Workbook: {manifest.get('workbook_title')}",
            f"Rows: {rows}",
            f"Receipt inventory: {receipt_status}",
            "Manifest checksums: verified",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Local backup ZIP to validate")
    args = parser.parse_args()
    try:
        manifest = validate_backup_file(args.backup)
        report = validation_report(args.backup, manifest)
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    print(report)


if __name__ == "__main__":
    main()
