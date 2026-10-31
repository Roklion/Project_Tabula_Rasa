"""Synthetic handoff packages reuse canonical validation and never deliver partial files."""

from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tabula_rasa.application.customer_export import CustomerExportService
from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.bookkeeping_export.format import build_artifact, validate_artifact, content_digest
from tests.test_bookkeeping_export import empty_snapshot


def package_service(content=b'synthetic receipt', *, max_bytes=200 * 1024 * 1024):
    artifact = build_artifact(empty_snapshot())
    root = artifact['domains']['business_entities'][0]
    artifact['domains']['documents'] = [{
        'entity_id': 'alpha', 'id': 'doc', 'incarnation_id': 'doc', 'version': 1,
        'created_at': root['created_at'], 'updated_at': root['updated_at'],
        'stored_filename': 'receipt.pdf', 'original_filename': '../../receipt.pdf',
        'mime_type': 'application/pdf', 'byte_size': len(content), 'sha256': sha256(content).hexdigest(),
        'store_kind': 'fake', 'store_scope_key': 'alpha-store', 'storage_key': 'opaque', 'open_url': '',
    }]
    artifact['manifest']['counts']['documents'] = 1
    artifact['manifest']['content_sha256'] = content_digest(artifact['domains'])
    receipts = Mock(profile_key='alpha')
    receipts.unreferenced.return_value = SimpleNamespace(documents=(), unverified_storage_keys=())
    reference = SimpleNamespace(profile_key='alpha', metadata=SimpleNamespace(document_id='doc'))
    receipts.download.return_value = reference, content
    exporter = Mock()
    exporter.export.return_value = artifact
    return CustomerExportService(exporter, receipts, 'alpha', max_bytes=max_bytes), artifact


def prepare(service, include=True):
    return service.prepare(include_documents=include, history_boundary={
        'activated_at': '2026-01-01T00:00:00+00:00', 'pre_activation_history': 'unavailable',
        'mutation_history': 'excluded'})


def test_complete_versioned_package_preserves_canonical_and_maps_safe_attachment_paths():
    service, artifact = package_service(b'x' * (20 * 1024 * 1024))
    with prepare(service) as stream, ZipFile(stream) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['format_version'] == 1 and manifest['scope'] == 'documents_inclusive'
        assert manifest['audit_history'] == 'excluded'
        assert manifest['history_boundary']['pre_activation_history'] == 'unavailable'
        assert manifest['attachments'] == [{'document_id': 'doc', 'path': 'documents/000000',
            'origin': 'canonical',
            'original_filename': '../../receipt.pdf', 'mime_type': 'application/pdf'}]
        for path, expected in manifest['files'].items():
            content = archive.read(path)
            assert len(content) == expected['bytes'] and sha256(content).hexdigest() == expected['sha256']
        canonical = json.loads(archive.read('bookkeeping.json'))
        assert validate_artifact(canonical, entity_id='alpha') == artifact
        assert len(canonical['domains']) == 26
        assert all('..' not in name for name in archive.namelist())


def test_metadata_only_discloses_missing_bytes_without_calling_provider():
    service, _ = package_service()
    with prepare(service, False) as stream, ZipFile(stream) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['scope'] == 'metadata_only' and manifest['attachments'] == []
        assert 'documents/000000' not in archive.namelist()
    service.receipts.download.assert_not_called()


def test_unlinked_provider_files_are_included_without_rewriting_canonical_json():
    service, artifact = package_service()
    reference = SimpleNamespace(profile_key='alpha', metadata=SimpleNamespace(
        document_id='unlinked', byte_size=3, sha256=sha256(b'new').hexdigest(),
        original_filename='new.pdf', mime_type='application/pdf'))
    service.receipts.unreferenced.return_value = SimpleNamespace(documents=(reference,), unverified_storage_keys=())
    canonical_reference, original = service.receipts.download.return_value
    service.receipts.download.side_effect = lambda identity: (reference, b'new') if identity == 'unlinked' else (canonical_reference, original)
    with prepare(service) as stream, ZipFile(stream) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert [row['origin'] for row in manifest['attachments']] == ['canonical', 'unlinked_inventory']
        assert archive.read('documents/000001') == b'new'
        assert json.loads(archive.read('bookkeeping.json')) == artifact


def test_disconnected_or_unverified_inventory_fails_inclusive_and_closes_partial_stream(monkeypatch):
    from tabula_rasa.application import customer_export
    service, _ = package_service()
    service.receipts.unreferenced.return_value = SimpleNamespace(documents=(), unverified_storage_keys=('opaque',))
    with pytest.raises(ExportError, match='document_integrity_unavailable'):
        prepare(service)
    service.receipts = None
    with pytest.raises(ExportError, match='documents_unavailable'):
        prepare(service)
    service, _ = package_service()
    temporary = customer_export.TemporaryFile()
    monkeypatch.setattr(customer_export, 'TemporaryFile', lambda **kwargs: temporary)
    service.receipts.download.side_effect = RuntimeError('synthetic read failure')
    with pytest.raises(RuntimeError):
        prepare(service)
    assert temporary.closed


@pytest.mark.parametrize('failure', ['missing', 'changed', 'unverified', 'foreign', 'quota'])
def test_missing_changed_foreign_or_oversized_documents_never_produce_a_complete_package(failure):
    service, artifact = package_service(max_bytes=100 if failure == 'quota' else 200 * 1024 * 1024)
    if failure == 'missing':
        service.receipts.download.side_effect = RuntimeError('private provider text')
    elif failure == 'changed':
        reference, _ = service.receipts.download.return_value
        service.receipts.download.return_value = reference, b'changed'
    elif failure == 'foreign':
        service.receipts.download.return_value[0].profile_key = 'beta'
    elif failure == 'unverified':
        artifact['domains']['documents'][0]['sha256'] = None
        artifact['manifest']['content_sha256'] = content_digest(artifact['domains'])
    with pytest.raises((ExportError, RuntimeError)):
        prepare(service)


def test_deadline_and_forged_canonical_entity_fail_then_read_retry_builds_a_new_package():
    service, artifact = package_service()
    original = deepcopy(artifact)
    artifact['manifest']['entity_id'] = 'beta'
    with pytest.raises(ExportError, match='entity_scope'):
        prepare(service)
    service.exporter.export.return_value = original
    service.clock = Mock(side_effect=[0, 301])
    with pytest.raises(ExportError, match='export_limit'):
        prepare(service)
    service.clock = lambda: 0
    with prepare(service) as stream:
        assert stream.read(2) == b'PK'
