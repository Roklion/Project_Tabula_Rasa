from __future__ import annotations

from unittest.mock import Mock

import pytest

from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
)
from tests.mixed_use_storage._support import expense_inputs


def test_mixed_use_delete_removes_source_and_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )

    default_storage.delete_mixed_use_expense(source["id"], expected_source=source)

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_delete_rejects_stale_source_baseline(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    updated = default_storage.edit_mixed_use_expense(
        source["id"],
        expected_source=source,
        allocation_rationale="Updated business use",
    )

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"], expected_source=source)

    assert default_storage.get_mixed_use_expense(source["id"]) == updated
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_source_baseline_includes_projection_tags(
    default_storage: GoogleSheetsStorage,
) -> None:
    first_tag = default_storage.create_tag("Original tag")
    second_tag = default_storage.create_tag("Concurrent tag")
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
        tag_ids=[first_tag["id"]],
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("tag_ids")] = f'["{second_tag["id"]}"]'
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="tags do not match"):
        default_storage.list_mixed_use_expenses()

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_mixed_use_expense(
            source["id"],
            expected_source=source,
            allocation_rationale="Updated business use",
        )

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"], expected_source=source)


def test_sheet_id_validation_is_consistent_for_mixed_use_worksheets(
    default_storage: GoogleSheetsStorage,
) -> None:
    worksheet = default_storage._worksheet("MixedUseExpenses")
    worksheet.id = "not-an-integer"

    with pytest.raises(StorageValidationError, match="invalid sheet ID"):
        default_storage._sheet_id("MixedUseExpenses")


def test_mixed_use_retry_ignores_its_persisted_receipt_owner(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-receipt-retry",
        "linked_transaction_id": "transaction-receipt-retry",
        "receipt_references": [{"id": "retryreceipt01", "name": "Receipt.pdf"}],
    }

    created = default_storage.create_mixed_use_expense(**inputs)
    retried = default_storage.create_mixed_use_expense(**inputs)

    assert retried["id"] == created["id"]
    assert retried["linked_transaction_id"] == created["linked_transaction_id"]
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1
    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1


def test_mixed_use_create_retry_reuses_pair_after_account_deactivation(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-deactivated-retry",
        "linked_transaction_id": "transaction-deactivated-retry",
    }
    created = default_storage.create_mixed_use_expense(**inputs)
    default_storage.deactivate_account(inputs["account_id"])
    default_storage.edit_payee(inputs["payee_id"], active=False)

    retry_inputs = {
        key: value for key, value in inputs.items() if key != "linked_transaction_id"
    }
    retried = default_storage.create_mixed_use_expense(**retry_inputs)

    assert retried == created


