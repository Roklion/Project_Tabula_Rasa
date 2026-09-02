from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from decimal import Decimal
from unittest.mock import patch

import gspread
import pytest
from google.oauth2.service_account import Credentials

from tabula_rasa.mixed_use import (
    MixedUseAllocationError,
    calculate_allocated_amount,
    validate_mixed_use_allocation,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageBulkMutationUncertainError,
    StorageConflictError,
    StorageValidationError,
)
from tabula_rasa.storage.google_sheets import (
    BACKUP_FORMAT_VERSION,
    MIXED_USE_WORKSHEET_HEADERS,
    PRE_MIXED_USE_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
from tests.fakes import FakeWorkbook


def _expense_inputs(storage: GoogleSheetsStorage) -> dict[str, str]:
    account = next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == "Checking"
    )
    category = next(
        category
        for category in storage.list_categories()
        if category["name"] == "Office"
    )
    payee = storage.create_payee("Office vendor")
    return {
        "txn_date": "2026-09-01",
        "account_id": account["id"],
        "category_id": category["id"],
        "payee_id": payee["id"],
        "description": "Internet service",
        "reference": "INV-119",
    }


def test_allocation_uses_decimal_currency_rounding_and_five_places() -> None:
    assert calculate_allocated_amount("123.45", "33.33333") == Decimal("41.15")
    normalized = validate_mixed_use_allocation("123.45", "33.33333")
    assert normalized.total_expense == "123.45"
    assert normalized.business_use_percentage == "33.33333"
    assert normalized.allocated_amount == "41.15"


@pytest.mark.parametrize("percentage", ["0", "-1", "100.00001", "0.000001"])
def test_allocation_rejects_percentage_boundaries_and_precision(
    percentage: str,
) -> None:
    with pytest.raises(MixedUseAllocationError):
        validate_mixed_use_allocation("100", percentage)


def test_allocation_rejects_result_that_rounds_to_zero() -> None:
    with pytest.raises(MixedUseAllocationError, match=r"\$0.00"):
        validate_mixed_use_allocation("0.01", "0.00001")


def test_mixed_use_create_persists_one_allocated_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="125.00",
        business_use_percentage="40.00000",
        allocation_rationale="Dedicated office percentage",
    )

    transactions = default_storage.list_transactions()
    assert len(default_storage.list_mixed_use_expenses()) == 1
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "50.00"
    assert transactions[0]["source_type"] == "mixed_use_expense"
    assert transactions[0]["source_id"] == source["id"]
    assert transactions[0]["description"] == (
        "Internet service\nAllocation rationale: Dedicated office percentage"
    )
    assert source["linked_transaction_id"] == transactions[0]["id"]
    assert source["allocated_amount"] == "50.00"


def test_mixed_use_edit_updates_same_projection_and_detects_stale_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="25",
        allocation_rationale="Quarterly measured usage",
    )
    edited = default_storage.edit_mixed_use_expense(
        source["id"],
        expected_source=source,
        total_expense="200",
        business_use_percentage="12.5",
        reference="UPDATED-119",
        allocation_rationale="Updated quarterly measurement",
    )

    assert edited["id"] == source["id"]
    assert edited["linked_transaction_id"] == source["linked_transaction_id"]
    transaction = default_storage.list_transactions()[0]
    assert transaction["id"] == source["linked_transaction_id"]
    assert transaction["amount"] == "25.00"
    assert transaction["reference"] == "UPDATED-119"
    assert transaction["description"].endswith(
        "Allocation rationale: Updated quarterly measurement"
    )
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"], expected_source=source, total_expense="300"
        )


def test_mixed_use_delete_removes_source_and_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )

    default_storage.delete_mixed_use_expense(source["id"], expected_source=source)

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_backup_round_trip_includes_source_and_linkage(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
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
        **_expense_inputs(default_storage),
        total_expense="80",
        business_use_percentage="12.5",
        allocation_rationale="Home office calculation",
    )
    backup = default_storage.export_backup_zip(
        {"business_profile_key": "test", "receipts": [], "schema_version": 1}
    )
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as source, zipfile.ZipFile(
        output, "w"
    ) as destination:
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


def test_writable_initialization_upgrades_pre_mixed_workbook_idempotently() -> None:
    workbook = FakeWorkbook(PRE_MIXED_USE_WORKSHEET_HEADERS)
    google_client = type("GoogleClient", (), {"open_by_key": lambda self, _: workbook})()
    with (
        patch.object(Credentials, "from_service_account_info", return_value=object()),
        patch.object(gspread, "authorize", return_value=google_client),
    ):
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "test", "gcp_service_account": {"type": "service_account"}}
        )
        GoogleSheetsStorage.from_secrets(
            {"spreadsheet_id": "test", "gcp_service_account": {"type": "service_account"}}
        )

    assert "MixedUseExpenses" in workbook.sheets
    assert workbook.sheets["MixedUseExpenses"].rows == [list(MIXED_USE_WORKSHEET_HEADERS)]
    assert workbook.sheets["Transactions"].rows[0] == list(
        WORKSHEET_HEADERS["Transactions"]
    )
    assert workbook.sheets["Transactions"].col_count == len(
        WORKSHEET_HEADERS["Transactions"]
    )


def test_mixed_use_uncertain_create_never_retries_projection_blindly(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-retry-safe",
        "linked_transaction_id": "transaction-retry-safe",
    }
    original_append = default_storage._append
    calls = 0

    def append_then_lose_first_result(title: str, record: dict[str, str]) -> None:
        nonlocal calls
        original_append(title, record)
        calls += 1
        if calls == 1:
            raise StorageBulkMutationUncertainError(
                "uncertain", outcome="mixed_ambiguous", retryable=False
            )

    default_storage._append = append_then_lose_first_result  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError, match="review"):
        default_storage.create_mixed_use_expense(**inputs)

    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1
    assert default_storage._rows("Transactions", force_refresh=True) == []
    default_storage._append = original_append  # type: ignore[method-assign]
    retried = default_storage.create_mixed_use_expense(**inputs)
    assert retried["id"] == "source-retry-safe"
    assert len(default_storage.list_transactions()) == 1
