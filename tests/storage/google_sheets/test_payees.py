from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageValidationError,
)
from tests.fakes import FakeWorkbook

def _ledger_setup(
    storage: GoogleSheetsStorage,
) -> tuple[dict[str, str], dict[str, str]]:
    account = next(item for item in storage.list_accounts(active_only=False) if item["name"] == "Checking")
    category = next(item for item in storage.list_categories() if item["name"] == "Office")
    return account, category


def test_legacy_payee_aliases_remain_available(default_storage) -> None:
    target = default_storage.create_payee("Alias target")
    source = default_storage.create_payee("Alias source")
    assert default_storage.merge_payee(target["id"], [source["id"]])["status"] == "fully_applied"
    assert default_storage.delete_payee(target["id"])["status"] == "fully_applied"


def test_merge_payees_rewrites_recurring_schedule_references(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_payee("Target vendor")
    source = default_storage.create_payee("Source vendor")
    default_storage.create_recurring_expense(
        schedule_id="payee-schedule", name="Subscription", txn_date="2026-01-01",
        recurrence_unit="month", amount=10, account_id=account["id"],
        category_id=category["id"], payee_id=source["id"],
    )

    default_storage.merge_payees(target["id"], [source["id"]])

    assert default_storage.get_recurring_schedule("payee-schedule")["payee_id"] == target["id"]


def test_referenced_payee_remove_is_blocked(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    payee = default_storage.create_payee("Used")
    default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"], payee_id=payee["id"],
    )
    with pytest.raises(StorageConflictError, match="referenced by 1"):
        default_storage.remove_payee(payee["id"])


def test_recurring_schedule_payee_reference_blocks_remove(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    payee = default_storage.create_payee("Recurring vendor")
    default_storage.create_recurring_expense(
        schedule_id="payee-reference-schedule", name="Subscription", txn_date="2026-01-01",
        recurrence_unit="month", amount=10, account_id=account["id"],
        category_id=category["id"], payee_id=payee["id"],
    )

    with pytest.raises(StorageConflictError, match="referenced by 2"):
        default_storage.remove_payee(payee["id"])


def test_expected_payee_snapshot_protects_rename(default_storage) -> None:
    payee = default_storage.create_payee("Vendor")
    expected = dict(payee)
    default_storage.edit_payee(payee["id"], name="Changed")
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.edit_payee(payee["id"], name="New", expected_payee=expected)


def test_payee_edit_preserves_id_and_supports_activation(default_storage) -> None:
    payee = default_storage.create_payee("Vendor")

    renamed = default_storage.edit_payee(
        payee["id"], name="Renamed Vendor", active=False
    )
    reactivated = default_storage.edit_payee(payee["id"], active=True)

    assert renamed["id"] == payee["id"]
    assert renamed["name"] == "Renamed Vendor"
    assert renamed["active"] == "FALSE"
    assert reactivated["id"] == payee["id"]
    assert reactivated["active"] == "TRUE"


def test_payee_rename_rejects_normalized_name_collision(default_storage) -> None:
    first = default_storage.create_payee("First vendor")
    second = default_storage.create_payee("Second vendor")

    with pytest.raises(StorageConflictError, match="already exists"):
        default_storage.edit_payee(second["id"], name=" first   vendor ")

    assert default_storage.list_payees(active_only=False) == [first, second]

@pytest.mark.parametrize("reference_kind", ["payee", "account", "transfer_destination"])
def test_edit_preserves_unchanged_inactive_references(reference_kind: str) -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    if reference_kind == "payee":
        payee = storage.create_payee("Vendor")
        transaction = storage.create_transaction(
            txn_date="2026-09-01", kind="Expense", amount=10,
            account_id=account["id"], category_id=category["id"], payee_id=payee["id"],
        )
        storage.edit_payee(payee["id"], active=False)
        column, reference_id = "payee_id", payee["id"]
    elif reference_kind == "account":
        transaction = storage.create_transaction(
            txn_date="2026-09-01", kind="Expense", amount=10,
            account_id=account["id"], category_id=category["id"],
        )
        storage.edit_account(account["id"], active=False)
        column, reference_id = "account_id", account["id"]
    else:
        destination = storage.create_account("Savings", "Bank")
        transaction = storage.create_transaction(
            txn_date="2026-09-01", kind="Transfer", amount=10,
            account_id=account["id"], to_account_id=destination["id"],
        )
        storage.edit_account(destination["id"], active=False)
        column, reference_id = "to_account_id", destination["id"]

    transaction_sheet = workbook.worksheet("Transactions")
    reference_index = transaction_sheet.rows[0].index(column)
    transaction_sheet.rows[1][reference_index] = f"  {reference_id}  "
    updated = storage.edit_transaction(transaction["id"], description="Updated")
    assert updated[column] == reference_id
    assert updated["description"] == "Updated"


def test_edit_preserves_unchanged_inactive_transaction_references() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Vendor")
    transaction = storage.create_transaction(
        txn_date="2026-09-01", kind="Expense", amount=10,
        account_id=account["id"], category_id=category["id"], payee_id=payee["id"],
    )
    storage.edit_account(account["id"], active=False)
    storage.edit_payee(payee["id"], active=False)
    updated = storage.edit_transaction(transaction["id"], description="Updated")
    assert updated["account_id"] == account["id"]
    assert updated["payee_id"] == payee["id"]
    assert updated["description"] == "Updated"

def test_payees_are_normalized_and_transactions_store_references() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    first = storage.create_payee("  Acme   Supplies ")
    second = storage.create_payee("acme supplies")

    assert second["id"] == first["id"]
    transaction = storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=first["id"],
    )

    assert transaction["payee_id"] == first["id"]
    assert storage.list_transactions()[0]["payee"] == "Acme   Supplies"


def test_ensuring_payees_batches_reactivation_writes() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    first = storage.create_payee("First vendor")
    second = storage.create_payee("Second vendor")
    storage.edit_payee(first["id"], active=False)
    storage.edit_payee(second["id"], active=False)
    payee_sheet = workbook.worksheet("Payees")
    original_batch_update = payee_sheet.batch_update
    payee_sheet.batch_update = Mock(wraps=original_batch_update)  # type: ignore[method-assign]

    storage._ensure_payee_names(["First vendor", "Second vendor"])

    assert payee_sheet.batch_update.call_count == 1
    assert {item["id"] for item in storage.list_payees()} == {
        first["id"],
        second["id"],
    }


def test_ensuring_payees_reactivates_ids_with_storage_whitespace() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    payee = storage.create_payee("Vendor")
    storage.edit_payee(payee["id"], active=False)
    payee_row = workbook.worksheet("Payees").rows[1]
    payee_row[0] = f"  {payee['id']}  "

    ensured = storage._ensure_payee_names(["Vendor"])

    assert ensured[payee["id"]]["active"] == "TRUE"
    assert storage.list_payees()[0]["active"] == "TRUE"


def test_list_transactions_rejects_unknown_payee_references() -> None:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    transaction_sheet = workbook.worksheet("Transactions")
    payee_id_index = transaction_sheet.rows[0].index("payee_id")
    transaction_sheet.rows[1][payee_id_index] = "missing-payee"

    with pytest.raises(StorageValidationError, match="Payee does not exist"):
        storage.list_transactions(_force_refresh=True)


def test_transactions_reject_arbitrary_payee_text_after_migration() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    with pytest.raises(StorageValidationError, match="stored payee"):
        storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            payee="Free text must not persist",
        )

    assert storage.list_transactions() == []


