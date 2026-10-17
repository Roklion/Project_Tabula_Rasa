"""Explicit byte copy/verification; no automatic migration or source retirement."""
from dataclasses import dataclass
import hashlib

from .documents import DocumentUpload, DocumentValidationError


def verify_document(document, content):
    metadata = document.metadata
    if (metadata.byte_size != len(content) or not metadata.sha256
            or hashlib.sha256(content).hexdigest() != metadata.sha256):
        raise DocumentValidationError('Receipt bytes do not match retained metadata. Stop and inspect recovery copies.')


@dataclass(frozen=True)
class CopyResult:
    verified: int
    promoted: bool
    dry_run: bool


def copy_entity_documents(repository, source, target, *, dry_run=True, promote=False, connection_binding=None,
                          recovery_snapshot=False, progress=None):
    """Freeze writers first. Deterministic destination identities are checkpoints.

    A failed copy keeps all source locations authoritative. Restart reuses exact
    target bytes. Promotion compares the whole fresh canonical metadata set in
    one SQL transaction and preserves old locators and every bookkeeping link.
    Neither this workflow nor the adapters retire originals or old versions.
    """
    entity_id = repository.entity_id
    if source.scope_key == target.scope_key or not source.scope_key or not target.scope_key:
        raise DocumentValidationError('Copy requires distinct explicit source and destination bindings.')
    documents = repository.retained_documents()
    if not recovery_snapshot:
        source_inventory = source.inventory(entity_id, fresh=True)
        registered = {item.storage_key for item in documents}
        if source_inventory.unverified_storage_keys or any(item.storage_key not in registered for item in source_inventory.documents):
            raise DocumentValidationError('Reconcile unregistered or unverified source receipts before copying this entity.')
    copied = []
    for count, document in enumerate(documents, 1):
        if document.profile_key != entity_id:
            raise DocumentValidationError('Receipt copy returned a different business entity.')
        content = source.fetch(entity_id, document.storage_key)
        verify_document(document, content)
        if dry_run:
            if progress is not None:
                progress({'stage': 'source_verified', 'verified': count, 'total': len(documents)})
            continue
        upload = DocumentUpload(document.metadata.document_id, document.metadata.original_filename,
                                document.metadata.mime_type, document.metadata.sha256, content,
                                stored_filename=document.metadata.stored_filename)
        destination = target.upload(entity_id, upload)
        if destination.profile_key != entity_id or destination.metadata != document.metadata:
            raise DocumentValidationError('Copied receipt metadata differs from the canonical document.')
        # Migration is an explicit verification operation, not runtime post-PUT reconciliation.
        if target.metadata(entity_id, destination.storage_key) != destination:
            raise DocumentValidationError('Copied receipt location could not be verified.')
        target_bytes = target.fetch(entity_id, destination.storage_key)
        verify_document(destination, target_bytes)
        if target_bytes != content:
            raise DocumentValidationError('Copied receipt bytes differ from the original.')
        copied.append(destination)
        if progress is not None:
            progress({'stage': 'target_verified', 'verified': count, 'total': len(documents)})
    if promote and not dry_run:
        repository.promote_locations(documents, tuple(copied), target_kind=target.store_kind,
                                     target_scope=target.scope_key, connection_binding=connection_binding)
    return CopyResult(len(documents), promote and not dry_run, dry_run)


def verify_entity_documents(repository, store):
    """Read-only verifier against retained DB metadata in an isolated binding."""
    documents = repository.retained_documents()
    for document in documents:
        if document.profile_key != repository.entity_id:
            raise DocumentValidationError('Recovery returned a different business entity.')
        actual = store.metadata(repository.entity_id, document.storage_key)
        if actual != document:
            raise DocumentValidationError('Restored receipt metadata or provider version differs.')
        verify_document(document, store.fetch(repository.entity_id, document.storage_key))
    return len(documents)
