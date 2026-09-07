from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from threading import Event, Thread

from tabula_rasa.storage import (
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
)
from tests.app_support import authenticated_app, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


def _ledger_setup(storage):
    account = next(item for item in storage.list_accounts(active_only=False) if item["name"] == "Checking")
    category = next(item for item in storage.list_categories() if item["name"] == "Office")
    return account, category


def test_payee_rename_preserves_id_and_references(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    payee = default_storage.create_payee("Vendor")
    transaction = default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"], payee_id=payee["id"],
    )

    renamed = default_storage.edit_payee(payee["id"], name="Renamed Vendor")

    assert renamed["id"] == payee["id"]
    assert default_storage.list_transactions()[0]["payee_id"] == transaction["payee_id"]
    assert default_storage.list_transactions()[0]["payee"] == "Renamed Vendor"


def test_payee_append_rechecks_name_before_retry(default_storage) -> None:
    worksheet = default_storage._worksheet("Payees")
    headers = default_storage._headers("Payees")
    original_append = worksheet.append_row
    calls = 0

    def duplicate_then_timeout(values: list[str], **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            duplicate = {header: "" for header in headers}
            duplicate.update(
                {
                    "id": "external-payee",
                    "name": "Concurrent Vendor",
                    "active": "TRUE",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            )
            original_append(
                [duplicate.get(header, "") for header in headers], **kwargs
            )
            raise OSError("temporary response lost")
        original_append(values, **kwargs)

    worksheet.append_row = duplicate_then_timeout  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="already exists"):
        default_storage.create_payee("Concurrent Vendor")

    assert calls == 1


def test_payee_batch_append_rechecks_name_before_retry(default_storage) -> None:
    worksheet = default_storage._worksheet("Payees")
    original_append = worksheet.append_rows
    calls = 0

    def duplicate_then_timeout(
        values: list[list[str]], **kwargs: object
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            duplicate = list(values[0])
            duplicate[0] = "external-payee-batch"
            original_append([duplicate], **kwargs)
            raise OSError("temporary response lost")
        original_append(values, **kwargs)

    worksheet.append_rows = duplicate_then_timeout  # type: ignore[method-assign]
    with pytest.raises(StorageConflictError, match="already exists"):
        default_storage._ensure_payee_names(["Concurrent Batch Vendor"])

    assert calls == 1


def test_payee_merge_updates_mixed_use_source_and_projection(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_payee("Target")
    source = default_storage.create_payee("Source")
    mixed = default_storage.create_mixed_use_expense(
        txn_date="2026-01-01", account_id=account["id"], category_id=category["id"],
        payee_id=source["id"], total_expense="100", business_use_percentage="50",
        allocation_rationale="Shared use",
    )

    result = default_storage.merge_payees(target["id"], [source["id"]])

    assert result["status"] == "fully_applied"
    assert default_storage.list_transactions()[0]["payee_id"] == target["id"]
    assert default_storage.list_mixed_use_expenses()[0]["payee_id"] == target["id"]
    assert source["id"] not in {item["id"] for item in default_storage.list_payees(active_only=False)}
    assert mixed["id"] == default_storage.list_mixed_use_expenses()[0]["id"]


def test_payee_merge_rechecks_new_references_before_retry(
    default_storage, monkeypatch
) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_payee("Retry target")
    source = default_storage.create_payee("Retry source")
    calls = 0

    def add_reference_during_backoff(_: float) -> None:
        default_storage.create_transaction(
            txn_date="2026-01-01",
            kind="Expense",
            amount="10",
            account_id=account["id"],
            category_id=category["id"],
            payee_id=source["id"],
        )

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise StorageUnavailableError("temporary response lost", retryable=True)

    monkeypatch.setattr(default_storage, "_sleeper", add_reference_during_backoff)
    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", fail_once)

    with pytest.raises(StorageConflictError, match="references changed"):
        default_storage.merge_payees(target["id"], [source["id"]])

    assert calls == 1
    assert source["id"] in {
        item["id"] for item in default_storage.list_payees(active_only=False)
    }


def test_tag_merge_deduplicates_transactions_and_mileage(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    transaction = default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"],
        tag_ids=[target["id"], source["id"]], description="keep",
    )
    mileage = default_storage.create_mileage_trip(
        trip_date="2026-01-01", miles="2", start_location="A", destination="B",
        business_purpose="Visit", vehicle="Car", tag_ids=[source["id"]],
    )

    default_storage.merge_tags(target["id"], [source["id"]])

    assert default_storage.list_transactions()[0]["tag_ids"] == [target["id"]]
    assert default_storage.list_transactions()[0]["description"] == transaction["description"]
    assert default_storage.list_mileage_trips()[0]["tag_ids"] == [target["id"]]
    assert source["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}
    assert mileage["id"] == default_storage.list_mileage_trips()[0]["id"]


def test_tag_merge_rechecks_new_references_before_retry(
    default_storage, monkeypatch
) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Retry target")
    source = default_storage.create_tag("Retry source")
    calls = 0

    def add_reference_during_backoff(_: float) -> None:
        default_storage.create_transaction(
            txn_date="2026-01-01",
            kind="Expense",
            amount="10",
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[source["id"]],
        )

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise StorageUnavailableError("temporary response lost", retryable=True)

    monkeypatch.setattr(default_storage, "_sleeper", add_reference_during_backoff)
    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", fail_once)

    with pytest.raises(StorageConflictError, match="references changed"):
        default_storage.merge_tags(target["id"], [source["id"]])

    assert calls == 1
    assert source["id"] in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }


def test_referenced_remove_is_blocked_and_unreferenced_remove_succeeds(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    payee = default_storage.create_payee("Used")
    default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"], payee_id=payee["id"],
    )
    with pytest.raises(StorageConflictError, match="referenced by 1"):
        default_storage.remove_payee(payee["id"])

    unused = default_storage.create_tag("Unused")
    result = default_storage.remove_tag(unused["id"])
    assert result["status"] == "fully_applied"
    assert unused["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_management_expected_snapshot_rejects_stale_merge(default_storage) -> None:
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    expected = default_storage.list_tags(active_only=False)
    default_storage.edit_tag(source["id"], name="Changed")

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.merge_tags(target["id"], [source["id"]], expected_tags=expected)


def test_tag_merge_confirms_committed_write_without_retry(default_storage, monkeypatch) -> None:
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def commit_then_lose_response(body: object) -> None:
        nonlocal calls
        original_batch_update(body)
        calls += 1
        raise OSError("response lost after commit")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", commit_then_lose_response
    )

    result = default_storage.merge_tags(target["id"], [source["id"]])

    assert result == {"status": "fully_applied", "count": "1"}
    assert calls == 1
    assert source["id"] not in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }


def test_tag_removal_retries_once_then_invalidates_on_unchanged_failure(
    default_storage, monkeypatch
) -> None:
    tag = default_storage.create_tag("Unused")
    batch_update = Mock(side_effect=OSError("temporary response lost"))
    monkeypatch.setattr(default_storage._workbook, "batch_update", batch_update)

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.remove_tag(tag["id"])

    assert batch_update.call_count == 2
    assert "Tags" not in default_storage._row_cache


def test_tag_removal_rebuilds_row_after_shift_before_retry(default_storage, monkeypatch) -> None:
    tag = default_storage.create_tag("Shifted")
    worksheet = default_storage._worksheet("Tags")
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def shift_then_lose_response(body: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-before-retry"
            raise OSError("temporary response lost")
        original_batch_update(body)

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", shift_then_lose_response
    )

    default_storage.remove_tag(tag["id"])

    assert calls == 2
    assert tag["id"] not in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }
    assert worksheet.rows[1][0] == "inserted-before-retry"


def test_tag_removal_rechecks_references_after_retry_backoff(
    default_storage, monkeypatch
) -> None:
    account, category = _ledger_setup(default_storage)
    tag = default_storage.create_tag("Referenced during retry")
    calls = 0

    def add_reference_during_backoff(_: float) -> None:
        default_storage.create_transaction(
            txn_date="2026-01-01",
            kind="Expense",
            amount="10",
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[tag["id"]],
        )

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise OSError("temporary response lost")

    monkeypatch.setattr(default_storage, "_sleeper", add_reference_during_backoff)
    monkeypatch.setattr(default_storage._workbook, "batch_update", fail_once)

    with pytest.raises(StorageConflictError, match="became referenced"):
        default_storage.remove_tag(tag["id"])

    assert calls == 1
    assert tag["id"] in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }


