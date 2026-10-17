"""Explicit private byte recovery artifacts; never a live document/ledger backend.

The existing canonical bookkeeping export is the metadata/link manifest. The
small binding record identifies its byte source; files use canonical IDs. No
credentials, alternate metadata model, schema converter or automatic pruning.
"""
import json
import re
from pathlib import Path

from tabula_rasa.application.document_recovery import validate_document_inventory, verify_document
from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.application.documents import DocumentError, DocumentValidationError, ReceiptInventory, MAX_RECEIPT_BYTES
from tabula_rasa.bookkeeping_export.files import read_artifact, write_artifact, write_private_bytes
from tabula_rasa.bookkeeping_export.format import validate_artifact
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository


def _root(path, *, create=False):
    try:
        supplied = Path(path)
        root = supplied.resolve()
        if (supplied.is_symlink() or any((parent / '.git').exists() for parent in (root, *root.parents))
                or not root.parent.is_dir()):
            raise ValueError
        if create and not root.exists():
            root.mkdir(mode=0o700)
        if not root.is_dir():
            raise ValueError
        return root
    except (OSError, RuntimeError, ValueError):
        pass
    raise DocumentValidationError('Use an available private recovery directory outside the repository.')


def _file(root, name):
    path = root / name
    if path.is_symlink() or path.resolve().parent != root:
        raise DocumentValidationError('The receipt archive contains an unsafe file path.')
    return path


def _byte_name(document):
    if not re.fullmatch('[0-9a-f]{32}', document.metadata.document_id):
        raise DocumentValidationError('Backfill portable receipt identities/integrity before byte backup.')
    return document.metadata.document_id + '.bin'


def _read_bytes(root, document):
    try:
        with _file(root, _byte_name(document)).open('rb') as source:
            content = source.read(MAX_RECEIPT_BYTES + 1)
    except OSError:
        pass
    else:
        verify_document(document, content)
        return content
    raise DocumentError('Receipt recovery bytes are missing or unreadable. Inspect the retained archive.')


class DocumentArchive:
    """Read-only historical point, usable only by explicit verifier/copy tooling."""
    def __init__(self, path, entity_id):
        self.root = _root(path)
        try:
            self.artifact = read_artifact(_file(self.root, 'bookkeeping.json'), entity_id=entity_id)
        except ExportError:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise DocumentValidationError('Receipt archive is incomplete, invalid or belongs to a different entity.')
        try:
            with _file(self.root, 'binding.json').open('rb') as stream:
                binding = json.loads(stream.read(4097))
            if (set(binding) != {'format', 'version', 'entity_id', 'store_kind', 'scope_key', 'content_sha256'}
                    or binding['format'] != 'tabula-rasa-receipt-bytes'
                    or type(binding['version']) is not int or binding['version'] != 1
                    or binding['entity_id'] != entity_id or binding['store_kind'] not in {'google_drive', 's3'}
                    or not isinstance(binding['scope_key'], str) or not binding['scope_key']
                    or binding['content_sha256'] != self.artifact['manifest']['content_sha256']):
                raise ValueError
        except (OSError, ValueError, TypeError, KeyError):
            pass
        else:
            self.entity_id, self.store_kind, self.scope_key = entity_id, binding['store_kind'], binding['scope_key']
            mapper = PostgresReceiptRepository(None, entity_id, store_kind=self.store_kind, store_scope_key=self.scope_key)
            self.documents = tuple(mapper.document(row) for row in self.artifact['domains']['documents'])
            self._by_key = {doc.storage_key: doc for doc in self.documents}
            if len(self._by_key) == len(self.documents):
                return
        raise DocumentValidationError('Receipt archive binding or source metadata is invalid.')

    def _scope(self, entity_id):
        if entity_id != self.entity_id:
            raise DocumentValidationError('Receipt archive belongs to a different business entity.')

    def inventory(self, entity_id, *, fresh=False):
        self._scope(entity_id)
        return ReceiptInventory(self.documents)

    def metadata(self, entity_id, storage_key):
        self._scope(entity_id)
        document = self._by_key.get(storage_key)
        if document is None:
            raise DocumentValidationError('The receipt location is outside this recovery point.')
        return document

    def fetch(self, entity_id, storage_key):
        return _read_bytes(self.root, self.metadata(entity_id, storage_key))

    def upload(self, entity_id, upload):
        raise DocumentValidationError('Recovery archives are read-only and cannot serve as live storage.')

    def delete(self, entity_id, storage_key):
        raise DocumentValidationError('Recovery archive retirement requires a separate approved operation.')


def archive_documents(repository, source, path, artifact, *, dry_run=True, progress=None):
    """Freeze writers. Resume exact verified files; publish completion metadata last."""
    entity_id = repository.entity_id
    validate_artifact(artifact, entity_id=entity_id)
    mapper = PostgresReceiptRepository(None, entity_id, store_kind=repository.store_kind,
                                      store_scope_key=repository.store_scope_key)
    documents = tuple(mapper.document(row) for row in artifact['domains']['documents'])
    if documents != repository.retained_documents() or source.scope_key != repository.store_scope_key:
        raise DocumentValidationError('Receipt metadata or source binding changed. Freeze writers and re-plan backup.')
    validate_document_inventory(documents, source, entity_id)
    root = None if dry_run else _root(path, create=True)
    binding = dict(format='tabula-rasa-receipt-bytes', version=1, entity_id=entity_id,
                   store_kind=repository.store_kind, scope_key=source.scope_key,
                   content_sha256=artifact['manifest']['content_sha256'])
    if root is not None:
        binding_path = _file(root, 'binding.json')
        if binding_path.exists():
            try:
                existing = json.loads(binding_path.read_text(encoding='utf-8'))
                same = existing == binding and type(existing.get('version')) is int
            except (OSError, ValueError):
                same = False
            if not same:
                raise DocumentValidationError('This recovery directory belongs to another source point. Use a new generation.')
        else:
            write_artifact(binding_path, binding)
    for count, document in enumerate(documents, 1):
        _byte_name(document)
        content = source.fetch(entity_id, document.storage_key)
        verify_document(document, content)
        if root is not None:
            destination = _file(root, _byte_name(document))
            if destination.exists():
                if _read_bytes(root, document) != content:
                    raise DocumentValidationError('Existing archive bytes differ. Preserve the generation and inspect it.')
            else:
                write_private_bytes(destination, content)
        if progress is not None:
            progress({'stage': 'archive_verified' if root else 'source_verified', 'verified': count, 'total': len(documents)})
    if root is not None:
        # One current snapshot comparison before completion; no remote mutation.
        if repository.retained_documents() != documents:
            raise DocumentValidationError('Receipt metadata changed during backup; the generation remains incomplete.')
        manifest = _file(root, 'bookkeeping.json')
        if not manifest.exists():
            write_artifact(manifest, artifact)
        elif read_artifact(manifest, entity_id=entity_id)['manifest']['content_sha256'] != binding['content_sha256']:
            raise DocumentValidationError('The retained archive manifest belongs to a different recovery point.')
    return {'verified': len(documents), 'archived': not dry_run, 'dry_run': dry_run}
