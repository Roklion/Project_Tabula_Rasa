from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
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
    StorageUnavailableError,
    StorageValidationError,
)
from tabula_rasa.storage import google_sheets as google_sheets_module
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


def test_allocation_accepts_trailing_zero_percentage_precision() -> None:
    normalized = validate_mixed_use_allocation("100", "12.340000")

    assert normalized.business_use_percentage == "12.34"
    assert normalized.allocated_amount == "12.34"


def test_allocation_preserves_precision_before_currency_rounding() -> None:
    assert calculate_allocated_amount(
        "3165809505055861412909.65", "35.52850"
    ) == Decimal("1124764630003771722085.61")


@pytest.mark.parametrize("percentage", ["0", "-1", "100.00001", "0.000001"])
def test_allocation_rejects_percentage_boundaries_and_precision(
    percentage: str,
) -> None:
    with pytest.raises(MixedUseAllocationError):
        validate_mixed_use_allocation("100", percentage)


@pytest.mark.parametrize(
    "percentage",
    [
        "1e1000000000",
        "99.9999999999999999999999999999",
        "100.00000000000000000000000000001",
    ],
)
def test_allocation_rejects_large_or_overprecise_percentages(
    percentage: str,
) -> None:
    with pytest.raises(MixedUseAllocationError):
        validate_mixed_use_allocation("100", percentage)


def test_allocation_rejects_result_that_rounds_to_zero() -> None:
    with pytest.raises(MixedUseAllocationError, match=r"\$0.00"):
        validate_mixed_use_allocation("0.01", "0.00001")


def test_allocation_rejects_values_that_exceed_decimal_context() -> None:
    with pytest.raises(MixedUseAllocationError, match="too large"):
        validate_mixed_use_allocation("1e28", "50")


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
    assert "payee" not in default_storage._rows(
        "MixedUseExpenses", force_refresh=True
    )[0].values


def test_transaction_edit_canonicalizes_padded_id(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **_expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )

    edited = default_storage.edit_transaction(
        f"  {transaction['id']}  ", description="Updated"
    )

    assert edited["id"] == transaction["id"]
    assert edited["description"] == "Updated"


def test_mixed_use_edit_updates_same_projection_and_detects_stale_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="25",
        allocation_rationale="Quarterly measured usage",
    )
    original_projection_created_at = default_storage.list_transactions()[0][
        "created_at"
    ]
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
    assert transaction["created_at"] == original_projection_created_at
    assert transaction["description"].endswith(
        "Allocation rationale: Updated quarterly measurement"
    )
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"], expected_source=source, total_expense="300"
        )


def test_category_kind_change_rejects_mixed_use_references(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )

    with pytest.raises(StorageConflictError, match="mixed-use expense"):
        default_storage.edit_category(
            f" {source['category_id']} ", kind="Income"
        )

    category = next(
        item
        for item in default_storage.list_categories()
        if item["id"] == source["category_id"]
    )
    assert category["kind"] == "Expense"


def test_category_edit_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    category = next(
        item for item in default_storage.list_categories() if item["name"] == "Office"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_category() -> None:
        started.set()
        try:
            default_storage.edit_category(category["id"], name="Office updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_category)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_mixed_use_edit_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_mixed_use() -> None:
        started.set()
        try:
            default_storage.edit_mixed_use_expense(
                source["id"], allocation_rationale="Updated use"
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_mixed_use)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_mixed_use_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_mixed_use() -> None:
        started.set()
        try:
            default_storage.delete_mixed_use_expense(source["id"])
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_mixed_use)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_category_delete_shares_mixed_use_creation_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    category = default_storage.create_category("Unused category", "Expense")
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def delete_category() -> None:
        started.set()
        try:
            default_storage.delete_category(category["id"])
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=delete_category)
    with google_sheets_module._MIXED_USE_CREATE_LOCK:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_category_delete_rejects_orphaned_mixed_use_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_sheet.rows.pop(1)
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageConflictError, match="mixed-use expenses"):
        default_storage.delete_category(source["category_id"])


