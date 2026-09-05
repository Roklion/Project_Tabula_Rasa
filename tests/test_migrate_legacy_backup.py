from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable
import zipfile

import pytest

from scripts.migrate_legacy_backup import (
    SOURCE_HEADERS,
    default_output_path,
    migrate_backup_file,
    migrate_legacy_backup,
)
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets import WORKSHEET_HEADERS
from tests.fakes import FakeWorkbook


def _csv_bytes(headers: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([[row.get(header, "") for header in headers] for row in rows])
    return buffer.getvalue().encode("utf-8")


def _downgrade(backup: bytes, version: int) -> bytes:
    schemas = SOURCE_HEADERS[version]
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        manifest = json.loads(source.read("manifest.json"))
        current = {
            title: list(csv.DictReader(io.StringIO(source.read(f"{title}.csv").decode())))
            for title in WORKSHEET_HEADERS
        }
        receipts = source.read("receipts.json")
    payee_names = {row["id"]: row["name"] for row in current["Payees"]}
    for row in current["Transactions"]:
        row["payee"] = payee_names.get(row.get("payee_id", ""), "")
    files = {}
    for title, headers in schemas.items():
        output_headers = headers
        if version == 5 and title in {"Accounts", "Categories"}:
            output_headers = (*headers, "parent_id")
        files[f"{title}.csv"] = _csv_bytes(output_headers, current[title])
    if version >= 5:
        files["receipts.json"] = receipts
    manifest.update(
        {
            "format_version": version,
            "row_counts": {
                name.removesuffix(".csv"): sum(
                    1 for _ in csv.DictReader(io.StringIO(content.decode()))
                )
                for name, content in files.items()
                if name.endswith(".csv")
            },
            "worksheet_headers": {
                title: list(
                    (*headers, "parent_id")
                    if version == 5 and title in {"Accounts", "Categories"}
                    else headers
                )
                for title, headers in schemas.items()
            },
            "sha256": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        }
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
        for name, content in files.items():
            destination.writestr(name, content)
        destination.writestr("manifest.json", json.dumps(manifest).encode())
    return output.getvalue()


def _rewrite_legacy(
    backup: bytes,
    *,
    update_manifest: Callable[[dict[str, bytes], dict[str, Any]], None],
) -> bytes:
    with zipfile.ZipFile(io.BytesIO(backup)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(files["manifest.json"])
    update_manifest(files, manifest)
    files["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    return output.getvalue()


def test_all_supported_legacy_versions_migrate_to_v10() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )

    for version in range(1, 10):
        converted = migrate_legacy_backup(_downgrade(current, version), profile_key="test")
        assert GoogleSheetsStorage.validate_backup_zip(converted)["format_version"] == 10


def test_v9_projection_tags_are_copied_to_mixed_use_source() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    tag = storage.create_tag("Project")
    source = storage.create_mixed_use_expense(
        txn_date="2026-09-01",
        account_id=account["id"],
        category_id=category["id"],
        total_expense="100.00",
        business_use_percentage="50",
        allocation_rationale="Workspace",
        tag_ids=[tag["id"]],
    )
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    converted = migrate_legacy_backup(_downgrade(current, 9), profile_key="test")
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.restore_backup_zip(converted)
    assert target.get_mixed_use_expense(source["id"])["tag_ids"] == [tag["id"]]


def test_v8_transaction_and_mileage_tags_are_preserved() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    tag = storage.create_tag("Project")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10.00",
        account_id=account["id"],
        category_id=category["id"],
        tag_ids=[tag["id"]],
    )
    mileage = storage.create_mileage_trip(
        trip_date="2026-09-02",
        miles="5.0",
        start_location="Office",
        destination="Client",
        business_purpose="Visit",
        tag_ids=[tag["id"]],
    )
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    converted = migrate_legacy_backup(_downgrade(current, 8), profile_key="test")
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.restore_backup_zip(converted)
    assert target.list_transactions()[0]["id"] == transaction["id"]
    assert target.list_transactions()[0]["tag_ids"] == [tag["id"]]
    assert target.list_mileage_trips()[0]["id"] == mileage["id"]
    assert target.list_mileage_trips()[0]["tag_ids"] == [tag["id"]]


def test_v6_payee_text_and_hierarchy_become_current_records() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    parent = storage.create_account("Operating", "Bank")
    account = storage.create_account("Petty cash", "Cash", parent_id=parent["id"])
    category = storage.create_category("Office", "Expense")
    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10.00",
        account_id=account["id"],
        category_id=category["id"],
        payee_id=storage.create_payee("Legacy vendor")["id"],
    )
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    converted = migrate_legacy_backup(_downgrade(current, 6), profile_key="test")
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    target.restore_backup_zip(converted)
    assert target.list_payees()[0]["name"] == "Legacy vendor"
    assert target.list_transactions()[0]["payee"] == "Legacy vendor"
    assert target.list_accounts(active_only=False)[1]["parent_id"] == parent["id"]


def test_v5_receipt_inventory_is_carried_into_v10() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10.00",
        account_id=account["id"],
        category_id=category["id"],
    )
    reference = {
        "id": "receipt123456",
        "name": "receipt.pdf",
        "receipt_id": "a" * 32,
        "original_filename": "receipt.pdf",
        "mime_type": "application/pdf",
        "byte_size": 7,
        "sha256": "b" * 64,
    }
    storage.link_transaction_receipt(transaction["id"], reference=reference)
    drive_file = {
        "id": reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "test",
            "tabulaRasaReceiptId": reference["receipt_id"],
            "tabulaRasaSha256": reference["sha256"],
            "tabulaRasaOriginalName": reference["original_filename"],
        },
    }
    current = storage.export_backup_zip(
        build_receipt_manifest("test", storage.list_transactions(), [drive_file])
    )
    converted = migrate_legacy_backup(_downgrade(current, 5), profile_key="test")
    manifest = GoogleSheetsStorage.validate_backup_zip(converted)
    assert manifest["receipt_count"] == 1


