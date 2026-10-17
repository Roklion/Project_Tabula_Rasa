"""Private byte adapter, SDK boundary, bounded reconciliation and integrity."""
from dataclasses import replace
import hashlib

import boto3
from botocore.config import Config
from botocore.stub import Stubber
import pytest

from tabula_rasa.application.documents import DocumentError, DocumentNotFoundError, DocumentUpload, DocumentValidationError
from tabula_rasa.infrastructure.s3_documents import S3DocumentStore, create_s3_document_store
from tests.s3_support import FakeS3, s3_store


def upload(identity='a' * 32, content=b'%PDF-1.7 synthetic', name='receipt.pdf'):
    return DocumentUpload(identity, name, 'application/pdf', hashlib.sha256(content).hexdigest(), content)


def test_invalid_recovery_filename_is_document_validation_error_without_provider_write():
    store = s3_store()
    with pytest.raises(DocumentValidationError, match='filename metadata'):
        store.upload('alpha', replace(upload(), stored_filename='../invalid.pdf'))
    assert store.client.calls == []


def test_exact_bytes_pinned_versions_scoped_keys_and_reference_only_recovery():
    client = FakeS3()
    alpha, beta = s3_store(client=client), s3_store('beta', client)
    a, b = alpha.upload('alpha', upload()), beta.upload('beta', upload(content=b'beta'))
    assert a.storage_key != b.storage_key and a.metadata.document_id == b.metadata.document_id
    assert 'receipt.pdf' not in a.storage_key and 'alpha' not in a.storage_key
    assert alpha.scope_key != beta.scope_key and not a.open_url
    assert client.calls == [('put', a.storage_key.split('?')[0]), ('put', b.storage_key.split('?')[0])]
    assert alpha.fetch('alpha', a.storage_key) == upload().content
    assert alpha.metadata('alpha', a.storage_key) == a
    before = len(client.calls)
    for scope, key in [('beta', a.storage_key), ('alpha', b.storage_key), ('alpha', 'forged'),
                       ('alpha', a.storage_key.split('?')[0]), ('alpha', a.storage_key + '&expired=yes')]:
        with pytest.raises(DocumentValidationError):
            alpha.fetch(scope, key)
    assert len(client.calls) == before
    alpha.delete('alpha', a.storage_key)
    assert alpha.inventory('alpha').documents == ()
    assert beta.inventory('beta').documents == (b,)
    # A logical deletion creates a marker. Explicit version pins keep originals reachable.
    assert alpha.fetch('alpha', a.storage_key) == upload().content
    client.objects.pop(('synthetic-receipts', *alpha._locator(a.storage_key)))
    with pytest.raises(DocumentNotFoundError, match='retained version'):
        alpha.fetch('alpha', a.storage_key)


@pytest.mark.parametrize('failure,puts', [('after', 1), ('before', 2)])
def test_uncertain_upload_reconciles_once_and_retries_only_absence(failure, puts):
    client = FakeS3()
    client.put_failures = [failure]
    store = s3_store(client=client)
    result = store.upload('alpha', upload())
    assert result.metadata.sha256 == upload().sha256
    assert sum(method == 'put' for method, _ in client.calls) == puts
    assert sum(method == 'get' for method, _ in client.calls) == (failure == 'after')
    assert len(client.objects) == 1


def test_replay_conflict_denial_unknown_status_and_secret_sanitization():
    client = FakeS3()
    store = s3_store(client=client)
    result = store.upload('alpha', upload())
    assert store.upload('alpha', upload()) == result
    with pytest.raises(DocumentValidationError, match='different upload'):
        store.upload('alpha', upload(content=b'other'))
    client.put_failures = ['denied']
    before = len(client.calls)
    with pytest.raises(DocumentError) as caught:
        store.upload('alpha', upload('b' * 32))
    assert len(client.calls) == before + 1
    assert caught.value.__context__ is None and 'private provider detail' not in str(caught.value)
    client.put_failures, client.read_failure = ['after'], 'AccessDenied'
    before = len(client.objects)
    with pytest.raises(DocumentError) as caught:
        store.upload('alpha', upload('c' * 32))
    assert len(client.objects) == before + 1 and caught.value.__context__ is None
    assert client.put_failures == []  # No hidden SDK or application retry.


def test_second_failed_put_stops_without_another_readback_or_retry():
    client = FakeS3()
    client.put_failures = ['before', 'after']
    store = s3_store(client=client)
    with pytest.raises(DocumentError, match='could not be confirmed'):
        store.upload('alpha', upload())
    assert [method for method, _ in client.calls] == ['put', 'head', 'put']
    assert len(client.objects) == 1
    assert len(store.inventory('alpha').documents) == 1  # Recoverable after the stop.


def test_type_size_checksum_encryption_and_version_controls():
    client = FakeS3()
    store = s3_store(client=client)
    for invalid in [replace(upload(), content=b''), replace(upload(), original_filename='bad.exe'),
                    replace(upload(), sha256='0' * 64), replace(upload(), document_id='../invalid')]:
        with pytest.raises(DocumentValidationError):
            store.upload('alpha', invalid)
    assert client.calls == []
    result = store.upload('alpha', upload())
    row = next(iter(client.objects.values()))
    for field, bad in [('content', b'corrupt'), ('ContentLength', 30_000_000), ('VersionId', 'null'),
                       ('ServerSideEncryption', 'none')]:
        original = row[field]
        row[field] = bad
        with pytest.raises(DocumentError):
            store.fetch('alpha', result.storage_key)
        row[field] = original
    client.versioning = 'Suspended'
    with pytest.raises(DocumentError, match='version-enabled'):
        store.validate()


def test_paginated_inventory_and_provider_failure():
    client = FakeS3()
    store = s3_store(client=client)
    first = store.upload('alpha', upload())
    second = store.upload('alpha', upload('b' * 32))
    client.page_size = 1
    assert set(store.inventory('alpha').documents) == {first, second}
    client.read_failure = 'AccessDenied'
    with pytest.raises(DocumentError) as caught:
        store.inventory('alpha')
    assert caught.value.__context__ is None


def test_boto3_put_get_boundary_uses_signed_private_conditional_requests():
    client = boto3.client('s3', region_name='us-east-1', aws_access_key_id='synthetic',
        aws_secret_access_key='synthetic', config=Config(retries={'total_max_attempts': 1}))
    store = S3DocumentStore('alpha', 'synthetic-receipts', 'us-east-1', 'staging/' + '1' * 32, client)
    with Stubber(client) as stub:
        stub.add_response('put_object', {'VersionId': 'version/1', 'ServerSideEncryption': 'AES256'})
        result = store.upload('alpha', upload())
        assert result.storage_key.endswith('?versionId=version%2F1')
        # The SDK model validates real request arguments even with a stubbed transport.
        from io import BytesIO
        from tests.s3_support import FakeS3
        fake = FakeS3()
        reference = s3_store(client=fake).upload('alpha', upload())
        response = fake.head_object(Bucket='synthetic-receipts', Key=reference.storage_key.split('?')[0])
        response['VersionId'] = 'version/1'
        response['Body'] = BytesIO(response.pop('content'))
        stub.add_response('get_object', response, {'Bucket': store.bucket,
            'Key': result.storage_key.split('?')[0], 'VersionId': 'version/1'})
        assert store.fetch('alpha', result.storage_key) == upload().content
        stub.assert_no_pending_responses()


def test_configuration_requires_explicit_credentials():
    with pytest.raises(DocumentError) as caught:
        create_s3_document_store('alpha', {}, client=FakeS3())
    assert caught.value.__context__ is None