def test_generic_transaction_mutations_reject_mixed_use_projections(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    projection = default_storage.list_transactions()[0]
    replacement = next(
        category
        for category in default_storage.list_categories()
        if category["kind"] == "Expense"
        and category["id"] != projection["category_id"]
    )

    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.edit_transaction(projection["id"], description="Changed")
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.delete_transaction(projection["id"])
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.bulk_change_transaction_category(
            [projection["id"]],
            expected_transactions=[projection],
            category_id=replacement["id"],
        )
    with pytest.raises(StorageValidationError, match="mixed-use expense APIs"):
        default_storage.bulk_delete_transactions(
            [projection["id"]], expected_transactions=[projection]
        )

    assert default_storage.get_mixed_use_expense(source["id"])["linked_transaction_id"] == projection[
        "id"
    ]


def test_mixed_use_projection_rejects_destination_account(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    destination = next(
        account
        for account in default_storage.list_accounts(active_only=False)
        if account["id"] != source["account_id"]
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("to_account_id")] = destination["id"]
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="destination account"):
        default_storage.list_mixed_use_expenses()


def test_generic_transaction_mutations_reject_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    default_storage._invalidate("Transactions")
    transaction = dict(default_storage._rows("Transactions", force_refresh=True)[0].values)

    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.delete_transaction(transaction["id"])
    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.bulk_delete_transactions(
            [transaction["id"]], expected_transactions=[transaction]
        )

    sources = default_storage._rows("MixedUseExpenses", force_refresh=True)
    assert sources[0].values["id"] == source["id"]
    assert sources[0].values["linked_transaction_id"] == transaction["id"]


def test_receipt_mutations_reject_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    transaction = default_storage.list_transactions()[0]
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    transaction_sheet.rows[1][headers.index("receipt_references")] = (
        '[{"id":"oldreceipt01","name":"Receipt"}]'
    )
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.set_transaction_receipt_references(
            transaction["id"], []
        )
    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.unlink_transaction_receipt(
            transaction["id"], file_id="oldreceipt01"
        )

    sources = default_storage._rows("MixedUseExpenses", force_refresh=True)
    assert sources[0].values["id"] == source["id"]


def test_receipt_recovery_rejects_half_populated_provenance(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    expected_transaction = default_storage.list_transactions()[0]
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    default_storage._invalidate("Transactions")

    with pytest.raises(
        StorageValidationError, match="incomplete transaction provenance"
    ):
        default_storage.apply_receipt_recovery_plan(
            [expected_transaction], {expected_transaction["id"]: []}
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


def test_sheet_id_validation_is_consistent_for_mixed_use_worksheets(
    default_storage: GoogleSheetsStorage,
) -> None:
    worksheet = default_storage._worksheet("MixedUseExpenses")
    worksheet.id = "not-an-integer"

    with pytest.raises(StorageValidationError, match="invalid sheet ID"):
        default_storage._sheet_id("MixedUseExpenses")


def test_replace_rows_rebuilds_ranges_after_rows_shift_during_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Retry target", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def insert_row_then_fail(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-before-retry"
            raise OSError("temporary failure")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = insert_row_then_fail  # type: ignore[method-assign]
    replacement = {**row.values, "name": "Retry target updated"}

    default_storage._replace_rows("Accounts", [(row, replacement)])

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Retry target updated"
    assert rows[0].values["id"] == "inserted-before-retry"


def test_replace_rows_reports_conflict_when_row_changes_during_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Retry conflict", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update

    def change_then_timeout(data: list[dict[str, object]], **kwargs: object) -> None:
        del data, kwargs
        worksheet.rows[row.row_number - 1][worksheet.rows[0].index("name")] = (
            "Changed elsewhere"
        )
        raise OSError("temporary response lost")

    worksheet.batch_update = change_then_timeout  # type: ignore[method-assign]

    with pytest.raises(StorageConflictError, match="changed unexpectedly"):
        default_storage._replace_rows(
            "Accounts", [(row, {**row.values, "name": "Retry conflict updated"})]
        )

    worksheet.batch_update = original_batch_update  # type: ignore[method-assign]


def test_replace_rows_refreshes_positions_after_retry_backoff(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Backoff refresh", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def shift_then_timeout(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-during-backoff"
            raise OSError("temporary response lost")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = shift_then_timeout  # type: ignore[method-assign]
    default_storage._replace_rows(
        "Accounts", [(row, {**row.values, "name": "Backoff refresh updated"})]
    )

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Backoff refresh updated"
    assert rows[0].values["id"] == "inserted-during-backoff"


def test_replace_rows_refreshes_positions_after_retry_guard(
    default_storage: GoogleSheetsStorage,
) -> None:
    account = default_storage.create_account("Guard refresh", "Bank")
    row = default_storage._find_row("Accounts", account["id"])
    worksheet = default_storage._worksheet("Accounts")
    original_batch_update = worksheet.batch_update
    calls = 0

    def shift_during_guard() -> None:
        worksheet.rows.insert(1, list(worksheet.rows[1]))
        worksheet.rows[1][0] = "inserted-during-guard"

    def fail_then_retry(data: list[dict[str, object]], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary response lost")
        original_batch_update(data, **kwargs)

    worksheet.batch_update = fail_then_retry  # type: ignore[method-assign]
    default_storage._replace_rows(
        "Accounts",
        [(row, {**row.values, "name": "Guard refresh updated"})],
        before_retry=shift_during_guard,
    )

    rows = default_storage._rows("Accounts", force_refresh=True)
    assert next(item for item in rows if item.values["id"] == account["id"]).values[
        "name"
    ] == "Guard refresh updated"
    assert rows[0].values["id"] == "inserted-during-guard"


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
    original_created_at = default_storage._rows(
        "MixedUseExpenses", force_refresh=True
    )[0].values["created_at"]
    default_storage._append = original_append  # type: ignore[method-assign]
    retried = default_storage.create_mixed_use_expense(**inputs)
    assert retried["id"] == "source-retry-safe"
    assert retried["created_at"] == original_created_at
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_source_only_retry_classifies_missing_projection_as_retryable(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-source-only-retry",
        "linked_transaction_id": "transaction-source-only-retry",
    }
    original_append = default_storage._append
    calls = 0

    def fail_projection_on_both_attempts(title: str, record: dict[str, str]) -> None:
        nonlocal calls
        calls += 1
        if title == "Transactions":
            raise StorageUnavailableError("projection unavailable", retryable=True)
        original_append(title, record)

    default_storage._append = fail_projection_on_both_attempts  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError) as error:
        default_storage.create_mixed_use_expense(**inputs)
    assert error.value.outcome == "mixed_ambiguous"

    with pytest.raises(StorageBulkMutationUncertainError) as retry_error:
        default_storage.create_mixed_use_expense(**inputs)
    assert retry_error.value.outcome == "not_applied"
    assert retry_error.value.retryable is True
    assert calls == 3


def test_mixed_use_create_verifies_uncertain_source_payload_before_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-payload-conflict",
        "linked_transaction_id": "transaction-payload-conflict",
    }
    original_append = default_storage._append

    def append_conflicting_source(title: str, record: dict[str, str]) -> None:
        if title == "MixedUseExpenses":
            conflicting = {**record, "allocation_rationale": "Other use"}
            original_append(title, conflicting)
            return
        original_append(title, record)

    default_storage._append = append_conflicting_source  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="different data"):
        default_storage.create_mixed_use_expense(**inputs)

    assert default_storage._rows("Transactions", force_refresh=True) == []


def test_mixed_use_create_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-final-write",
        "linked_transaction_id": "transaction-final-write",
    }
    original_append = default_storage._append
    calls = 0

    def append_then_lose_final_result(title: str, record: dict[str, str]) -> None:
        nonlocal calls
        original_append(title, record)
        calls += 1
        if calls == 2:
            raise StorageUnavailableError("response lost")

    default_storage._append = append_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.create_mixed_use_expense(**inputs)

    assert result["id"] == inputs["source_id"]
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_retry_reuses_projection_timestamp_after_postcondition_failure(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **_expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-postcondition-retry",
        "linked_transaction_id": "transaction-postcondition-retry",
    }
    original_snapshot = default_storage._raw_mixed_use_snapshot
    calls = 0

    def fail_after_written_pair() -> tuple[
        dict[str, dict[str, str]], dict[str, dict[str, str]]
    ]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise StorageUnavailableError("postcondition unavailable")
        return original_snapshot()

    default_storage._raw_mixed_use_snapshot = fail_after_written_pair  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError, match="postcondition"):
        default_storage.create_mixed_use_expense(**inputs)
    default_storage._raw_mixed_use_snapshot = original_snapshot  # type: ignore[method-assign]
    persisted_projection_created_at = default_storage._rows(
        "Transactions", force_refresh=True
    )[0].values["created_at"]

    with patch(
        "tabula_rasa.storage.google_sheets._utc_now",
        return_value="2099-01-01T00:00:00Z",
    ):
        retried = default_storage.create_mixed_use_expense(**inputs)

    assert retried["id"] == inputs["source_id"]
    assert (
        default_storage.list_transactions()[0]["created_at"]
        == persisted_projection_created_at
    )