def test_v4_receipt_references_are_unlinked_without_inventory() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10.00",
        account_id=account["id"],
        category_id=category["id"],
    )
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    legacy = _downgrade(current, 4)
    with zipfile.ZipFile(io.BytesIO(legacy)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    rows = list(csv.reader(io.StringIO(files["Transactions.csv"].decode())))
    rows[1][rows[0].index("receipt_references")] = json.dumps(
        [{"id": "oldreceipt12345", "name": "legacy-receipt.pdf"}]
    )
    files["Transactions.csv"] = _csv_bytes(
        tuple(rows[0]), [dict(zip(rows[0], row)) for row in rows[1:]]
    )
    manifest = json.loads(files["manifest.json"])
    manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
        files["Transactions.csv"]
    ).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    source_archive = io.BytesIO()
    with zipfile.ZipFile(source_archive, "w") as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    legacy = source_archive.getvalue()

    source_copy = legacy
    converted = migrate_legacy_backup(legacy, profile_key="test")
    GoogleSheetsStorage.validate_backup_zip(converted)
    with zipfile.ZipFile(io.BytesIO(converted)) as archive:
        converted_rows = list(
            csv.DictReader(io.StringIO(archive.read("Transactions.csv").decode()))
        )
    assert converted_rows[0]["receipt_references"] == ""
    assert legacy == source_copy


def test_application_rejects_legacy_archive_before_restore_writes() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    legacy = _downgrade(current, 5)
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    with pytest.raises(StorageValidationError, match="migrate_legacy_backup"):
        target.restore_backup_zip(legacy)
    assert target.list_accounts(active_only=False) == []


def test_v1_account_normalization_and_source_checksum_are_preserved() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Equipment loan", "Other")
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    legacy = _downgrade(current, 1)
    with zipfile.ZipFile(io.BytesIO(legacy)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    account_rows = list(csv.reader(io.StringIO(files["Accounts.csv"].decode())))
    account_rows[1][account_rows[0].index("type")] = "Loan"
    files["Accounts.csv"] = _csv_bytes(
        tuple(account_rows[0]),
        [dict(zip(account_rows[0], row)) for row in account_rows[1:]],
    )
    source_manifest = json.loads(files["manifest.json"])
    source_manifest["sha256"]["Accounts.csv"] = hashlib.sha256(
        files["Accounts.csv"]
    ).hexdigest()
    files["manifest.json"] = json.dumps(source_manifest).encode()
    legacy_output = io.BytesIO()
    with zipfile.ZipFile(legacy_output, "w") as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    legacy = legacy_output.getvalue()
    converted = migrate_legacy_backup(legacy, profile_key="test")
    with zipfile.ZipFile(io.BytesIO(converted)) as archive:
        accounts = list(csv.DictReader(io.StringIO(archive.read("Accounts.csv").decode())))
        manifest = json.loads(archive.read("manifest.json"))
    assert accounts[0]["id"] == account["id"]
    assert accounts[0]["type"] == "Short-term debt"
    assert accounts[0]["classification"] == "Liability"
    assert manifest["conversion"]["source_archive_sha256"] == hashlib.sha256(legacy).hexdigest()


def test_migration_rejects_tampered_csv_and_never_overwrites_source() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    current = storage.export_backup_zip(
        {"schema_version": 1, "business_profile_key": "test", "receipts": []}
    )
    legacy = _downgrade(current, 1)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(legacy)) as source, zipfile.ZipFile(output, "w") as destination:
        for name in source.namelist():
            content = source.read(name)
            if name == "Accounts.csv":
                content += b"tampered,row\n"
            destination.writestr(name, content)
    with pytest.raises(StorageValidationError, match="checksum"):
        migrate_legacy_backup(output.getvalue())
    with TemporaryDirectory() as directory:
        source_path = Path(directory) / "backup.zip"
        source_path.write_bytes(legacy)
        destination = default_output_path(source_path)
        destination.write_bytes(b"existing")
        with pytest.raises(FileExistsError):
            migrate_backup_file(source_path)
        assert source_path.read_bytes() == legacy
        assert destination.read_bytes() == b"existing"


