from __future__ import annotations

import pytest

from tabula_rasa.storage import (
    StorageBulkMutationUncertainError,
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


def test_non_applied_management_batch_is_classified(default_storage, monkeypatch) -> None:
    tag = default_storage.create_tag("Unused")

    def fail(_requests):
        raise StorageBulkMutationUncertainError(
            "temporary", outcome="not_applied", retryable=True
        )

    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", fail)
    with pytest.raises(StorageBulkMutationUncertainError) as raised:
        default_storage.remove_tag(tag["id"])
    assert raised.value.outcome == "not_applied"
    assert raised.value.retryable is True


def test_partial_source_delete_is_ambiguous_not_retryable(default_storage, monkeypatch) -> None:
    first = default_storage.create_tag("First")
    second = default_storage.create_tag("Second")
    target = default_storage.create_tag("Target")

    def partial_delete(_requests):
        row = default_storage._find_row("Tags", first["id"])
        default_storage._worksheet("Tags").delete_rows(row.row_number)
        raise StorageUnavailableError("response lost", retryable=True)

    monkeypatch.setattr(default_storage, "_batch_update_spreadsheet", partial_delete)
    with pytest.raises(StorageBulkMutationUncertainError) as raised:
        default_storage.merge_tags(target["id"], [first["id"], second["id"]])
    assert raised.value.outcome == "mixed_ambiguous"
    assert raised.value.retryable is False


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
