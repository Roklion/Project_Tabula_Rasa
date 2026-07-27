from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.convert_backup_v1_to_v2 import (
    convert_backup_file,
    convert_backup_v1_to_v2,
    default_output_path,
)
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _format1_backup(*, tamper_accounts: bool = False) -> bytes:
    csv_files = {
        "Accounts.csv": _csv_bytes(
            [
                "id",
                "name",
                "type",
                "opening_balance",
                "active",
                "created_at",
            ],
            [
                [
                    "account-1",
                    "Checking",
                    "Bank",
                    "100.00",
                    "1",
                    "2026-07-19T12:00:00Z",
                ],
                [
                    "account-2",
                    "Equipment loan",
                    "Loan",
                    "-50.00",
                    "yes",
                    "2026-07-19T12:00:00Z",
                ],
            ],
        ),
        "Categories.csv": _csv_bytes(
            ["id", "name", "kind"],
            [["category-1", "Sales", "Income"]],
        ),
        "Transactions.csv": _csv_bytes(
            [
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
            [
                [
                    "transaction-1",
                    "2026-07-19",
                    "Income",
                    "25.00",
                    "account-1",
                    "",
                    "category-1",
                    "Customer",
                    "Invoice",
                    "INV-1",
                    "2026-07-19T12:30:00Z",
                ]
            ],
        ),
    }
    manifest = {
        "backup_time": "2026-07-19T13:00:00Z",
        "format_version": 1,
        "row_counts": {
            "Accounts": 2,
            "Categories": 1,
            "Transactions": 1,
        },
        "sha256": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in csv_files.items()
        },
        "workbook_title": "Sanitized test ledger",
        "worksheet_headers": {
            title.removesuffix(".csv"): next(
                csv.reader(io.StringIO(content.decode("utf-8")))
            )
            for title, content in csv_files.items()
        },
    }
    if tamper_accounts:
        csv_files["Accounts.csv"] += b"tampered,row\n"

    output = io.BytesIO()
    with zipfile.ZipFile(
        output, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for name, content in csv_files.items():
            archive.writestr(name, content)
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
    return output.getvalue()


class ConvertBackupV1ToV2Tests(unittest.TestCase):
    def test_converts_and_normalizes_legacy_account_schema(self) -> None:
        source = _format1_backup()

        converted = convert_backup_v1_to_v2(source)

        manifest = GoogleSheetsStorage.validate_backup_zip(converted)
        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(
            manifest["conversion"]["source_archive_sha256"],
            hashlib.sha256(source).hexdigest(),
        )
        with zipfile.ZipFile(io.BytesIO(converted)) as archive:
            accounts = list(
                csv.DictReader(
                    io.StringIO(
                        archive.read("Accounts.csv").decode("utf-8")
                    )
                )
            )
        self.assertEqual(accounts[0]["classification"], "Asset")
        self.assertEqual(accounts[0]["active"], "TRUE")
        self.assertEqual(accounts[1]["type"], "Short-term debt")
        self.assertEqual(accounts[1]["classification"], "Liability")
        self.assertEqual(accounts[1]["active"], "TRUE")

    def test_refuses_a_tampered_source_archive(self) -> None:
        with self.assertRaisesRegex(
            StorageValidationError,
            "Accounts backup checksum does not match",
        ):
            convert_backup_v1_to_v2(
                _format1_backup(tamper_accounts=True)
            )

    def test_file_conversion_never_overwrites_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "backup.zip"
            source_bytes = _format1_backup()
            source.write_bytes(source_bytes)
            destination = default_output_path(source)
            destination.write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                convert_backup_file(source)

            self.assertEqual(destination.read_bytes(), b"existing")
            self.assertEqual(source.read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