def test_tag_merge_partial_write_stops_without_retry(default_storage, monkeypatch) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    default_storage.create_transaction(
        txn_date="2026-01-01",
        kind="Expense",
        amount="10",
        account_id=account["id"],
        category_id=category["id"],
        tag_ids=[source["id"]],
    )
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def partial_then_lose_response(body: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        original_batch_update({"requests": body["requests"][:1]})
        raise OSError("response lost after partial application")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", partial_then_lose_response
    )

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.merge_tags(target["id"], [source["id"]])

    assert calls == 1
    assert "Tags" not in default_storage._row_cache


def test_expected_management_snapshot_preserves_falsy_values() -> None:
    current = {"tag-1": {"id": "tag-1", "active": "FALSE", "count": "0"}}
    expected = {"id": "tag-1", "active": False, "count": 0}

    GoogleSheetsStorage._assert_expected_managed_records(current, expected)


def test_repeated_merge_with_original_snapshot_converges(default_storage) -> None:
    target = default_storage.create_payee("Target")
    source = default_storage.create_payee("Source")
    expected = default_storage.list_payees(active_only=False)

    default_storage.merge_payees(target["id"], [source["id"]])
    result = default_storage.merge_payees(
        target["id"], [source["id"]], expected_payees=expected
    )

    assert result["status"] == "fully_applied"