def test_invalid_transaction_does_not_create_new_payee() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")

    with pytest.raises(StorageValidationError, match="greater than zero"):
        storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=0,
            account_id=account["id"],
            category_id=category["id"],
            new_payee_name="Should not be created",
        )

    assert storage.list_payees() == []


def test_quickbooks_import_batches_new_payee_writes() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    payee_sheet = storage._workbook.sheets["Payees"]
    payee_sheet.append_rows = Mock(wraps=payee_sheet.append_rows)

    rows = [
        {
            "Date": f"09/0{index}/2026",
            "Transaction Type": "Expense",
            "Num": str(index),
            "Name": f"Vendor {index}",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
        for index in range(1, 4)
    ]

    imported = storage.import_quickbooks_transactions(rows)

    assert len(imported) == 3
    assert payee_sheet.append_rows.call_count == 1
    assert {item["payee"] for item in imported} == {
        "Vendor 1",
        "Vendor 2",
        "Vendor 3",
    }


def test_quickbooks_import_reuses_canonical_payee_for_duplicates() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.create_payee("Acme Inc")
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme  Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
    ]

    assert len(storage.import_quickbooks_transactions(rows)) == 1
    assert storage.import_quickbooks_transactions(rows) == []
    assert len(storage.list_transactions()) == 1


def test_quickbooks_import_deduplicates_unseen_payee_variants() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        },
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Acme  Inc",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        },
    ]

    preview = storage.preview_quickbooks_transactions(rows)

    assert len(preview["rows"]) == 1
    assert preview["duplicate_rows"] == [3]
    assert len(storage.import_quickbooks_transactions(rows)) == 1
    assert len(storage.list_payees()) == 1


