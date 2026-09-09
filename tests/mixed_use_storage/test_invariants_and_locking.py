from __future__ import annotations

import threading

import pytest

from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageConflictError,
    StorageValidationError,
)
from tests.fakes import FakeWorkbook
from tests.mixed_use_storage._support import expense_inputs


def test_category_kind_change_rejects_mixed_use_references(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )

    with pytest.raises(StorageConflictError, match="mixed-use expense"):
        default_storage.edit_category(f" {source['category_id']} ", kind="Income")

    category = next(
        item
        for item in default_storage.list_categories()
        if item["id"] == source["category_id"]
    )
    assert category["kind"] == "Expense"


def test_transaction_mutation_uses_workbook_ledger_lock(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **expense_inputs(default_storage), kind="Expense", amount="10"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_transaction() -> None:
        started.set()
        try:
            default_storage.edit_transaction(transaction["id"], description="Updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_transaction)
    with default_storage._workbook_locks.ledger:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_storage_instances_for_same_spreadsheet_share_ledger_lock() -> None:
    first = GoogleSheetsStorage(
        FakeWorkbook(), spreadsheet_id="shared-spreadsheet", sleeper=lambda _: None
    )
    second = GoogleSheetsStorage(
        FakeWorkbook(), spreadsheet_id="shared-spreadsheet", sleeper=lambda _: None
    )
    first.ensure_defaults()
    second.ensure_defaults()
    category = next(
        item for item in second.list_categories() if item["name"] == "Office"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_category() -> None:
        started.set()
        try:
            second.edit_category(category["id"], name="Office updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_category)
    with first._workbook_locks.ledger:
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
    assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_different_spreadsheets_have_independent_ledger_locks() -> None:
    first = GoogleSheetsStorage(
        FakeWorkbook(), spreadsheet_id="first-spreadsheet", sleeper=lambda _: None
    )
    second = GoogleSheetsStorage(
        FakeWorkbook(), spreadsheet_id="second-spreadsheet", sleeper=lambda _: None
    )
    first.ensure_defaults()
    second.ensure_defaults()
    category = next(
        item for item in second.list_categories() if item["name"] == "Office"
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def edit_category() -> None:
        started.set()
        try:
            second.edit_category(category["id"], name="Office updated")
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=edit_category)
    with first._workbook_locks.ledger:
        worker.start()
        assert started.wait(1)
        assert finished.wait(1)
    worker.join(timeout=1)
    assert not errors


def test_category_delete_rejects_orphaned_mixed_use_source(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    projection = default_storage.list_transactions()[0]
    replacement = next(
        category
        for category in default_storage.list_categories()
        if category["kind"] == "Expense" and category["id"] != projection["category_id"]
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

    assert (
        default_storage.get_mixed_use_expense(source["id"])["linked_transaction_id"]
        == projection["id"]
    )


def test_mixed_use_create_rejects_transaction_collision_before_creating_payee(
    default_storage: GoogleSheetsStorage,
) -> None:
    transaction = default_storage.create_transaction(
        **expense_inputs(default_storage), kind="Expense", amount="10"
    )
    mixed_use_inputs = expense_inputs(default_storage)
    payees_before = default_storage.list_payees(active_only=False)
    mixed_use_inputs.update(
        payee_id="",
        new_payee_name="Should not be created",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        linked_transaction_id=transaction["id"],
    )

    with pytest.raises(StorageConflictError, match="already in use"):
        default_storage.create_mixed_use_expense(**mixed_use_inputs)

    assert default_storage.list_payees(active_only=False) == payees_before


def test_mixed_use_writes_reject_receipts_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    owner = default_storage.create_transaction(
        **expense_inputs(default_storage), kind="Expense", amount="10"
    )
    reference = {"id": "ownedreceipt01", "name": "Receipt.pdf"}
    default_storage.set_transaction_receipt_references(owner["id"], [reference])
    mixed_inputs = expense_inputs(default_storage)
    mixed_inputs["receipt_references"] = [reference]

    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.create_mixed_use_expense(
            **mixed_inputs,
            total_expense="100",
            business_use_percentage="50",
            allocation_rationale="Measured use",
        )

    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.edit_mixed_use_expense(
            source["id"], receipt_references=[reference]
        )


def test_mixed_use_receipt_remap_rejects_receipt_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    old_reference = {
        "id": "remap-old-receipt",
        "name": "Old.pdf",
        "receipt_id": "0123456789abcdef0123456789abcdef",
        "original_filename": "Old.pdf",
        "mime_type": "application/pdf",
        "byte_size": 1,
        "sha256": "a" * 64,
    }
    replacement = {
        **old_reference,
        "id": "remap-owned-receipt",
        "name": "Replacement.pdf",
        "receipt_id": "fedcba9876543210fedcba9876543210",
        "original_filename": "Replacement.pdf",
        "sha256": "b" * 64,
    }
    default_storage.set_mixed_use_receipt_references(
        source["id"], [old_reference], expected_source=source
    )
    owner = default_storage.create_transaction(
        **expense_inputs(default_storage), kind="Expense", amount="10"
    )
    default_storage.set_transaction_receipt_references(owner["id"], [replacement])
    refreshed_source = default_storage.get_mixed_use_expense(source["id"])

    with pytest.raises(StorageConflictError, match="already linked"):
        default_storage.remap_mixed_use_receipt(
            source["id"],
            old_file_id=old_reference["id"],
            reference=replacement,
            expected_source=refreshed_source,
        )

    assert (
        default_storage.get_mixed_use_expense(source["id"])["receipt_references"]
        == refreshed_source["receipt_references"]
    )


def test_generic_receipt_setter_rejects_receipts_owned_by_another_transaction(
    default_storage: GoogleSheetsStorage,
) -> None:
    owner = default_storage.create_transaction(
        **expense_inputs(default_storage), kind="Expense", amount="10"
    )
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    reference = {"id": "setterowned01", "name": "Receipt.pdf"}
    default_storage.set_transaction_receipt_references(owner["id"], [reference])

    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.set_transaction_receipt_references(
            source["linked_transaction_id"], [reference]
        )


@pytest.mark.parametrize(
    "operation",
    [
        "set_transaction_receipt_references",
        "link_transaction_receipt",
        "remap_transaction_receipt",
        "unlink_transaction_receipt",
    ],
)
def test_every_generic_receipt_mutation_rejects_mixed_use_projection(
    default_storage: GoogleSheetsStorage, operation: str
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
    )
    transaction_id = source["linked_transaction_id"]
    reference = {"id": "generic-guard-receipt", "name": "Receipt.pdf"}

    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        if operation == "set_transaction_receipt_references":
            default_storage.set_transaction_receipt_references(
                transaction_id, [reference]
            )
        elif operation == "link_transaction_receipt":
            default_storage.link_transaction_receipt(
                transaction_id, reference=reference
            )
        elif operation == "remap_transaction_receipt":
            default_storage.remap_transaction_receipt(
                transaction_id, old_file_id="old-receipt", reference=reference
            )
        else:
            default_storage.unlink_transaction_receipt(
                transaction_id, file_id="old-receipt"
            )


def test_mixed_use_create_rejects_source_link_mismatch_before_payee_creation(
    default_storage: GoogleSheetsStorage,
) -> None:
    inputs = expense_inputs(default_storage)
    inputs.update(
        payee_id="",
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured use",
        source_id="source-link-mismatch",
        linked_transaction_id="transaction-link-mismatch",
    )
    source = default_storage.create_mixed_use_expense(**inputs)
    payees_before = default_storage.list_payees(active_only=False)
    retry_inputs = {
        **inputs,
        "linked_transaction_id": "different-linked-transaction",
        "new_payee_name": "Should not be created",
    }

    with pytest.raises(StorageConflictError, match="another transaction ID"):
        default_storage.create_mixed_use_expense(**retry_inputs)

    assert default_storage.list_payees(active_only=False) == payees_before
    assert (
        default_storage.get_mixed_use_expense(source["id"])["linked_transaction_id"]
        == "transaction-link-mismatch"
    )


def test_mixed_use_projection_rejects_destination_account(
    default_storage: GoogleSheetsStorage,
) -> None:
    source = default_storage.create_mixed_use_expense(
        **expense_inputs(default_storage),
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
        **expense_inputs(default_storage),
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Measured business use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    headers = default_storage._headers("Transactions")
    transaction_sheet.rows[1][headers.index("source_type")] = ""
    default_storage._invalidate("Transactions")
    transaction = dict(
        default_storage._rows("Transactions", force_refresh=True)[0].values
    )

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
        **expense_inputs(default_storage),
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
        default_storage.set_transaction_receipt_references(transaction["id"], [])
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
        **expense_inputs(default_storage),
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
