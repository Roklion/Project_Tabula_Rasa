"""Final reference/import seams preserve domain and fresh adapter behavior."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from tabula_rasa.application.imports import (
    TransactionImportContext,
    TransactionImportService,
)
from tabula_rasa.application.reference_data import CategoryService
from tabula_rasa.errors import StorageConflictError, StorageValidationError


QUICKBOOKS_ROW = {
    "Date": "09/01/2026",
    "Transaction Type": "Expense",
    "Num": "INV-1",
    "Name": "Acme",
    "Memo/Description": "Office supplies",
    "Account": "Checking",
    "Split": "Office",
    "Amount": "-12.50",
}


def test_category_service_normalizes_and_rejects_invalid_domain_inputs():
    repository = Mock()
    service = CategoryService(repository)
    service.create(" Office ", " expense ", parent_id=" parent ")
    repository.create.assert_called_once_with("Office", "Expense", parent_id="parent")
    service.update(" category ", name=" Revised ", kind=" income ", parent_id=None)
    repository.update.assert_called_once_with(
        "category", changes={"name": "Revised", "kind": "Income", "parent_id": ""}
    )
    for operation in (
        lambda: service.create("", "Expense"),
        lambda: service.create("Office", "Unknown"),
        lambda: service.update("category", kind="Unknown"),
        lambda: service.delete(""),
    ):
        with pytest.raises(StorageValidationError):
            operation()
    repository.delete.assert_not_called()


def test_import_preview_is_persistence_free_and_retains_duplicate_and_transfer_rules():
    context = TransactionImportContext(
        accounts=[
            {"id": "checking", "name": "Checking", "active": True},
            {"id": "savings", "name": "Savings", "active": True},
        ],
        categories=[{"id": "office", "name": "Office", "kind": "Expense"}],
        payees=[{"id": "acme", "name": "Ａｃｍｅ"}],
        transactions=[],
    )
    before = deepcopy(context)
    repository = Mock()
    repository.quickbooks_context.return_value = context
    service = TransactionImportService(repository)
    transfer = {
        **QUICKBOOKS_ROW, "Transaction Type": "Transfer", "Split": "Savings"
    }
    invalid = {**QUICKBOOKS_ROW, "Date": "not a date"}
    preview = service.preview_quickbooks([QUICKBOOKS_ROW, QUICKBOOKS_ROW, transfer, invalid])
    assert preview["summary"] == {
        "ready": 2, "duplicates": 1, "Income": 0, "Expense": 1, "Transfer": 1
    }
    assert preview["duplicate_rows"] == [3]
    assert preview["rows"][0]["payee"] == "Ａｃｍｅ"
    assert preview["rows"][1]["to_account_id"] == "savings"
    assert len(preview["errors"]) == 1 and "QuickBooks row 5" in preview["errors"][0]
    assert context == before
    repository.import_quickbooks.assert_not_called()


def test_import_preview_proposes_references_without_writes():
    repository = Mock()
    repository.quickbooks_context.return_value = TransactionImportContext([], [], [], [])
    service = TransactionImportService(repository)
    assert service.preview_quickbooks([QUICKBOOKS_ROW])["errors"]
    preview = service.preview_quickbooks([QUICKBOOKS_ROW], auto_create=True)
    assert preview["errors"] == []
    assert preview["new_accounts"] == ["Checking"]
    assert preview["new_categories"] == [("Office", "Expense")]
    assert preview["new_account_types"] == {"Checking": "Bank"}
    assert preview["new_account_classifications"] == {"Checking": "Asset"}
    repository.import_quickbooks.assert_not_called()


def test_import_commands_propagate_uncertain_or_validation_failure_without_retries():
    repository = Mock()
    repository.import_quickbooks.side_effect = StorageConflictError("Refresh and inspect")
    repository.import_csv.side_effect = StorageValidationError("CSV row 2: invalid")
    service = TransactionImportService(repository)
    with pytest.raises(StorageConflictError, match="Refresh and inspect"):
        service.import_quickbooks([QUICKBOOKS_ROW], auto_create=True)
    with pytest.raises(StorageValidationError, match="CSV row 2"):
        service.import_csv([])
    assert repository.import_quickbooks.call_count == 1
    assert repository.import_csv.call_count == 1
    repository.quickbooks_context.assert_not_called()