def test_mixed_use_edit_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_replace = default_storage._replace_rows
    calls = 0

    def replace_then_lose_final_result(title: str, updates: object) -> None:
        nonlocal calls
        original_replace(title, updates)  # type: ignore[arg-type]
        calls += 1
        if calls == 2:
            raise StorageUnavailableError("response lost")

    default_storage._replace_rows = replace_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="200",
        business_use_percentage="25",
        allocation_rationale="Updated use",
    )

    assert result["allocated_amount"] == "50.00"


def test_mixed_use_edit_rejects_receipt_drift_before_replacing_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 0:
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            reference = '[{"id":"oldreceipt01","name":"Receipt"}]'
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"], allocation_rationale="Updated use"
        )


def test_mixed_use_receipt_update_rejects_pair_drift_before_writing(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_concurrent_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 1:
            reference = '[{"id":"concurrent-receipt","name":"Receipt"}]'
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
            default_storage._invalidate("Transactions")
            default_storage._invalidate("MixedUseExpenses")
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_concurrent_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="receipt references changed"):
        default_storage.set_transaction_receipt_references(
            source["linked_transaction_id"], []
        )


def test_mixed_use_receipt_update_refreshes_row_position_before_writing(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_transaction_row_shift(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 1:
            worksheet = default_storage._worksheet("Transactions")
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "unrelated-transaction"
            default_storage._invalidate("Transactions")
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_transaction_row_shift  # type: ignore[method-assign]
    updated = default_storage.set_transaction_receipt_references(
        source["linked_transaction_id"], []
    )

    assert updated["id"] == source["linked_transaction_id"]
    rows = default_storage._rows("Transactions", force_refresh=True)
    assert [
        (item.row_number, item.values["id"], item.values["receipt_references"])
        for item in rows
    ] == [(2, "unrelated-transaction", "[]"), (3, source["linked_transaction_id"], "[]")]
    assert rows[0].values["id"] == "unrelated-transaction"
    assert rows[0].values["receipt_references"] == "[]"
    assert rows[1].values["id"] == source["linked_transaction_id"]
    assert rows[1].values["receipt_references"] == "[]"


def test_receipt_recovery_restarts_after_mixed_use_pair_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction = default_storage.list_transactions()[0]
    original_rows = default_storage._rows
    calls = 0

    def rows_after_concurrent_receipt_update(
        title: str, *, force_refresh: bool = False
    ) -> list[object]:
        nonlocal calls
        if title == "MixedUseExpenses":
            reference = '[{"id":"recovery-concurrent","name":"Receipt"}]'
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
            default_storage._invalidate("Transactions")
            default_storage._invalidate("MixedUseExpenses")
        calls += 1
        return original_rows(title, force_refresh=force_refresh)

    default_storage._rows = rows_after_concurrent_receipt_update  # type: ignore[method-assign]
    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        [transaction], {transaction["id"]: []}
    )

    assert applied is False
    assert fresh_transactions[0]["id"] == transaction["id"]
    assert fresh_transactions[0]["receipt_references"] == (
        '[{"id":"recovery-concurrent","name":"Receipt"}]'
    )
    assert calls == 3


def test_receipt_recovery_restarts_after_mixed_use_provenance_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    expected_transactions = default_storage.list_transactions()
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    transaction_sheet.rows[1][headers.index("source_id")] = ""
    default_storage._invalidate("Transactions")

    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {source["linked_transaction_id"]: []},
    )

    assert applied is False
    assert fresh_transactions[0]["source_type"] == ""
    assert fresh_transactions[0]["source_id"] == ""


