"""Read-only receipt inventory, including legacy metadata; no byte requests."""

from dataclasses import dataclass, field
from collections.abc import Mapping

from tabula_rasa.application.documents import DocumentMetadata, DocumentReference
from tabula_rasa.migration.model import MigrationError
from tabula_rasa.receipt_manifest import receipt_reference_from_drive_file, validate_receipt_reference, ReceiptManifestError
from tabula_rasa.receipt_records import document_from_receipt_reference
from .google_drive_documents import GoogleDriveDocumentStore


@dataclass(frozen=True, repr=False)
class MigrationReceiptInventory:
    documents: tuple[DocumentReference, ...] = field(repr=False)
    timestamps: dict = field(repr=False)
    unverified_storage_keys: tuple[str, ...] = ()


class GoogleDriveMigrationInventory(GoogleDriveDocumentStore):
    def inventory(self, profile_key, *, fresh=False):
        files = self._client(profile_key).list_profile_receipts(
            profile_key=profile_key, folder_id=self.folder_id, _force_refresh=fresh)
        documents, timestamps = [], {}
        for file in files:
            properties = file.get("appProperties")
            if (not isinstance(properties, Mapping) or properties.get("tabulaRasaProfile") != profile_key
                    or properties.get("tabulaRasaKind") != "receipt"
                    or ("parents" in file and self.folder_id not in file["parents"])):
                raise MigrationError("Document inventory ownership is invalid for the selected profile.")
            valid = True
            try:
                if properties.get("tabulaRasaSha256"):
                    reference = receipt_reference_from_drive_file(file)
                    document = document_from_receipt_reference(profile_key, reference)
                else:
                    reference = validate_receipt_reference(
                        {"id": file.get("id"), "name": file.get("name")}, allow_nonportable_legacy_name=True)
                    # Preserve known partial metadata without declaring a checksum.
                    size = file.get("size")
                    size = int(size) if size is not None else None
                    document = DocumentReference(profile_key, DocumentMetadata(
                        str(properties.get("tabulaRasaReceiptId") or ""), reference["name"],
                        str(file.get("description") or properties.get("tabulaRasaOriginalName") or ""),
                        str(file.get("mimeType") or ""), size,
                    ), reference["id"])
            except (ReceiptManifestError, ValueError, TypeError):
                valid = False
            if not valid:
                raise MigrationError("Document inventory metadata is invalid; inspect the selected profile privately.")
            documents.append(DocumentReference(
                document.profile_key, document.metadata, document.storage_key,
                str(file.get("webViewLink") or "https://drive.google.com/open?id=" + document.storage_key)))
            timestamps[document.storage_key] = {
                "created_at": str(file.get("createdTime") or ""),
                "updated_at": str(file.get("modifiedTime") or ""),
            }
        return MigrationReceiptInventory(tuple(documents), timestamps)
