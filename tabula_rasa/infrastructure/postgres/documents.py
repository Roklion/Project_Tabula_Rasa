"""Document metadata and logical bookkeeping links; never external byte I/O."""

from dataclasses import replace as replace_document
from collections.abc import Mapping
import json
import re
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text

from tabula_rasa.application.documents import (
    DocumentMetadata, DocumentReference, DocumentValidationError, MAX_RECEIPT_REFERENCES, MAX_RECEIPT_BYTES,
    ReceiptAssociation,
)
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.receipt_manifest import validate_receipt_filename, validate_receipt_reference, ReceiptManifestError
from tabula_rasa.reference_data import clean_text
from .concurrency import check_baseline, lock_aggregates
from .repository import EntityRepository, insert, new_object


def receipt_reference(doc):
    """Compatibility projection for the current Simple Ledger record contract."""
    result = {'id': doc['storage_key'], 'name': doc['stored_filename']}
    if doc['sha256']:
        result.update(receipt_id=doc['id'], original_filename=doc['original_filename'],
                      mime_type=doc['mime_type'], byte_size=doc['byte_size'], sha256=doc['sha256'])
    return result


def write_document_links(connection, scope, column, target, documents):
    """Replace one already-locked target's links, preserving retained instants."""
    if column not in {'entry_id', 'mixed_use_source_id'}:
        raise StorageValidationError('Unsupported document target.')
    if len(documents) > MAX_RECEIPT_REFERENCES or len(documents) != len(set(documents)):
        raise StorageValidationError('A target accepts at most 100 distinct receipts.')
    params = {'scope': scope, 'id': target}
    existing = dict(connection.execute(text(
        f'SELECT document_id,position FROM document_links WHERE entity_id=:scope AND {column}=:id'
    ), params).all())
    for document_id in set(existing) - set(documents):
        connection.execute(text(
            f'DELETE FROM document_links WHERE entity_id=:scope AND {column}=:id AND document_id=:document'
        ), {**params, 'document': document_id})
    reordered = any(existing[document_id] != position for position, document_id in enumerate(documents, 1)
                    if document_id in existing)
    if reordered:
        # The position indexes are immediate; reserve a disjoint temporary range.
        connection.execute(text(
            f'UPDATE document_links SET position=position+:offset WHERE entity_id=:scope AND {column}=:id'
        ), {**params, 'offset': max(existing.values()) + len(documents)})
    for position, document_id in enumerate(documents, 1):
        if document_id in existing:
            if existing[document_id] == position and not reordered:
                continue
            connection.execute(text(
                f'UPDATE document_links SET position=:position WHERE entity_id=:scope AND {column}=:id AND document_id=:document'
            ), {**params, 'document': document_id, 'position': position})
        else:
            insert(connection, 'document_links', {
                'entity_id': scope, column: target, 'document_id': document_id, 'position': position,
            })


def map_legacy_document(entity_id, store_kind, store_scope_key, document):
    """Deterministic missing-ID mapping consumed by explicit migration tooling."""
    if document.profile_key != entity_id:
        raise DocumentValidationError('The receipt belongs to a different business entity.')
    if document.metadata.document_id:
        return document
    payload = json.dumps(['tabula-rasa-document-v1', entity_id, store_kind, store_scope_key,
                          document.storage_key], separators=(',', ':'))
    return replace_document(document, metadata=replace_document(
        document.metadata, document_id=uuid5(NAMESPACE_URL, payload).hex,
    ))


