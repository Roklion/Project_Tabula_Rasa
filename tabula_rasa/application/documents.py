"""Receipt use cases and document ports, independent of storage providers."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

MAX_RECEIPT_REFERENCES = 100
MAX_RECEIPT_BYTES = 20 * 1024 * 1024
MAX_RECEIPT_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024
RECEIPT_UPLOAD_TYPES = ("pdf", "png", "jpg", "jpeg", "webp", "heic")
UPLOADED_NOT_LINKED_MESSAGE = (
    "The receipt is uploaded but could not be linked to the ledger. "
    "If it is not already linked, the file remains available from "
    "Unreferenced receipts."
)


class DocumentError(RuntimeError):
    """Safe, actionable document failure; never includes file contents."""


class DocumentValidationError(DocumentError, ValueError):
    """An upload or document association is outside its supported contract."""


@dataclass(frozen=True)
class DocumentMetadata:
    """Portable identity and provenance, separate from a provider's locator.

    Existing references may lack integrity metadata until explicit backfill;
    a new document always has all of these fields.
    """

    document_id: str
    stored_filename: str
    original_filename: str = ""
    mime_type: str = ""
    byte_size: int | None = None
    sha256: str = ""


@dataclass(frozen=True)
class DocumentReference:
    """One profile's document metadata and opaque storage address."""

    profile_key: str
    metadata: DocumentMetadata
    storage_key: str
    open_url: str = ""


@dataclass(frozen=True)
class ReceiptAssociation:
    transaction_id: str
    document: DocumentReference


@dataclass(frozen=True)
class ReceiptInventory:
    documents: tuple[DocumentReference, ...]
    unverified_storage_keys: tuple[str, ...] = ()

    @property
    def needing_integrity(self) -> int:
        return len(self.unverified_storage_keys)


@dataclass(frozen=True)
class DocumentUpload:
    """A stable identity is prepared before a remote create can occur."""

    document_id: str
    original_filename: str
    mime_type: str
    sha256: str
    content: bytes = field(repr=False)


class DocumentStore(Protocol):
    """Profile-scoped document bytes; adapters own provider retry semantics.

    Upload must reuse its stable identity after an uncertain response, perform
    one bounded readback, and retry at most once when absence is established.
    Failed metadata linking never authorizes deletion. Fetch/delete/metadata
    must verify selected-profile ownership before accessing the opaque locator.
    """

    @property
    def scope_key(self) -> str:
        """Opaque configuration identity; empty when storage is unconfigured."""
        ...

    def upload(self, profile_key: str, upload: DocumentUpload) -> DocumentReference: ...

    def inventory(self, profile_key: str, *, fresh: bool = False) -> ReceiptInventory: ...

    def metadata(self, profile_key: str, storage_key: str) -> DocumentReference: ...

    def fetch(self, profile_key: str, storage_key: str) -> bytes: ...

    def delete(self, profile_key: str, storage_key: str) -> None:
        """Explicit destructive operation, never invoked by receipt unlink."""
        ...


class ReceiptRepository(Protocol):
    """Ledger metadata and relationships, distinct from document bytes.

    Mutation adapters own fresh-record, ownership, duplicate, and stale-write
    checks plus cache invalidation and bounded uncertain-write reconciliation.
    """

    def associations(self, profile_key: str, *, fresh: bool = False) -> Sequence[ReceiptAssociation]: ...

    def references(self, profile_key: str, transaction_id: str, *, fresh: bool = False) -> Sequence[DocumentReference]: ...

    def link(self, profile_key: str, transaction_id: str, document: DocumentReference) -> None: ...

    def unlink(self, profile_key: str, transaction_id: str, storage_key: str) -> None: ...


def validate_receipt_upload(original_name: str, content: bytes) -> None:
    """The supported file contract belongs to the receipt use case."""
    filename = str(original_name or "").strip()
    if not filename or not filename.casefold().endswith(tuple(f".{item}" for item in RECEIPT_UPLOAD_TYPES)):
        raise DocumentValidationError("Receipt files must be PDF, PNG, JPG, JPEG, WEBP, or HEIC.")
    if not content or len(content) > MAX_RECEIPT_BYTES:
        raise DocumentValidationError("Receipt files must be non-empty and no larger than 20 MB.")


