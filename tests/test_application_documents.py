from __future__ import annotations

import hashlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from tabula_rasa.application.documents import (
    DocumentError, DocumentMetadata, DocumentReference, DocumentUpload,
    DocumentValidationError, ReceiptAssociation, ReceiptInventory, ReceiptService,
    prepare_receipt_uploads,
)


class FakeDocumentStore:
    """Opaque object keys exercise services without Drive IDs or API dictionaries."""

    scope_key = "test-objects"

    def __init__(self) -> None:
        self.files: dict[tuple[str, str], DocumentReference] = {}
        self.contents: dict[tuple[str, str], bytes] = {}
        self.upload_calls = 0
        self.delete_calls = 0
        self.fail_after_create = False

    def upload(self, profile_key, upload):
        self.upload_calls += 1
        key = (profile_key, upload.document_id)
        document = self.files.setdefault(key, DocumentReference(
            profile_key,
            DocumentMetadata(upload.document_id, upload.original_filename, upload.original_filename, upload.mime_type, len(upload.content), upload.sha256),
            f"object/{upload.document_id}", "https://objects.example.test/receipt",
        ))
        self.contents[key] = upload.content
        if self.fail_after_create:
            self.fail_after_create = False
            raise DocumentError("Upload status remains uncertain; inspect the receipt inventory.")
        return document

    def inventory(self, profile_key, *, fresh=False):
        return ReceiptInventory(tuple(value for (profile, _), value in self.files.items() if profile == profile_key))

    def metadata(self, profile_key, storage_key):
        return next(value for value in self.inventory(profile_key).documents if value.storage_key == storage_key)

    def fetch(self, profile_key, storage_key):
        reference = self.metadata(profile_key, storage_key)
        return self.contents[(profile_key, reference.metadata.document_id)]

    def delete(self, profile_key, storage_key):
        self.delete_calls += 1
        document = self.metadata(profile_key, storage_key)
        del self.files[(profile_key, document.metadata.document_id)]


class FakeReceiptRepository:
    def __init__(self):
        self.records = {("north", "txn"): [], ("south", "txn"): []}
        self.fail_link = False
        self.fail_unlink = False
        self.reads = []

    def references(self, profile_key, transaction_id, *, fresh=False):
        self.reads.append((profile_key, transaction_id, fresh))
        return tuple(self.records[(profile_key, transaction_id)])

    def associations(self, profile_key, *, fresh=False):
        return tuple(ReceiptAssociation(transaction, document) for (profile, transaction), documents in self.records.items() if profile == profile_key for document in documents)

    def link(self, profile_key, transaction_id, document):
        if self.fail_link:
            self.fail_link = False
            raise DocumentError("Ledger metadata is temporarily unavailable.")
        records = self.records[(profile_key, transaction_id)]
        if document not in records:
            records.append(document)

    def unlink(self, profile_key, transaction_id, storage_key):
        if self.fail_unlink:
            raise DocumentError("Ledger metadata is temporarily unavailable.")
        self.records[(profile_key, transaction_id)] = [item for item in self.records[(profile_key, transaction_id)] if item.storage_key != storage_key]


def test_export_inventory_resolves_two_profiles_once_and_rejects_foreign_reference_before_fetch():
    from unittest.mock import Mock
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    north, south = (ReceiptService(profile, repository, store) for profile in ('north', 'south'))
    a = north.upload('a' * 32, 'north.pdf', b'north')
    b = south.upload('a' * 32, 'south.pdf', b'south')
    repository.link('north', 'txn', a)
    store.inventory = Mock(wraps=store.inventory)
    assert north.export_inventory().documents == (a,)
    assert south.export_inventory().documents == (b,)
    assert store.inventory.call_count == 2
    store.fetch = Mock(wraps=store.fetch)
    with pytest.raises(DocumentValidationError, match='different business profile'):
        north.download_reference(b)
    store.fetch.assert_not_called()
    assert north.download_reference(a)[1] == b'north'
    assert south.download_reference(b)[1] == b'south'


def prepared(*, identity="a" * 32, name="receipt.pdf", content=b"receipt"):
    return prepare_receipt_uploads([DocumentUpload(identity, name, "application/pdf", hashlib.sha256(content).hexdigest(), content)])


@pytest.mark.parametrize('linked', [False, True])
def test_portable_upload_identity_reuses_confirmed_content_and_rejects_conflicts(linked):
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService('north', repository, store)
    identity = 'a' * 32
    first = service.upload(identity, 'receipt.pdf', b'original')
    if linked:
        service.link('txn', first)
    assert service.upload(identity, 'receipt.pdf', b'original') == first
    for filename, content in [('receipt.pdf', b'different'), ('changed.pdf', b'original')]:
        with pytest.raises(DocumentValidationError, match='identity is already used'):
            service.upload(identity, filename, content)
    assert store.upload_calls == 1
    assert service.download(identity)[1] == b'original'
    # Portable identity uniqueness remains scoped to each selected profile.
    south = ReceiptService('south', repository, store)
    other = south.upload(identity, 'receipt.pdf', b'other profile')
    assert other.profile_key == 'south' and south.download(identity)[1] == b'other profile'
    assert service.download(identity)[1] == b'original'


