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
