"""Translate the current ledger receipt record into portable document metadata."""

from collections.abc import Mapping
from typing import Any

from tabula_rasa.application.documents import DocumentMetadata, DocumentReference


def document_from_receipt_reference(
    profile_key: str, reference: Mapping[str, Any], *, open_url: str = ""
) -> DocumentReference:
    return DocumentReference(
        profile_key,
        DocumentMetadata(
            str(reference.get("receipt_id", "")), str(reference["name"]),
            str(reference.get("original_filename", "")), str(reference.get("mime_type", "")),
            reference.get("byte_size"), str(reference.get("sha256", "")),
        ),
        str(reference["id"]),
        open_url,
    )


def document_to_receipt_reference(document: DocumentReference) -> dict[str, Any]:
    metadata = document.metadata
    reference: dict[str, Any] = {"id": document.storage_key, "name": metadata.stored_filename}
    # Canonical SQL identities also exist for historical documents whose
    # integrity is unknown. The frozen cell format can represent those only
    # as legacy references; never manufacture a verified rich reference.
    if metadata.document_id and metadata.sha256:
        reference.update({
            "receipt_id": metadata.document_id, "original_filename": metadata.original_filename,
            "mime_type": metadata.mime_type, "byte_size": metadata.byte_size, "sha256": metadata.sha256,
        })
    return reference