def prepare_receipt_uploads(
    uploaded_files: Sequence[DocumentUpload],
    *,
    existing_reference_count: int = 0,
    max_upload_total_bytes: int = MAX_RECEIPT_UPLOAD_TOTAL_BYTES,
) -> list[dict[str, Any]]:
    """Copy all selected files and validate the entire batch before ledger save."""
    if existing_reference_count < 0:
        raise ValueError("Existing receipt reference count cannot be negative")
    if existing_reference_count + len(uploaded_files) > MAX_RECEIPT_REFERENCES:
        raise DocumentValidationError(
            "A transaction can reference no more than 100 receipts. "
            "Remove an existing receipt reference or select fewer files."
        )
    prepared: list[dict[str, Any]] = []
    total_bytes = 0
    for index, uploaded_file in enumerate(uploaded_files):
        name = uploaded_file.original_filename
        content = uploaded_file.content
        total_bytes += len(content)
        if total_bytes > max_upload_total_bytes:
            raise DocumentValidationError("Selected receipt files cannot exceed 200 MB total. Select fewer or smaller files.")
        validate_receipt_upload(name, content)
        sha256 = hashlib.sha256(content).hexdigest()
        prepared.append({
            "key": f"{index}:{sha256}", "receipt_id": uploaded_file.document_id or secrets.token_hex(16),
            "sha256": sha256, "original_name": name,
            "mime_type": uploaded_file.mime_type or "application/octet-stream",
            "content": content, "reference": None, "error": "",
        })
    return prepared


Reference = TypeVar("Reference")


def process_pending_receipts(
    workflow: MutableMapping[str, Any],
    *,
    upload_receipt: Callable[[Mapping[str, Any]], Reference],
    link_receipt: Callable[[Reference], object],
) -> None:
    """The shared Add/Edit recovery loop retains only unresolved work.

    Provider adapters reconcile uncertainty; this orchestration never reuploads
    a confirmed reference and never attempts rollback of stored bytes.
    """
    unresolved: list[dict[str, Any]] = []
    linked_count = int(workflow.get("linked_count", 0))
    for pending in workflow.get("receipts", []):
        if not isinstance(pending, Mapping):
            continue
        receipt = dict(pending)
        reference = receipt.get("reference")
        if reference is None:
            try:
                reference = upload_receipt(receipt)
            except Exception as error:  # noqa: BLE001 - keep resumable input
                receipt["error"] = str(error)
                unresolved.append(receipt)
                continue
            receipt["reference"] = reference
            receipt["content"] = b""
        try:
            link_receipt(reference)
        except Exception as error:  # noqa: BLE001 - stored bytes remain recoverable
            receipt["error"] = f"{UPLOADED_NOT_LINKED_MESSAGE} {error}"
            unresolved.append(receipt)
        else:
            linked_count += 1
    workflow["linked_count"] = linked_count
    workflow["receipts"] = unresolved


class ReceiptService:
    """Receipt upload/link/unlink and recovery for an explicitly selected profile."""

    def __init__(self, profile_key: str, repository: ReceiptRepository, documents: DocumentStore) -> None:
        if not profile_key.strip():
            raise ValueError("Receipt services require a selected business profile.")
        self.profile_key = profile_key
        self.repository = repository
        self.documents = documents

    @property
    def document_scope(self) -> str:
        return self.documents.scope_key

    def with_repository(self, repository: ReceiptRepository) -> ReceiptService:
        """Use the same byte store with a source-aware bookkeeping adapter."""
        return ReceiptService(self.profile_key, repository, self.documents)

    def references(self, transaction_id: str, *, fresh: bool = False) -> tuple[DocumentReference, ...]:
        references = tuple(self.repository.references(self.profile_key, transaction_id, fresh=fresh))
        for document in references:
            self._check_profile(document)
        return references

    def _check_profile(self, document: DocumentReference) -> None:
        if document.profile_key != self.profile_key:
            raise DocumentValidationError("The receipt belongs to a different business profile.")

    def unreferenced(self) -> ReceiptInventory:
        associations = self.repository.associations(self.profile_key)
        for association in associations:
            self._check_profile(association.document)
        referenced = {item.document.storage_key for item in associations}
        inventory = self.documents.inventory(self.profile_key)
        for document in inventory.documents:
            self._check_profile(document)
        return ReceiptInventory(
            tuple(item for item in inventory.documents if item.storage_key not in referenced),
            tuple(key for key in inventory.unverified_storage_keys if key not in referenced),
        )

    def link(self, transaction_id: str, document: DocumentReference) -> None:
        self._check_profile(document)
        self.repository.link(self.profile_key, transaction_id, document)

    def unlink(self, transaction_id: str, storage_key: str) -> None:
        # Unlink has no access to DocumentStore.delete; bytes remain recoverable.
        self.repository.unlink(self.profile_key, transaction_id, storage_key)

    def process_recovery(self, workflow: MutableMapping[str, Any]) -> None:
        transaction_id = str(workflow["transaction_id"])

        def upload(receipt: Mapping[str, Any]) -> DocumentReference:
            content = bytes(receipt["content"])
            validate_receipt_upload(str(receipt["original_name"]), content)
            sha256 = hashlib.sha256(content).hexdigest()
            if sha256 != str(receipt["sha256"]):
                raise DocumentValidationError("Prepared receipt content failed checksum validation.")
            document = self.documents.upload(self.profile_key, DocumentUpload(
                str(receipt["receipt_id"]), str(receipt["original_name"]),
                str(receipt["mime_type"]), sha256, content,
            ))
            self._check_profile(document)
            return document

        process_pending_receipts(workflow, upload_receipt=upload, link_receipt=lambda document: self.link(transaction_id, document))
