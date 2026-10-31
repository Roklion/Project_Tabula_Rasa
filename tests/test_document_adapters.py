from __future__ import annotations

import hashlib
import mimetypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.application.documents import DocumentError, DocumentUpload, ReceiptService, validate_receipt_upload
from tabula_rasa.infrastructure.google_drive_documents import (
    GoogleDriveDocumentStore, document_to_receipt_reference,
)
from tabula_rasa.application.receipt_context import MixedUseReceiptRepository, receipt_service_for_context
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file
from tests.drive_fixtures import receipt_drive_file
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


@pytest.mark.parametrize(('filename', 'canonical'), [
    ('CON.pdf', '_CON.pdf'), ('invoice?.pdf', 'invoice_.pdf'),
    ('.pdf', 'receipt.pdf'), (' ... .JPEG', 'receipt.JPEG'),
    ('a' * 200 + '.pdf', 'a' * 176 + '.pdf'),
    ('a' * 200 + '.JPEG', 'a' * 175 + '.JPEG'),
])
def test_service_reconciles_drive_upload_with_canonical_filename(filename, canonical):
    client = Mock()
    stored = receipt_drive_file(
        'receiptfile12345', canonical, profile_key='north', receipt_id='a' * 32,
        sha256=hashlib.sha256(b'receipt').hexdigest(), original_name=canonical, size=7,
    )
    stored['mimeType'] = mimetypes.guess_type(canonical)[0]
    client.list_profile_receipts.side_effect = [[], [stored]]
    def uncertain_upload(**kwargs):
        # The real Drive upload boundary revalidates the canonical filename.
        validate_receipt_upload(kwargs['original_name'], kwargs['content'])
        raise DocumentError('Upload status is uncertain')

    client.upload_receipt.side_effect = uncertain_upload
    service = ReceiptService('north', FakeReceiptRepository(), GoogleDriveDocumentStore(
        'north', 'folder123456', lambda: client,
    ))
    with pytest.raises(DocumentError, match='uncertain'):
        service.upload('a' * 32, filename, b'receipt')
    confirmed = service.upload('a' * 32, filename, b'receipt')
    assert confirmed.metadata.original_filename == canonical
    client.upload_receipt.assert_called_once_with(
        profile_key='north', folder_id='folder123456', original_name=canonical,
        content=b'receipt', mime_type=mimetypes.guess_type(canonical)[0], receipt_id='a' * 32,
    )


def test_drive_fetch_and_delete_require_current_profile_folder_membership_and_checksum():
    from tabula_rasa.google_drive import GoogleDriveAccessError
    client = Mock()
    client.list_profile_receipts.return_value = [drive_file()]
    def metadata(**kwargs):
        if kwargs['file_id'] != 'receiptfile12345':
            raise GoogleDriveAccessError("The receipt is not in this profile's selected receipt folder.")
        return drive_file()
    client.receipt_file.side_effect = metadata
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
    client.list_profile_receipts.assert_not_called()


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


def test_context_service_preserves_non_google_adapters_and_rejects_mismatched_profile_before_io():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    services = SimpleNamespace(receipts=ReceiptService("north", repository, store))
    context = SimpleNamespace(profile_key="north", services=services)
    assert receipt_service_for_context(context) is services.receipts
    context.profile_key = "south"
    with pytest.raises(DocumentError, match="different business profile"):
        receipt_service_for_context(context)
    assert store.upload_calls == 0
    assert repository.records[("north", "txn")] == []


def test_mixed_use_receipt_repository_keeps_document_store_and_source_expected_record():
    ordinary_repository, source_service = FakeReceiptRepository(), Mock()
    store = FakeDocumentStore()
    expected = {"id": "source", "receipt_references": ""}
    refreshed_references = '[{"id":"object/a","name":"original.pdf"}]'
    source_service.get.return_value = {"id": "source", "receipt_references": refreshed_references}
    on_source_changed = Mock()
    service = ReceiptService("north", ordinary_repository, store)
    rebound = service.with_repository(MixedUseReceiptRepository(
        ordinary_repository, source_service, "source", expected, on_source_changed,
    ))
    assert rebound.documents is store
    document = store.upload("north", DocumentUpload("a" * 32, "original.pdf", "application/pdf", hashlib.sha256(b"receipt").hexdigest(), b"receipt"))
    rebound.link("txn", document)
    source_service.link_receipt.assert_called_once_with(
        "source", reference=document_to_receipt_reference(document), expected_source=expected,
    )
    updated_expected = {**expected, "receipt_references": refreshed_references}
    on_source_changed.assert_called_once_with(updated_expected)
    assert ordinary_repository.records[("north", "txn")] == []
    rebound.unlink("txn", document.storage_key)
    source_service.unlink_receipt.assert_called_once_with(
        "source", file_id=document.storage_key, expected_source=updated_expected,
    )
    assert store.delete_calls == 0