def test_receipt_recovery_rejects_unrelated_receipt_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    unrelated = default_storage.create_transaction(
        **_expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )
    expected_transactions = default_storage.list_transactions()
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    unrelated_row = next(
        row
        for row in transaction_sheet.rows[1:]
        if row[headers.index("id")] == unrelated["id"]
    )
    unrelated_row[headers.index("receipt_references")] = (
        '[{"id":"unrelatedreceipt","name":"Receipt"}]'
    )
    default_storage._invalidate("Transactions")

    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {
            source["linked_transaction_id"]: [
                {"id": "recoveredreceipt", "name": "Receipt"}
            ]
        },
    )

    assert applied is False
    assert next(
        item for item in fresh_transactions if item["id"] == unrelated["id"]
    )["receipt_references"] == '[{"id":"unrelatedreceipt","name":"Receipt"}]'
    assert next(
        item
        for item in fresh_transactions
        if item["id"] == source["linked_transaction_id"]
    )["receipt_references"] == "[]"


def test_mixed_use_delete_rejects_pair_drift_before_deleting_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_find = default_storage._find_row
    calls = 0

    def find_after_receipt_update(title: str, record_id: str) -> object:
        nonlocal calls
        if calls == 0:
            transaction_sheet = default_storage._worksheet("Transactions")
            source_sheet = default_storage._worksheet("MixedUseExpenses")
            transaction_headers = default_storage._headers("Transactions")
            source_headers = default_storage._headers("MixedUseExpenses")
            reference = '[{"id":"oldreceipt01","name":"Receipt"}]'
            transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1