class PostgresReceiptRepository(EntityRepository):
    def __init__(self, database, entity_id, *, store_kind, store_scope_key,
                 source_id=None, expected_source=None):
        super().__init__(database, entity_id)
        self.store_kind = clean_text(store_kind, 'Document store kind', required=True)
        self.store_scope_key = clean_text(store_scope_key, 'Document store scope', required=True)
        self.source_id = source_id
        self.expected_source = expected_source

    def for_mixed_use(self, source_id, *, expected_source):
        """Bind source-aware receipt mutations for #248 without editing its pair."""
        return type(self)(self.database, self.entity_id, store_kind=self.store_kind,
                          store_scope_key=self.store_scope_key,
                          source_id=clean_text(source_id, 'Mixed-use source', required=True),
                          expected_source=expected_source)

    def check_profile(self, profile_key):
        if profile_key != self.entity_id:
            raise DocumentValidationError('Receipt metadata belongs to a different business entity.')

    def document(self, row):
        if row['store_kind'] != self.store_kind or row['store_scope_key'] != self.store_scope_key:
            raise DocumentValidationError('The receipt uses a different document-store binding.')
        return DocumentReference(self.entity_id, DocumentMetadata(
            row['id'], row['stored_filename'], row['original_filename'], row['mime_type'],
            row['byte_size'], row['sha256'] or '',
        ), row['storage_key'], row['open_url'])

    def metadata_values(self, document):
        self.check_profile(document.profile_key)
        metadata = document.metadata
        try:
            if not metadata.sha256 and self.store_kind == 'google_drive':
                validate_receipt_reference(
                    {'id': document.storage_key, 'name': metadata.stored_filename},
                    allow_nonportable_legacy_name=True,
                )
            else:
                validate_receipt_filename(metadata.stored_filename, 'Receipt stored filename')
            validate_receipt_filename(metadata.original_filename, 'Receipt original filename', required=False)
        except ReceiptManifestError:
            raise DocumentValidationError('Receipt filename metadata is invalid.') from None
        if (metadata.byte_size is not None and
                (isinstance(metadata.byte_size, bool) or not isinstance(metadata.byte_size, int)
                 or metadata.byte_size < 0)):
            raise DocumentValidationError('Receipt size metadata is invalid.')
        if metadata.sha256 and not re.fullmatch('[0-9a-f]{64}', metadata.sha256):
            raise DocumentValidationError('Receipt checksum metadata is invalid.')
        if metadata.sha256 and (metadata.byte_size is None or metadata.byte_size <= 0 or
                                metadata.byte_size > MAX_RECEIPT_BYTES or
                                not metadata.original_filename or not metadata.mime_type):
            raise DocumentValidationError('Verified receipts require complete integrity metadata.')
        if metadata.sha256 and not re.fullmatch('[0-9a-f]{32}', metadata.document_id):
            raise DocumentValidationError('Verified receipts require a portable receipt identity.')
        if metadata.document_id == document.storage_key:
            raise DocumentValidationError('Document identity must be independent of the provider locator.')
        return dict(
            id=clean_text(metadata.document_id, 'Document identity', required=True),
            stored_filename=metadata.stored_filename, original_filename=metadata.original_filename,
            mime_type=metadata.mime_type, byte_size=metadata.byte_size, sha256=metadata.sha256 or None,
            storage_key=clean_text(document.storage_key, 'Document locator', required=True),
            open_url=document.open_url, store_kind=self.store_kind, store_scope_key=self.store_scope_key,
        )

    def register(self, connection, document):
        document = map_legacy_document(self.entity_id, self.store_kind, self.store_scope_key, document)
        values = self.metadata_values(document)
        # Both canonical identity and scoped locator deduplicate concurrent acceptance.
        created = new_object(self.entity_id, **values)
        columns = ','.join(created)
        parameters = ','.join(':'+key for key in created)
        connection.execute(text(
            f'INSERT INTO documents({columns}) VALUES ({parameters}) ON CONFLICT DO NOTHING'
        ), created)
        rows = connection.execute(text(
            'SELECT * FROM documents WHERE entity_id=:scope AND (id=:id OR '
            '(store_kind=:store_kind AND store_scope_key=:store_scope_key AND storage_key=:storage_key)) '
            'ORDER BY id FOR UPDATE'
        ), {**values, 'scope': self.entity_id}).mappings().all()
        if len(rows) != 1 or any(rows[0][key] != value for key, value in values.items()):
            raise StorageConflictError('The document identity or metadata conflicts with the registered receipt.')
        return self.document(rows[0])

    def register_document(self, document):
        """Accept known inventory/migration metadata without linking or moving bytes."""
        with self.operation() as connection:
            self.lock_entity(connection, key_share=True)
            return self.register(connection, document)

    def target(self, connection, transaction_id, *, lock=False):
        row = self.get_row(connection, 'entries', transaction_id)
        if row['projection_kind'] != 'simple' or row['depreciation_asset_id']:
            raise DocumentValidationError('This bookkeeping record does not support receipts.')
        source = row['mixed_use_source_id']
        if lock:
            self.lock_entity(connection, key_share=True)
            if source and self.source_id != source:
                raise DocumentValidationError('Mixed-use receipts require the source-aware repository.')
            if self.source_id and source != self.source_id:
                raise DocumentValidationError('The selected projection does not belong to the bound source.')
            keys = {self.key('entries', transaction_id)}
            if source:
                keys.add(self.key('mixed_use_sources', source))
            locked = lock_aggregates(connection, keys)
            row = locked[self.key('entries', transaction_id)]
            if (row['mixed_use_source_id'] != source or row['projection_kind'] != 'simple'
                    or row['depreciation_asset_id']):
                raise StorageConflictError('Receipt ownership changed; reload the record.')
            if source:
                source_row = locked[self.key('mixed_use_sources', source)]
                if (source_row['relationship_state'] != 'complete' or
                        source_row['expected_projection_entry_id'] != transaction_id):
                    raise StorageConflictError('Inspect the mixed-use pair before changing receipts.')
                token = self.expected_source.get('baseline') if isinstance(self.expected_source, Mapping) else None
                check_baseline(self.key('mixed_use_sources', source), source_row, token, required=True)
        return ('mixed_use_source_id', source) if source else ('entry_id', transaction_id)

    def linked_documents(self, connection, column, target):
        return list(connection.execute(text(
            'SELECT d.* FROM document_links l JOIN documents d '
            'ON d.entity_id=l.entity_id AND d.id=l.document_id '
            f'WHERE l.entity_id=:scope AND l.{column}=:id ORDER BY l.position'
        ), {'scope': self.entity_id, 'id': target}).mappings())

    def references(self, profile_key, transaction_id, *, fresh=False):
        self.check_profile(profile_key)
        with self.operation(read_only=True) as connection:
            column, target = self.target(connection, transaction_id)
            return tuple(self.document(row) for row in self.linked_documents(connection, column, target))

    def associations(self, profile_key, *, fresh=False):
        self.check_profile(profile_key)
        with self.operation(read_only=True) as connection:
            rows = connection.execute(text(
                'SELECT d.*,coalesce(l.entry_id,s.expected_projection_entry_id) AS transaction_id '
                'FROM document_links l JOIN documents d ON d.entity_id=l.entity_id AND d.id=l.document_id '
                'LEFT JOIN mixed_use_sources s ON s.entity_id=l.entity_id AND s.id=l.mixed_use_source_id '
                'WHERE l.entity_id=:scope ORDER BY transaction_id,l.position'
            ), {'scope': self.entity_id}).mappings()
            return tuple(ReceiptAssociation(row['transaction_id'], self.document(row)) for row in rows)

    def link(self, profile_key, transaction_id, document):
        self.check_profile(profile_key)
        with self.operation() as connection:
            column, target = self.target(connection, transaction_id, lock=True)
            accepted = self.register(connection, document)
            ids = [self.document(row).metadata.document_id
                   for row in self.linked_documents(connection, column, target)]
            if accepted.metadata.document_id not in ids:
                ids.append(accepted.metadata.document_id)
            write_document_links(connection, self.entity_id, column, target, ids)

    def unlink(self, profile_key, transaction_id, storage_key):
        self.check_profile(profile_key)
        with self.operation() as connection:
            column, target = self.target(connection, transaction_id, lock=True)
            documents = [self.document(row) for row in self.linked_documents(connection, column, target)]
            ids = [document.metadata.document_id for document in documents if document.storage_key != storage_key]
            write_document_links(connection, self.entity_id, column, target, ids)