def test_migration_rejects_overwide_legacy_rows() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10.00",
        account_id=account["id"],
        category_id=category["id"],
    )
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        1,
    )

    def add_extra_column(files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        rows = list(csv.reader(io.StringIO(files["Transactions.csv"].decode())))
        rows[1].append("unexpected")
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerows(rows)
        files["Transactions.csv"] = buffer.getvalue().encode()
        manifest["sha256"]["Transactions.csv"] = hashlib.sha256(
            files["Transactions.csv"]
        ).hexdigest()

    legacy = _rewrite_legacy(legacy, update_manifest=add_extra_column)
    with pytest.raises(StorageValidationError, match="over-wide"):
        migrate_legacy_backup(legacy)


@pytest.mark.parametrize("field", ["sha256", "row_counts"])
def test_migration_rejects_null_validation_metadata(field: str) -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        1,
    )

    def null_metadata(_files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        manifest[field] = None

    legacy = _rewrite_legacy(legacy, update_manifest=null_metadata)
    with pytest.raises(StorageValidationError, match="validation metadata"):
        migrate_legacy_backup(legacy)


def test_migration_requires_the_complete_source_checksum_set() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        1,
    )

    def remove_checksum(_files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        manifest["sha256"].pop("Accounts.csv")

    legacy = _rewrite_legacy(legacy, update_manifest=remove_checksum)
    with pytest.raises(StorageValidationError, match="checksum entries"):
        migrate_legacy_backup(legacy)


def test_migration_validates_optional_payee_checksum() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        6,
    )

    def add_tampered_payees(files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        files["Payees.csv"] = _csv_bytes(
            ("id", "name", "active", "created_at"),
            [{"id": "payee-1", "name": "Vendor", "active": "TRUE"}],
        )
        manifest["sha256"]["Payees.csv"] = hashlib.sha256(
            files["Payees.csv"]
        ).hexdigest()
        files["Payees.csv"] += b"tampered"

    legacy = _rewrite_legacy(legacy, update_manifest=add_tampered_payees)
    with pytest.raises(StorageValidationError, match="Payees backup checksum"):
        migrate_legacy_backup(legacy)


def test_migration_validates_legacy_receipt_checksum() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        5,
    )

    def tamper_receipts(files: dict[str, bytes], _manifest: dict[str, Any]) -> None:
        files["receipts.json"] += b"tampered"

    legacy = _rewrite_legacy(legacy, update_manifest=tamper_receipts)
    with pytest.raises(StorageValidationError, match="receipts.json backup checksum"):
        migrate_legacy_backup(legacy)


def test_migration_accepts_reordered_legacy_headers() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    legacy = _downgrade(
        storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        ),
        1,
    )

    def reorder_accounts(files: dict[str, bytes], manifest: dict[str, Any]) -> None:
        rows = list(csv.DictReader(io.StringIO(files["Accounts.csv"].decode())))
        headers = tuple(reversed(tuple(rows[0]))) if rows else ()
        files["Accounts.csv"] = _csv_bytes(headers, rows)
        manifest["sha256"]["Accounts.csv"] = hashlib.sha256(
            files["Accounts.csv"]
        ).hexdigest()

    legacy = _rewrite_legacy(legacy, update_manifest=reorder_accounts)
    assert GoogleSheetsStorage.validate_backup_zip(migrate_legacy_backup(legacy))[
        "format_version"
    ] == 10