def test_mixed_use_delete_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_delete = default_storage._delete_mixed_use_row
    calls = 0

    def delete_then_lose_final_result(
        title: str,
        record_id: str,
        *,
        expected_record: object = None,
    ) -> None:
        nonlocal calls
        original_delete(title, record_id, expected_record=expected_record)  # type: ignore[arg-type]
        calls += 1
        if calls == 2:
            raise StorageUnavailableError("response lost")

    default_storage._delete_mixed_use_row = delete_then_lose_final_result  # type: ignore[method-assign]
    default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_uncertain_edit_classifies_partial_pair_safely(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_replace = default_storage._replace_rows
    calls = 0

    def replace_then_lose_first_result(title: str, updates: object) -> None:
        nonlocal calls
        original_replace(title, updates)  # type: ignore[arg-type]
        calls += 1
        if calls == 1:
            raise StorageUnavailableError("uncertain", retryable=False)

    default_storage._replace_rows = replace_then_lose_first_result  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError, match="ambiguous"):
        default_storage.edit_mixed_use_expense(
            source["id"],
            total_expense="200",
            business_use_percentage="25",
            allocation_rationale="Updated use",
        )


def test_mixed_use_edit_classifies_unchanged_pair_as_retryable_not_applied(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )

    def fail_before_replace(_title: str, _updates: object) -> None:
        raise StorageUnavailableError("temporary", retryable=True)

    default_storage._replace_rows = fail_before_replace  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError) as error:
        default_storage.edit_mixed_use_expense(
            source["id"], allocation_rationale="Updated use"
        )

    assert error.value.outcome == "not_applied"
    assert error.value.retryable is True


def test_mixed_use_receipt_update_classifies_partial_pair_as_ambiguous(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    old_references = '[{"id":"old-receipt","name":"Receipt"}]'
    transaction_sheet = default_storage._worksheet("Transactions")
    source_sheet = default_storage._worksheet("MixedUseExpenses")
    transaction_headers = default_storage._headers("Transactions")
    source_headers = default_storage._headers("MixedUseExpenses")
    transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = (
        old_references
    )
    source_sheet.rows[1][source_headers.index("receipt_references")] = old_references
    default_storage._invalidate("Transactions")
    default_storage._invalidate("MixedUseExpenses")

    def apply_transaction_only(_requests: object) -> None:
        transaction_sheet.rows[1][transaction_headers.index("receipt_references")] = "[]"
        default_storage._invalidate("Transactions")
        raise StorageUnavailableError("response lost", retryable=True)

    default_storage._batch_update_spreadsheet = apply_transaction_only  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError) as error:
        default_storage.set_transaction_receipt_references(
            source["linked_transaction_id"], []
        )

    assert error.value.outcome == "mixed_ambiguous"
    assert error.value.retryable is False