def test_missing_sources_with_surviving_references_never_converge(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_payee("Target")
    source = default_storage.create_payee("Source")
    default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"], payee_id=source["id"],
    )
    source_row = default_storage._find_row("Payees", source["id"])
    default_storage._worksheet("Payees").delete_rows(source_row.row_number)

    with pytest.raises(StorageConflictError, match="references remain"):
        default_storage.merge_payees(target["id"], [source["id"]])


def test_payee_merge_rejects_corrupt_mixed_use_pair(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_payee("Target")
    source = default_storage.create_payee("Source")
    default_storage.create_mixed_use_expense(
        txn_date="2026-01-01", account_id=account["id"], category_id=category["id"],
        payee_id=source["id"], total_expense="100", business_use_percentage="50",
        allocation_rationale="Shared use",
    )
    projection = default_storage._rows("Transactions", force_refresh=True)[0]
    payee_column = default_storage._headers("Transactions").index("payee_id")
    projection.values["payee_id"] = target["id"]
    # Mutate the fake workbook directly to model an externally corrupt pair.
    default_storage._worksheet("Transactions").rows[projection.row_number - 1][payee_column] = target["id"]

    with pytest.raises(StorageValidationError, match="source and projection"):
        default_storage.merge_payees(target["id"], [source["id"]])


def test_expected_snapshots_protect_rename_and_remove(default_storage) -> None:
    payee = default_storage.create_payee("Vendor")
    expected_payee = dict(payee)
    default_storage.edit_payee(payee["id"], name="Changed")
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_payee(
            payee["id"], name="New", expected_payee=expected_payee
        )

    tag = default_storage.create_tag("Label")
    expected_tag = dict(tag)
    default_storage.edit_tag(tag["id"], name="Changed label")
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.remove_tag(tag["id"], expected_tag=expected_tag)


def test_management_operations_are_isolated_between_profiles() -> None:
    first = GoogleSheetsStorage(FakeWorkbook())
    second = GoogleSheetsStorage(FakeWorkbook())
    first.ensure_defaults()
    second.ensure_defaults()
    first_account, first_category = _ledger_setup(first)
    second_account, second_category = _ledger_setup(second)
    first_target = first.create_payee("Shared target")
    first_source = first.create_payee("Shared source")
    second_target = second.create_payee("Shared target")
    second_source = second.create_payee("Shared source")
    second_transaction = second.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=second_account["id"], category_id=second_category["id"],
        payee_id=second_source["id"],
    )

    first.edit_payee(first_target["id"], name="First-only target")
    first.merge_payees(first_target["id"], [first_source["id"]])
    first_unused = first.create_tag("Profile-only unused")
    second_unused = second.create_tag("Profile-only unused")
    first.remove_tag(first_unused["id"])

    assert second.list_payees(active_only=False) == [
        second_source,
        second_target,
    ]
    assert second.list_transactions()[0]["payee_id"] == second_transaction["payee_id"]
    assert second_unused["id"] in {item["id"] for item in second.list_tags(active_only=False)}