def test_portable_upload_reconciles_uncertain_create_and_fails_closed_on_inventory_error():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService('north', repository, store)
    identity = 'a' * 32
    store.fail_after_create = True
    with pytest.raises(DocumentError, match='uncertain'):
        service.upload(identity, 'receipt.pdf', b'original')
    with patch.object(store, 'inventory', wraps=store.inventory) as inventory:
        assert service.upload(identity, 'receipt.pdf', b'original').metadata.document_id == identity
        inventory.assert_called_once_with('north', fresh=True)
    assert store.upload_calls == 1
    with patch.object(store, 'inventory', side_effect=DocumentError('Inventory unavailable')):
        with pytest.raises(DocumentError, match='Inventory unavailable'):
            service.upload('b' * 32, 'receipt.pdf', b'new')
    assert store.upload_calls == 1


def test_receipt_link_unlink_and_unreferenced_inventory_use_neutral_adapters():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService("north", repository, store)
    workflow = {"transaction_id": "txn", "receipts": prepared()}
    service.process_recovery(workflow)
    document, = service.references("txn", fresh=True)
    assert workflow == {"transaction_id": "txn", "receipts": [], "linked_count": 1}
    assert document.metadata.document_id == "a" * 32
    assert document.storage_key == "object/" + "a" * 32
    assert store.fetch("north", document.storage_key) == b"receipt"
    assert service.unreferenced().documents == ()
    assert repository.reads == [("north", "txn", True)]
    service.unlink("txn", document.storage_key)
    assert service.references("txn") == ()
    assert service.unreferenced().documents == (document,)
    assert store.delete_calls == 0


def test_link_failure_retains_confirmed_document_then_retries_without_upload():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService("north", repository, store)
    repository.fail_link = True
    workflow = {"transaction_id": "txn", "receipts": prepared()}
    service.process_recovery(workflow)
    pending, = workflow["receipts"]
    assert pending["content"] == b""
    assert isinstance(pending["reference"], DocumentReference)
    assert "Unreferenced receipts" in pending["error"]
    assert service.unreferenced().documents == (pending["reference"],)
    service.process_recovery(workflow)
    assert store.upload_calls == 1
    assert store.delete_calls == 0
    assert workflow["receipts"] == []
    assert workflow["linked_count"] == 1


def test_uncertain_upload_preserves_identity_and_never_rolls_back_bytes():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService("north", repository, store)
    store.fail_after_create = True
    workflow = {"transaction_id": "txn", "receipts": prepared()}
    service.process_recovery(workflow)
    assert len(store.files) == 1
    assert workflow["receipts"][0]["reference"] is None
    assert workflow["receipts"][0]["content"] == b"receipt"
    service.process_recovery(workflow)
    assert len(store.files) == 1
    assert len(service.references("txn")) == 1
    assert store.delete_calls == 0


def test_two_profiles_share_fake_adapters_without_sharing_documents_or_links():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    north, south = (ReceiptService(profile, repository, store) for profile in ("north", "south"))
    north.process_recovery({"transaction_id": "txn", "receipts": prepared()})
    north_document, = north.references("txn")
    assert south.references("txn") == ()
    assert south.unreferenced().documents == ()
    with pytest.raises(DocumentValidationError, match="different business profile"):
        south.link("txn", north_document)
    south.process_recovery({"transaction_id": "txn", "receipts": prepared(content=b"south")})
    south_document, = south.references("txn")
    assert south_document.storage_key == north_document.storage_key
    assert south_document.metadata.sha256 != north_document.metadata.sha256
    north.unlink("txn", north_document.storage_key)
    assert south.references("txn") == (south_document,)
    assert len(store.files) == 2


def test_partial_batch_keeps_other_successful_links_and_failed_unlink_keeps_metadata():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService("north", repository, store)
    repository.fail_link = True
    workflow = {"transaction_id": "txn", "receipts": prepared() + prepared(identity="b" * 32)}
    service.process_recovery(workflow)
    assert workflow["linked_count"] == 1
    assert len(workflow["receipts"]) == 1
    document, = service.references("txn")
    repository.fail_unlink = True
    with pytest.raises(DocumentError, match="unavailable"):
        service.unlink("txn", document.storage_key)
    assert service.references("txn") == (document,)
    assert store.delete_calls == 0


def test_checksum_mismatch_stops_before_upload_and_profile_mismatch_stops_before_link():
    store, repository = FakeDocumentStore(), FakeReceiptRepository()
    service = ReceiptService("north", repository, store)
    invalid = prepared()
    invalid[0]["content"] = b"changed"
    workflow = {"transaction_id": "txn", "receipts": invalid}
    service.process_recovery(workflow)
    assert store.upload_calls == 0
    assert "checksum" in workflow["receipts"][0]["error"]
    document = store.upload("south", DocumentUpload("a" * 32, "receipt.pdf", "application/pdf", hashlib.sha256(b"receipt").hexdigest(), b"receipt"))
    with pytest.raises(DocumentValidationError):
        service.link("txn", replace(document, profile_key="south"))
    assert service.references("txn") == ()


@pytest.mark.parametrize(("name", "content", "message"), [("receipt.txt", b"file", "must be PDF"), ("receipt.pdf", b"", "non-empty")])
def test_batch_validation_precedes_upload_and_has_no_streamlit_file_contract(name, content, message):
    with pytest.raises(DocumentValidationError, match=message):
        prepared(name=name, content=content)
