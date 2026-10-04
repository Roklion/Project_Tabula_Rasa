from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.application.documents import DocumentError, DocumentUpload, ReceiptService
from tabula_rasa.infrastructure.google_drive_documents import (
    GoogleDriveDocumentStore, document_from_receipt_reference, document_to_receipt_reference,
)
from tabula_rasa.infrastructure.google_sheets_receipts import GoogleSheetsReceiptRepository
from tabula_rasa.infrastructure.receipt_context import receipt_service_for_context
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tests.drive_fixtures import receipt_drive_file
from tests.fakes import FakeWorkbook
from tests.test_application_documents import FakeDocumentStore, FakeReceiptRepository


def drive_file(*, profile="north"):
    return receipt_drive_file(
        "receiptfile12345", "receipt.pdf", profile_key=profile,
        receipt_id="a" * 32, sha256=hashlib.sha256(b"receipt").hexdigest(),
        original_name="original.pdf", size=7,
    )


def test_drive_store_is_lazy_reuses_upload_owner_and_converts_provider_details():
    client = Mock()
    client.upload_receipt.return_value = drive_file()
    factory = Mock(return_value=client)
    store = GoogleDriveDocumentStore("north", "folder123456", factory)
    factory.assert_not_called()
    document = store.upload("north", DocumentUpload("a" * 32, "original.pdf", "application/pdf", hashlib.sha256(b"receipt").hexdigest(), b"receipt"))
    client.upload_receipt.assert_called_once_with(
        profile_key="north", folder_id="folder123456", original_name="original.pdf",
        content=b"receipt", mime_type="application/pdf", receipt_id="a" * 32,
    )
    assert document.metadata.document_id == "a" * 32
    assert document.storage_key == "receiptfile12345"
    assert document_to_receipt_reference(document) == receipt_reference_from_drive_file(drive_file())
    with pytest.raises(DocumentError, match="different business profile"):
        store.inventory("south")
    assert factory.call_count == 1


def test_drive_fetch_and_delete_require_current_profile_folder_membership_and_checksum():
    client = Mock()
    client.list_profile_receipts.return_value = [drive_file()]
    client.download_file.return_value = b"receipt"
    store = GoogleDriveDocumentStore("north", "folder123456", lambda: client)
    assert store.fetch("north", "receiptfile12345") == b"receipt"
    client.download_file.return_value = b"changed"
    with pytest.raises(DocumentError, match="checksum"):
        store.fetch("north", "receiptfile12345")
    with pytest.raises(DocumentError, match="selected receipt folder"):
        store.delete("north", "some-other-object")
    client.delete_file.assert_not_called()
    store.delete("north", "receiptfile12345")
    client.delete_file.assert_called_once_with("receiptfile12345")


def test_drive_inventory_rejects_cross_profile_responses_and_retains_integrity_warnings():
    client = Mock()
    store = GoogleDriveDocumentStore("north", "folder123456", lambda: client)
    client.list_profile_receipts.return_value = [drive_file(profile="south")]
    with pytest.raises(DocumentError, match="another profile"):
        store.inventory("north")
    legacy = drive_file()
    del legacy["appProperties"]["tabulaRasaSha256"]
    client.list_profile_receipts.return_value = [legacy]
    inventory = store.inventory("north")
    assert inventory.documents == ()
    assert inventory.needing_integrity == 1
    assert inventory.unverified_storage_keys == ("receiptfile12345",)


def test_sheets_adapter_roundtrips_current_integrity_format_and_unlink_preserves_store():
    storage = GoogleSheetsStorage(FakeWorkbook())
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Sales", "Income")
    transaction = storage.create_transaction(txn_date="2026-10-03", kind="Income", amount=10, account_id=account["id"], category_id=category["id"])
    repository = GoogleSheetsReceiptRepository("north", storage)
    document = document_from_receipt_reference("north", receipt_reference_from_drive_file(drive_file()))
    repository.link("north", transaction["id"], document)
    assert repository.references("north", transaction["id"], fresh=True) == (document,)
    association, = repository.associations("north", fresh=True)
    assert association.transaction_id == transaction["id"]
    assert association.document == document
    repository.link("north", transaction["id"], document)
    assert len(repository.references("north", transaction["id"])) == 1
    with pytest.raises(StorageValidationError, match="different business profile"):
        repository.unlink("south", transaction["id"], document.storage_key)
    repository.unlink("north", transaction["id"], document.storage_key)
    assert repository.references("north", transaction["id"]) == ()


def test_context_bridge_preserves_non_google_adapters_and_rejects_mismatched_profile_before_io():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    services = SimpleNamespace(receipts=ReceiptService("north", repository, store))
    context = SimpleNamespace(profile_key="north", services=services, storage=Mock())
    assert receipt_service_for_context(context) is services.receipts
    context.profile_key = "south"
    with pytest.raises(DocumentError, match="different business profile"):
        receipt_service_for_context(context)
    assert store.upload_calls == 0
    context.storage.link_transaction_receipt.assert_not_called()


def test_context_bridge_rebinds_mixed_use_repository_but_keeps_profile_document_store():
    ordinary_storage, source_storage = Mock(), Mock()
    store = FakeDocumentStore()
    service = ReceiptService("north", GoogleSheetsReceiptRepository("north", ordinary_storage), store)
    context = SimpleNamespace(profile_key="north", services=SimpleNamespace(receipts=service), storage=source_storage)
    rebound = receipt_service_for_context(context)
    assert rebound.documents is store
    document = store.upload("north", DocumentUpload("a" * 32, "original.pdf", "application/pdf", hashlib.sha256(b"receipt").hexdigest(), b"receipt"))
    rebound.link("txn", document)
    source_storage.link_transaction_receipt.assert_called_once()
    ordinary_storage.link_transaction_receipt.assert_not_called()