def test_quickbooks_import_rejects_inactive_account_before_payee_write() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.edit_account(account["id"], active=False)
    rows = [
        {
            "Date": "09/01/2026",
            "Transaction Type": "Expense",
            "Num": "1",
            "Name": "Vendor",
            "Memo/Description": "Office supplies",
            "Account": "Checking",
            "Split": "Office",
            "Amount": "(10.00)",
        }
    ]

    preview = storage.preview_quickbooks_transactions(rows)

    assert preview["rows"] == []
    assert preview["errors"] == [
        "QuickBooks row 2: source account 'Checking' is inactive"
    ]
    with pytest.raises(StorageValidationError, match="source account.*inactive"):
        storage.import_quickbooks_transactions(rows)
    assert storage.list_payees() == []
    assert storage.list_transactions() == []


def test_concurrent_payee_creation_rechecks_inside_shared_lock() -> None:
    workbook = FakeWorkbook()
    first = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    second = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    payee_sheet = workbook.worksheet("Payees")
    original_append = payee_sheet.append_row
    append_started = threading.Event()
    release_append = threading.Event()

    def delayed_append(values: list[str], **kwargs: object) -> None:
        if not append_started.is_set():
            append_started.set()
            assert release_append.wait(timeout=2)
        original_append(values, **kwargs)

    payee_sheet.append_row = delayed_append  # type: ignore[method-assign]
    results: list[dict[str, str]] = []

    def create(storage: GoogleSheetsStorage) -> None:
        results.append(storage.create_payee("Concurrent vendor"))

    first_thread = threading.Thread(target=create, args=(first,))
    second_thread = threading.Thread(target=create, args=(second,))
    first_thread.start()
    assert append_started.wait(timeout=2)
    second_thread.start()
    release_append.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert len(results) == 2
    assert results[0]["id"] == results[1]["id"]
    assert len(workbook.worksheet("Payees").rows) == 2


def test_concurrent_payee_renames_recheck_inside_shared_lock() -> None:
    workbook = FakeWorkbook()
    first = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    second = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    first_payee = first.create_payee("First vendor")
    second_payee = second.create_payee("Second vendor")
    payee_sheet = workbook.worksheet("Payees")
    original_update = payee_sheet.update
    update_started = threading.Event()
    release_update = threading.Event()

    def delayed_update(
        values: list[list[str]], range_name: str, **kwargs: object
    ) -> None:
        if not update_started.is_set():
            update_started.set()
            assert release_update.wait(timeout=2)
        original_update(values, range_name, **kwargs)

    payee_sheet.update = delayed_update  # type: ignore[method-assign]
    renamed: list[dict[str, str]] = []
    errors: list[Exception] = []

    def rename(storage: GoogleSheetsStorage, payee_id: str) -> None:
        try:
            renamed.append(storage.edit_payee(payee_id, name="Merged vendor"))
        except Exception as error:  # pragma: no cover - assertion below checks the type
            errors.append(error)

    first_thread = threading.Thread(target=rename, args=(first, first_payee["id"]))
    second_thread = threading.Thread(target=rename, args=(second, second_payee["id"]))
    first_thread.start()
    assert update_started.wait(timeout=2)
    second_thread.start()
    release_update.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert len(renamed) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], StorageConflictError)
    assert len(workbook.worksheet("Payees").rows) == 3


def test_new_payee_transaction_uses_created_record_without_refresh() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    original_lookup = storage._payee_lookup
    storage._payee_lookup = Mock(wraps=original_lookup)

    storage.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
        new_payee_name="New vendor",
    )

    assert storage._payee_lookup.call_count == 1
    assert storage._payee_lookup.call_args.kwargs["force_refresh"] is False


def test_csv_import_validates_all_rows_before_creating_payees() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    rows = [
        {
            "Date": "2026-09-01",
            "Type": "Expense",
            "Account": "Checking",
            "Category": "Office",
            "Amount": "10.00",
            "Payee": "First vendor",
        },
        {
            "Date": "not-a-date",
            "Type": "Expense",
            "Account": "Checking",
            "Category": "Office",
            "Amount": "10.00",
            "Payee": "Second vendor",
        },
    ]

    with pytest.raises(StorageValidationError, match="Date"):
        storage.import_csv_transactions(rows)

    assert storage.list_transactions() == []
    assert storage.list_payees() == []
    assert account["name"] == "Checking"
    assert category["name"] == "Office"

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
