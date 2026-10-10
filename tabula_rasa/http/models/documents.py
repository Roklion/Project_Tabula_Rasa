from .common import DTO


class Document(DTO):
    id: str
    filename: str
    mime_type: str
    byte_size: int | None
    sha256: str


class DocumentList(DTO):
    items: list[Document]
    needing_integrity: int = 0


class DocumentLink(DTO):
    document_id: str


def document_response(reference):
    metadata = reference.metadata
    return Document(id=metadata.document_id, filename=metadata.original_filename or metadata.stored_filename,
                    mime_type=metadata.mime_type, byte_size=metadata.byte_size, sha256=metadata.sha256)
