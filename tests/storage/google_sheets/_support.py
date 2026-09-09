from __future__ import annotations

import csv

import hashlib

import io

import json

import zipfile

from collections.abc import Callable, Mapping

from unittest.mock import Mock, patch

import gspread

import pytest

from google.oauth2.service_account import Credentials

from tabula_rasa.storage.google_sheets import (
    BACKUP_FORMAT_VERSION,
    decode_receipt_references,
    GoogleSheetsStorage,
    _mutation_guidance,
    SHEETS_SCOPE,
    SHEETS_READONLY_SCOPE,
    StorageAuthenticationError,
    StorageConflictError,
    StorageInitializationError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    StorageWorkbookAccessError,
    WORKSHEET_HEADERS,
)
from scripts.migration_schemas import VERSION_5_WORKSHEET_HEADERS

from tabula_rasa.quickbooks_import import (
    general_ledger_rows,
    suggested_account_classification,
    suggested_account_type,
)

from tabula_rasa.ledger_reporting import account_balances

from tabula_rasa.receipt_manifest import (
    build_receipt_manifest,
    ReceiptManifestError,
)

from tests.fakes import FakeWorkbook

TEST_RECEIPT_REFERENCE = {
    "id": "receipt123456",
    "name": "customer-receipt.pdf",
    "receipt_id": "a" * 32,
    "original_filename": "customer-receipt.pdf",
    "mime_type": "application/pdf",
    "byte_size": 7,
    "sha256": "b" * 64,
}

def drive_file_from_reference(
    reference: dict[str, object],
    *,
    profile_key: str = "test",
) -> dict[str, object]:
    return {
        "id": reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": reference["receipt_id"],
            "tabulaRasaSha256": reference["sha256"],
            "tabulaRasaOriginalName": reference["original_filename"],
        },
    }

def backup_receipt_manifest(storage: GoogleSheetsStorage) -> dict[str, object]:
    transactions = storage.list_transactions(_force_refresh=True)
    files = []
    for transaction in transactions:
        for reference in decode_receipt_references(
            transaction.get("receipt_references", "")
        ):
            if "receipt_id" not in reference:
                continue
            files.append(drive_file_from_reference(reference))
    return build_receipt_manifest("test", transactions, files)

def rewrite_backup_tables(
    backup: bytes,
    transforms: Mapping[str, Callable[[list[list[str]]], None]],
    *,
    format_version: int | None = None,
) -> bytes:
    """Rewrite selected backup CSVs and keep checksums/metadata consistent."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(contents["manifest.json"])
    if format_version is not None:
        manifest["format_version"] = format_version
        if format_version < BACKUP_FORMAT_VERSION and "Payees.csv" in contents:
            payee_rows = list(
                csv.reader(io.StringIO(contents["Payees.csv"].decode("utf-8")))
            )
            payee_headers = payee_rows[0]
            payee_id_index = payee_headers.index("id")
            payee_name_index = payee_headers.index("name")
            payee_names = {
                row[payee_id_index]: row[payee_name_index]
                for row in payee_rows[1:]
            }
            transaction_rows = list(
                csv.reader(io.StringIO(contents["Transactions.csv"].decode("utf-8")))
            )
            transaction_headers = transaction_rows[0]
            payee_id_index = transaction_headers.index("payee_id")
            transaction_headers[payee_id_index] = "payee"
            for row in transaction_rows[1:]:
                row[payee_id_index] = payee_names.get(row[payee_id_index], "")
            csv_buffer = io.StringIO(newline="")
            csv.writer(csv_buffer, lineterminator="\n").writerows(transaction_rows)
            contents["Transactions.csv"] = csv_buffer.getvalue().encode("utf-8")
            manifest["worksheet_headers"]["Transactions"] = transaction_headers
            manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
                contents["Transactions.csv"]
            ).hexdigest()
            contents.pop("Payees.csv")
            manifest["worksheet_headers"].pop("Payees", None)
            manifest["row_counts"].pop("Payees", None)
            manifest["sha256"].pop("Payees.csv", None)
        if format_version is not None and format_version < BACKUP_FORMAT_VERSION:
            for title in ("Transactions", "Mileage"):
                filename = f"{title}.csv"
                rows = list(
                    csv.reader(io.StringIO(contents[filename].decode("utf-8")))
                )
                if "tag_ids" in rows[0]:
                    tag_index = rows[0].index("tag_ids")
                    rows = [
                        [value for index, value in enumerate(row) if index != tag_index]
                        for row in rows
                    ]
                    csv_buffer = io.StringIO(newline="")
                    csv.writer(csv_buffer, lineterminator="\n").writerows(rows)
                    contents[filename] = csv_buffer.getvalue().encode("utf-8")
                    manifest["worksheet_headers"][title] = rows[0]
                    manifest["row_counts"][title] = len(rows) - 1
                    manifest["sha256"][filename] = hashlib.sha256(
                        contents[filename]
                    ).hexdigest()
            contents.pop("Tags.csv", None)
            manifest["worksheet_headers"].pop("Tags", None)
            manifest["row_counts"].pop("Tags", None)
            manifest["sha256"].pop("Tags.csv", None)
    for title, transform in transforms.items():
        filename = f"{title}.csv"
        rows = list(
            csv.reader(io.StringIO(contents[filename].decode("utf-8")))
        )
        transform(rows)
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(rows)
        contents[filename] = csv_buffer.getvalue().encode("utf-8")
        manifest["worksheet_headers"][title] = rows[0]
        manifest["row_counts"][title] = len(rows) - 1
        manifest["sha256"][filename] = hashlib.sha256(
            contents[filename]
        ).hexdigest()
    if format_version is not None and format_version < BACKUP_FORMAT_VERSION:
        contents.pop("MixedUseExpenses.csv", None)
        manifest["worksheet_headers"].pop("MixedUseExpenses", None)
        manifest["row_counts"].pop("MixedUseExpenses", None)
        manifest["sha256"].pop("MixedUseExpenses.csv", None)
    contents["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in contents.items():
            destination.writestr(name, content)
    return output.getvalue()


class GoogleSheetsStorageTestCase:
    def setup_method(self) -> None:
        self.workbook = FakeWorkbook()
        self.storage = GoogleSheetsStorage(self.workbook, sleeper=lambda _: None)



__all__ = [
    'BACKUP_FORMAT_VERSION',
    'Callable',
    'Credentials',
    'FakeWorkbook',
    'GoogleSheetsStorage',
    'GoogleSheetsStorageTestCase',
    'Mapping',
    'Mock',
    'ReceiptManifestError',
    'SHEETS_READONLY_SCOPE',
    'SHEETS_SCOPE',
    'StorageAuthenticationError',
    'StorageConflictError',
    'StorageInitializationError',
    'StorageNotFoundError',
    'StorageUnavailableError',
    'StorageValidationError',
    'StorageWorkbookAccessError',
    'TEST_RECEIPT_REFERENCE',
    'VERSION_5_WORKSHEET_HEADERS',
    'WORKSHEET_HEADERS',
    '_mutation_guidance',
    'account_balances',
    'annotations',
    'backup_receipt_manifest',
    'build_receipt_manifest',
    'csv',
    'decode_receipt_references',
    'drive_file_from_reference',
    'general_ledger_rows',
    'gspread',
    'hashlib',
    'io',
    'json',
    'patch',
    'pytest',
    'rewrite_backup_tables',
    'suggested_account_classification',
    'suggested_account_type',
    'zipfile',
]