def test_mixed_use_create_verifies_uncertain_source_payload_before_projection(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
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


def test_mixed_use_create_failure_invalidates_both_pair_caches(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-cache-invalidation",
        "linked_transaction_id": "transaction-cache-invalidation",
    }
    default_storage._row_cache["MixedUseExpenses"] = []
    default_storage._row_cache["Transactions"] = []
    original_append = default_storage._append

    def fail_projection_append(title: str, record: dict[str, str]) -> None:
        if title == "Transactions":
            raise StorageUnavailableError("projection write failed", retryable=True)
        original_append(title, record)

    default_storage._append = fail_projection_append  # type: ignore[method-assign]
    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.create_mixed_use_expense(**inputs)

    assert "MixedUseExpenses" not in default_storage._row_cache
    assert "Transactions" not in default_storage._row_cache


def test_mixed_use_create_projection_failure_guides_pair_inspection(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
        "total_expense": "100",
        "business_use_percentage": "50",
        "allocation_rationale": "Measured use",
        "source_id": "source-projection-guidance",
        "linked_transaction_id": "transaction-projection-guidance",
    }
    original_append = default_storage._append

    def fail_projection_append(title: str, record: dict[str, str]) -> None:
        if title == "Transactions":
            raise StorageUnavailableError("projection write unavailable")
        original_append(title, record)

    default_storage._append = fail_projection_append  # type: ignore[method-assign]
    with pytest.raises(
        StorageUnavailableError,
        match="could not confirm the mixed-use create.*Mixed-use expenses and the Transactions ledger",
    ) as raised:
        default_storage.create_mixed_use_expense(**inputs)

    assert raised.value.retryable is False
    assert (
        default_storage.list_mixed_use_expense_sources()[0]["id"] == inputs["source_id"]
    )
    assert default_storage.list_transactions() == []


def test_mixed_use_create_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = {
        **expense_inputs(default_storage),
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
            raise StorageUnavailableError("response lost", retryable=True)

    default_storage._append = append_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.create_mixed_use_expense(**inputs)

    assert result["id"] == inputs["source_id"]
    assert len(default_storage.list_transactions()) == 1


def test_mixed_use_edit_returns_success_when_final_response_is_lost(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_replace = default_storage._replace_rows_atomically

    def replace_then_lose_final_result(updates: object) -> None:
        original_replace(updates)  # type: ignore[arg-type]
        raise StorageUnavailableError("response lost", retryable=True)

    default_storage._replace_rows_atomically = replace_then_lose_final_result  # type: ignore[method-assign]
    result = default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="200",
        business_use_percentage="25",
        allocation_rationale="Updated use",
    )

    assert result["allocated_amount"] == "50.00"


def test_mixed_use_edit_replaces_pair_in_one_spreadsheet_batch(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch = default_storage._batch_update_spreadsheet
    batches: list[object] = []

    def record_batch(requests: object) -> None:
        batches.append(requests)
        original_batch(requests)  # type: ignore[arg-type]

    default_storage._batch_update_spreadsheet = record_batch  # type: ignore[method-assign]
    default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="200",
        business_use_percentage="25",
        allocation_rationale="Updated use",
    )

    assert len(batches) == 1
    requests = batches[0]
    assert isinstance(requests, list)
    assert len(requests) == 2
    assert {request["updateCells"]["range"]["sheetId"] for request in requests} == {
        default_storage._sheet_id("Transactions"),
        default_storage._sheet_id("MixedUseExpenses"),
    }


def test_mixed_use_edit_rejects_receipt_drift_before_replacing_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
            transaction_sheet.rows[1][
                transaction_headers.index("receipt_references")
            ] = reference
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
        **expense_inputs(default_storage),
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
            transaction_sheet.rows[1][
                transaction_headers.index("receipt_references")
            ] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
            default_storage._invalidate("Transactions")
            default_storage._invalidate("MixedUseExpenses")
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_concurrent_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="receipt pair changed"):
        default_storage.set_mixed_use_receipt_references(
            source["id"], [], expected_source=source
        )


def test_mixed_use_receipt_update_refreshes_row_position_before_writing(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
    updated = default_storage.set_mixed_use_receipt_references(
        source["id"], [], expected_source=source
    )

    assert updated["id"] == source["linked_transaction_id"]
    rows = default_storage._rows("Transactions", force_refresh=True)
    assert [
        (item.row_number, item.values["id"], item.values["receipt_references"])
        for item in rows
    ] == [
        (2, "unrelated-transaction", "[]"),
        (3, source["linked_transaction_id"], "[]"),
    ]
    assert rows[0].values["id"] == "unrelated-transaction"
    assert rows[0].values["receipt_references"] == "[]"
    assert rows[1].values["id"] == source["linked_transaction_id"]
    assert rows[1].values["receipt_references"] == "[]"


def test_uncertain_mixed_use_receipt_link_confirms_pair_without_retry(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch_update = default_storage._workbook.batch_update

    def commit_then_timeout(body: dict[str, object]) -> None:
        original_batch_update(body)
        raise OSError("response lost after mixed-use receipt link")

    default_storage._workbook.batch_update = Mock(side_effect=commit_then_timeout)

    default_storage.link_mixed_use_receipt(
        source["id"],
        reference={"id": "receipt123456", "name": "statement.pdf"},
        expected_source=source,
    )

    assert default_storage._workbook.batch_update.call_count == 1
    refreshed_source = default_storage.get_mixed_use_expense(source["id"])
    projection = default_storage.list_transactions(_force_refresh=True)[0]
    assert refreshed_source["receipt_references"] == projection["receipt_references"]
    assert decode_receipt_references(projection["receipt_references"])[0]["id"] == (
        "receipt123456"
    )


def test_receipt_recovery_restarts_after_mixed_use_pair_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
            transaction_sheet.rows[1][
                transaction_headers.index("receipt_references")
            ] = reference
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


def test_receipt_recovery_refreshes_transaction_rows_with_source_snapshot(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        receipt_references=[{"id": "old-receipt", "name": "Receipt"}],
    )
    transaction_id = source["linked_transaction_id"]
    expected_transactions = default_storage.list_transactions()
    original_snapshot = default_storage._snapshot
    final_snapshot_seen = False

    def snapshot_with_transaction_row_shift(
        titles: object, *, force_refresh: bool = False
    ) -> dict[str, object]:
        nonlocal final_snapshot_seen
        titles_list = list(titles)  # type: ignore[arg-type]
        if titles_list == ["Transactions", "MixedUseExpenses"]:
            final_snapshot_seen = True
            worksheet = default_storage._worksheet("Transactions")
            inserted = [""] * len(worksheet.rows[1])
            worksheet.rows.insert(1, inserted)
            default_storage._invalidate("Transactions")
        return original_snapshot(titles_list, force_refresh=force_refresh)

    default_storage._snapshot = snapshot_with_transaction_row_shift  # type: ignore[method-assign]
    applied, _ = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {transaction_id: [{"id": "new-receipt", "name": "Receipt"}]},
    )

    assert applied is True
    assert final_snapshot_seen is True
    rows = default_storage._rows("Transactions", force_refresh=True)
    assert [
        (row.row_number, row.values["id"], row.values["receipt_references"])
        for row in rows
    ] == [
        (3, transaction_id, '[{"id":"new-receipt","name":"Receipt"}]'),
    ]


def test_receipt_recovery_restarts_after_unrelated_receipt_drift_during_final_read(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        receipt_references=[{"id": "old-receipt", "name": "Receipt"}],
    )
    unrelated = default_storage.create_transaction(
        **expense_inputs(default_storage),
        kind="Expense",
        amount="20",
    )
    expected_transactions = default_storage.list_transactions()
    original_snapshot = default_storage._snapshot
    final_snapshot_seen = False

    def snapshot_with_unrelated_receipt_drift(
        titles: object, *, force_refresh: bool = False
    ) -> dict[str, object]:
        nonlocal final_snapshot_seen
        titles_list = list(titles)  # type: ignore[arg-type]
        if titles_list == ["Transactions", "MixedUseExpenses"]:
            final_snapshot_seen = True
            worksheet = default_storage._worksheet("Transactions")
            headers = default_storage._headers("Transactions")
            unrelated_row = next(
                row
                for row in worksheet.rows[1:]
                if row[headers.index("id")] == unrelated["id"]
            )
            unrelated_row[headers.index("receipt_references")] = (
                '[{"id":"unrelated-receipt","name":"Receipt"}]'
            )
            default_storage._invalidate("Transactions")
        return original_snapshot(titles_list, force_refresh=force_refresh)

    default_storage._snapshot = snapshot_with_unrelated_receipt_drift  # type: ignore[method-assign]
    applied, fresh_transactions = default_storage.apply_receipt_recovery_plan(
        expected_transactions,
        {source["linked_transaction_id"]: [{"id": "new-receipt", "name": "Receipt"}]},
    )

    assert applied is False
    assert final_snapshot_seen is True
    assert (
        next(row for row in fresh_transactions if row["id"] == unrelated["id"])[
            "receipt_references"
        ]
        == '[{"id":"unrelated-receipt","name":"Receipt"}]'
    )
    assert (
        next(
            row
            for row in fresh_transactions
            if row["id"] == source["linked_transaction_id"]
        )["receipt_references"]
        == source["receipt_references"]
    )


def test_receipt_recovery_restarts_after_mixed_use_provenance_drift(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    unrelated = default_storage.create_transaction(
        **expense_inputs(default_storage),
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
    assert (
        next(item for item in fresh_transactions if item["id"] == unrelated["id"])[
            "receipt_references"
        ]
        == '[{"id":"unrelatedreceipt","name":"Receipt"}]'
    )
    assert (
        next(
            item
            for item in fresh_transactions
            if item["id"] == source["linked_transaction_id"]
        )["receipt_references"]
        == "[]"
    )


def test_mixed_use_delete_rejects_pair_drift_before_deleting_rows(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
            transaction_sheet.rows[1][
                transaction_headers.index("receipt_references")
            ] = reference
            source_sheet.rows[1][source_headers.index("receipt_references")] = reference
        calls += 1
        return original_find(title, record_id)

    default_storage._find_row = find_after_receipt_update  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert len(default_storage._rows("Transactions", force_refresh=True)) == 1
    assert len(default_storage._rows("MixedUseExpenses", force_refresh=True)) == 1


def test_mixed_use_delete_confirms_final_delete_after_lost_response(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch_update = default_storage._workbook.batch_update

    def delete_then_lose_response(body: object) -> None:
        original_batch_update(body)
        raise OSError("response lost after delete")

    default_storage._workbook.batch_update = delete_then_lose_response

    default_storage.delete_mixed_use_expense(source["id"])

    assert default_storage.list_mixed_use_expenses() == []
    assert default_storage.list_transactions() == []


def test_mixed_use_delete_partial_pair_stops_without_retry(
    default_storage: GoogleSheetsStorage,
    monkeypatch,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def partial_then_lose_response(body: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        original_batch_update({"requests": body["requests"][:1]})
        raise OSError("response lost after partial deletion")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", partial_then_lose_response
    )

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.delete_mixed_use_expense(source["id"])

    assert calls == 1
    assert "Transactions" not in default_storage._row_cache
    assert "MixedUseExpenses" not in default_storage._row_cache
