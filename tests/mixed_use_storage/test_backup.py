from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile

import pytest

from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets import BACKUP_FORMAT_VERSION
from tests.fakes import FakeWorkbook
from tests.mixed_use_storage._support import expense_inputs


def test_mixed_use_backup_round_trip_includes_source_and_linkage(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="80",
        business_use_percentage="12.5",
        allocation_rationale="Home office calculation",
    )
    backup = default_storage.export_backup_zip(
        {"business_profile_key": "test", "receipts": [], "schema_version": 1}
    )
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        assert "MixedUseExpenses.csv" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == BACKUP_FORMAT_VERSION
        assert manifest["row_counts"]["MixedUseExpenses"] == 1

    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.restore_backup_zip(backup)
    restored = target.get_mixed_use_expense(source["id"])
    assert restored["linked_transaction_id"] == source["linked_transaction_id"]
    assert target.list_transactions()[0]["source_id"] == source["id"]


def test_current_backup_rejects_orphaned_mixed_use_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="80",
        business_use_percentage="12.5",
        allocation_rationale="Home office calculation",
    )
    backup = default_storage.export_backup_zip(
        {"business_profile_key": "test", "receipts": [], "schema_version": 1}
    )
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(backup)) as source,
        zipfile.ZipFile(output, "w") as destination,
    ):
        contents = {name: source.read(name) for name in source.namelist()}
        rows = list(csv.reader(io.StringIO(contents["Transactions.csv"].decode())))
        rows[1][rows[0].index("source_id")] = "missing-source"
        csv_buffer = io.StringIO(newline="")
        csv.writer(csv_buffer, lineterminator="\n").writerows(rows)
        contents["Transactions.csv"] = csv_buffer.getvalue().encode()
        manifest = json.loads(contents["manifest.json"])
        manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
            contents["Transactions.csv"]
        ).hexdigest()
        contents["manifest.json"] = json.dumps(manifest).encode()
        for name, content in contents.items():
            destination.writestr(name, content)

    with pytest.raises(StorageValidationError, match="unknown source"):
        GoogleSheetsStorage.validate_backup_zip(output.getvalue())
