"""Current document byte adapter; the existing Drive client owns reliability."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from tabula_rasa.application.documents import (
    DocumentError, DocumentMetadata, DocumentReference, DocumentUpload, ReceiptInventory,
)
from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.receipt_manifest import ReceiptManifestError, receipt_reference_from_drive_file


def document_from_receipt_reference(profile_key: str, reference: Mapping[str, Any]) -> DocumentReference:
    """Translate the current workbook format; legacy names remain readable."""
    return DocumentReference(
        profile_key,
        DocumentMetadata(
            str(reference.get("receipt_id", "")), str(reference["name"]),
            str(reference.get("original_filename", "")), str(reference.get("mime_type", "")),
            reference.get("byte_size"), str(reference.get("sha256", "")),
        ),
        str(reference["id"]),
        f"https://drive.google.com/open?id={reference['id']}",
    )


def document_to_receipt_reference(document: DocumentReference) -> dict[str, Any]:
    """Provider locator stays in this compatibility format adapter."""
    metadata = document.metadata
    reference: dict[str, Any] = {"id": document.storage_key, "name": metadata.stored_filename}
    if metadata.document_id:
        reference.update({
            "receipt_id": metadata.document_id, "original_filename": metadata.original_filename,
            "mime_type": metadata.mime_type, "byte_size": metadata.byte_size, "sha256": metadata.sha256,
        })
    return reference


class GoogleDriveDocumentStore:
    """Lazy, immutable profile/folder binding over the current Drive client.

    Client construction/auth/folders stay infrastructure concerns. Receipt
    identity reconciliation, filename preservation, and caches are delegated
    directly to the existing client rather than duplicated here.
    """

    def __init__(self, profile_key: str, folder_id: str, client_factory: Callable[[], Any]) -> None:
        self.profile_key = profile_key
        self.folder_id = folder_id
        self._client_factory = client_factory

    @property
    def scope_key(self) -> str:
        return self.folder_id

    def _client(self, profile_key: str) -> Any:
        if profile_key != self.profile_key:
            raise DocumentError("Document storage belongs to a different business profile.")
        if not self.folder_id:
            raise DocumentError("Google Drive receipt storage is not configured for this profile.")
        try:
            return self._client_factory()
        except GoogleDriveError as error:
            raise DocumentError(str(error)) from error

    def upload(self, profile_key: str, upload: DocumentUpload) -> DocumentReference:
        try:
            uploaded = self._client(profile_key).upload_receipt(
                profile_key=profile_key, folder_id=self.folder_id,
                original_name=upload.original_filename, content=upload.content,
                mime_type=upload.mime_type, receipt_id=upload.document_id,
            )
            reference = receipt_reference_from_drive_file(uploaded)
        except (GoogleDriveError, ReceiptManifestError) as error:
            raise DocumentError(str(error)) from error
        return document_from_receipt_reference(profile_key, reference)

    def inventory(self, profile_key: str, *, fresh: bool = False) -> ReceiptInventory:
        try:
            files = self._client(profile_key).list_profile_receipts(
                profile_key=profile_key, folder_id=self.folder_id, _force_refresh=fresh,
            )
        except GoogleDriveError as error:
            raise DocumentError(str(error)) from error
        documents: list[DocumentReference] = []
        missing_integrity: list[str] = []
        for file in files:
            properties = file.get("appProperties")
            # Queries already scope this inventory; reject conflicting response
            # metadata too without weakening older client fixtures/responses.
            if isinstance(properties, Mapping) and properties.get("tabulaRasaProfile", profile_key) != profile_key:
                raise DocumentError("Receipt inventory contains a file from another profile.")
            try:
                reference = receipt_reference_from_drive_file(file)
            except ReceiptManifestError:
                missing_integrity.append(str(file.get("id", "")))
            else:
                documents.append(document_from_receipt_reference(profile_key, reference))
        return ReceiptInventory(tuple(documents), tuple(missing_integrity))

    def metadata(self, profile_key: str, storage_key: str) -> DocumentReference:
        matches = [item for item in self.inventory(profile_key, fresh=True).documents if item.storage_key == storage_key]
        if len(matches) != 1:
            raise DocumentError("The receipt is not in this profile's selected receipt folder.")
        return matches[0]

    def fetch(self, profile_key: str, storage_key: str) -> bytes:
        document = self.metadata(profile_key, storage_key)
        try:
            content = self._client(profile_key).download_file(storage_key)
        except GoogleDriveError as error:
            raise DocumentError(str(error)) from error
        if len(content) != document.metadata.byte_size or hashlib.sha256(content).hexdigest() != document.metadata.sha256:
            raise DocumentError("The receipt content failed checksum validation.")
        return content

    def delete(self, profile_key: str, storage_key: str) -> None:
        self.metadata(profile_key, storage_key)
        try:
            self._client(profile_key).delete_file(storage_key)
        except GoogleDriveError as error:
            raise DocumentError(str(error)) from error