def test_mixed_use_uncertain_delete_rejects_partial_pair_as_ambiguous(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_delete = default_storage._delete_mixed_use_row

    def delete_then_lose_transaction_result(
        title: str,
        record_id: str,
        *,
        expected_record: object = None,
    ) -> None:
        original_delete(title, record_id, expected_record=expected_record)  # type: ignore[arg-type]
        if title == "Transactions":
            raise StorageUnavailableError("uncertain", retryable=False)

    default_storage._delete_mixed_use_row = delete_then_lose_transaction_result  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError, match="ambiguous"):
        default_storage.delete_mixed_use_expense(source["id"])


def test_mixed_use_delete_repairs_source_only_partial_pair(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_delete = default_storage._delete_mixed_use_row

    def delete_then_lose_transaction_result(
        title: str,
        record_id: str,
        *,
        expected_record: object = None,
    ) -> None:
        original_delete(title, record_id, expected_record=expected_record)  # type: ignore[arg-type]
        if title == "Transactions":
            raise StorageUnavailableError("uncertain", retryable=False)

    default_storage._delete_mixed_use_row = delete_then_lose_transaction_result  # type: ignore[method-assign]
    with pytest.raises(StorageBulkMutationUncertainError, match="ambiguous"):
        default_storage.delete_mixed_use_expense(source["id"])

    default_storage._delete_mixed_use_row = original_delete  # type: ignore[method-assign]
    default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_delete_rechecks_projection_before_source_only_repair(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction = default_storage.list_transactions()[0]
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_headers = default_storage._headers("Transactions")
    transaction_sheet.rows.pop(1)
    default_storage._invalidate("Transactions")
    original_rows = default_storage._rows
    injected = False

    def restore_projection_before_repair(
        title: str, *, force_refresh: bool = False
    ) -> list[object]:
        nonlocal injected
        if title == "Transactions" and force_refresh and not injected:
            injected = True
            transaction_sheet.append_row(
                [transaction.get(header, "") for header in transaction_headers]
            )
        return original_rows(title, force_refresh=force_refresh)

    default_storage._rows = restore_projection_before_repair  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == [source]
    assert default_storage.list_transactions() == [transaction]


def test_mixed_use_delete_rechecks_projection_before_source_delete(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction = default_storage.list_transactions()[0]
    original_delete = default_storage._delete_mixed_use_row
    injected = False

    def delete_then_restore_projection(
        title: str,
        record_id: str,
        *,
        expected_record: object = None,
    ) -> None:
        nonlocal injected
        original_delete(title, record_id, expected_record=expected_record)  # type: ignore[arg-type]
        if title == "Transactions" and not injected:
            injected = True
            transaction_sheet = default_storage._worksheet("Transactions")
            headers = default_storage._headers("Transactions")
            transaction_sheet.append_row(
                [transaction.get(header, "") for header in headers]
            )
            default_storage._invalidate("Transactions")

    default_storage._delete_mixed_use_row = delete_then_restore_projection  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == [source]
    assert default_storage.list_transactions() == [transaction]


def test_mixed_use_delete_revalidates_records_inside_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **_expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction = default_storage._find_row(
        "Transactions", source["linked_transaction_id"]
    ).values
    worksheet = default_storage._worksheet("Transactions")
    original_delete = worksheet.delete_rows
    calls = 0

    def edit_then_fail(row_number: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            description_column = default_storage._headers("Transactions").index(
                "description"
            )
            worksheet.rows[row_number - 1][description_column] = "changed"
            raise OSError("temporary failure")
        original_delete(row_number)

    worksheet.delete_rows = edit_then_fail  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="record changed"):
        default_storage._delete_mixed_use_row(
            "Transactions",
            source["linked_transaction_id"],
            expected_record=transaction,
        )

    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1