def test_create_transaction_cannot_interleave_management_remove(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    tag = default_storage.create_tag("In-flight")
    entered = Event()
    release = Event()
    original = default_storage._prepare_transaction

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_transaction = blocked_prepare
    writer = Thread(
        target=lambda: default_storage.create_transaction(
            txn_date="2026-01-01", kind="Expense", amount="10",
            account_id=account["id"], category_id=category["id"], tag_ids=[tag["id"]],
        )
    )
    writer.start()
    assert entered.wait(timeout=5)
    management_done = Event()
    def remove_after_writer() -> None:
        try:
            default_storage.remove_tag(tag["id"])
        except StorageConflictError:
            pass
        finally:
            management_done.set()

    management = Thread(target=remove_after_writer)
    management.start()
    assert not management_done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert not management.is_alive()
    assert tag["id"] in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_mileage_edit_cannot_interleave_tag_merge(default_storage) -> None:
    tag = default_storage.create_tag("In-flight")
    trip = default_storage.create_mileage_trip(
        trip_date="2026-01-01", miles="2", start_location="A", destination="B",
        business_purpose="Visit", vehicle="Car", tag_ids=[tag["id"]],
    )
    entered = Event()
    release = Event()
    original = default_storage._prepare_mileage_trip

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_mileage_trip = blocked_prepare
    writer = Thread(
        target=lambda: default_storage.edit_mileage_trip(
            trip["id"], notes="edited", tag_ids=[tag["id"]]
        )
    )
    writer.start()
    assert entered.wait(timeout=5)
    source = default_storage.create_tag("Other")
    done = Event()
    management = Thread(
        target=lambda: (default_storage.merge_tags(source["id"], [tag["id"]]), done.set())
    )
    management.start()
    assert not done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert done.is_set()


def test_mileage_import_cannot_interleave_management_remove(default_storage) -> None:
    tag = default_storage.create_tag("Import lock")
    entered = Event()
    release = Event()
    original = default_storage._prepare_mileage_trip

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_mileage_trip = blocked_prepare
    rows = [
        {
            "Trip Date": "07/20/2026",
            "Trip Type": "Business",
            "Business Purpose": "Client meeting",
            "Vehicle Used": "Blue car",
            "Starting Point": "Office",
            "Ending Point": "Client site",
            "Distance (km)": "10 km",
        }
    ]
    writer = Thread(target=lambda: default_storage.import_quickbooks_mileage(rows))
    writer.start()
    assert entered.wait(timeout=5)
    done = Event()
    management = Thread(
        target=lambda: (default_storage.remove_tag(tag["id"]), done.set())
    )
    management.start()
    assert not done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert not management.is_alive()
    assert tag["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_transactions_exposes_profile_local_management_tab() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    with authenticated_app(storage=storage) as app:
        navigate_to(app, "Transactions")
        management = next(tab for tab in app.tabs if tab.label == "Payees & Tags")
        labels = [getattr(node, "label", "") for node in management]
        assert "Payees" in labels
        assert "Tags" in labels
        assert "New payee name" in labels
        assert "New tag name" in labels
        assert any(
            "Business profile:" in str(node.value)
            for node in app.caption
        )


def test_management_display_uses_prefetched_cached_rows() -> None:
    renderer_source = Path(
        "tabula_rasa/page_renderers/transactions/renderer.py"
    ).read_text(encoding="utf-8")
    management_source = Path(
        "tabula_rasa/page_renderers/transactions/payees_tags.py"
    ).read_text(encoding="utf-8")
    assert '"MixedUseExpenses"' in renderer_source
    assert '"Mileage"' in renderer_source
    assert "list_mixed_use_expense_sources()" in management_source
    assert "list_transactions()" in management_source
    assert "list_mileage_trips()" in management_source
    assert management_source.count("context.storage.list_transactions()") == 1
    assert "list_mixed_use_expenses(_force_refresh=True)" not in management_source
    assert "list_mileage_trips(_force_refresh=True)" not in management_source
    assert "list_payees(active_only=False, _force_refresh=True)" not in management_source
    assert "list_tags(active_only=False, _force_refresh=True)" not in management_source


def test_management_destructive_controls_scope_acknowledgement_and_style_hooks() -> None:
    management_source = Path(
        "tabula_rasa/page_renderers/transactions/payees_tags.py"
    ).read_text(encoding="utf-8")
    assert "managed_merge_payee_ack_{context.profile_key}_{target_id}_" in management_source
    assert "managed_merge_tag_ack_{context.profile_key}_{target_id}_" in management_source
    assert "managed_remove_payee_ack_{context.profile_key}_{remove_id}" in management_source
    assert "managed_remove_tag_ack_{context.profile_key}_{remove_id}" in management_source
    assert "disabled=is_referenced" in management_source
    assert management_source.count('str(item["active"]).upper() == "TRUE"') == 2
    assert 'key="destructive_managed_payee_remove"' in management_source
    assert 'key="destructive_managed_tag_remove"' in management_source
