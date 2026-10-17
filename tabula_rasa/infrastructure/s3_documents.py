"""Private, immutable S3 receipt bytes; canonical relationships remain in SQL."""

import base64
import hashlib
from io import BytesIO
import re
from urllib.parse import quote, unquote

from tabula_rasa.application.documents import (
    DocumentError, DocumentMetadata, DocumentNotFoundError, DocumentReference,
    DocumentValidationError, MAX_RECEIPT_BYTES, ReceiptInventory, validate_receipt_upload,
)
from tabula_rasa.document_names import safe_receipt_filename
from tabula_rasa.receipt_manifest import ReceiptManifestError, validate_receipt_filename


class _ProviderFailure(Exception):
    def __init__(self, code):
        self.code = code


def _request(client, method, **kwargs):
    try:
        return getattr(client, method)(**kwargs)
    except Exception as error:
        response = getattr(error, 'response', {})
        code = str(response.get('Error', {}).get('Code', 'unavailable'))
    # Never retain SDK exceptions (which can contain request bodies/credentials).
    raise _ProviderFailure(code)


def _encode(value):
    return base64.b64encode(value.encode()).decode('ascii')


def _decode(value):
    return base64.b64decode(value, validate=True).decode('utf-8')


class S3DocumentStore:
    """One entity, one environment, version-pinned locators and server-only I/O.

    boto retries are disabled: one fresh GET reconciles a failed PUT and only
    confirmed absence permits one retry. A successful PUT is authoritative.
    No public URLs, signed browser grants, ACLs or unbounded body reads.
    """
    store_kind = 's3'

    def __init__(self, entity_id, bucket, region, namespace, client):
        if (not isinstance(entity_id, str) or not entity_id.strip()
                or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)
                or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-\d', region)
                or not re.fullmatch(r'(staging|production|recovery)/[0-9a-f]{32}', namespace)):
            raise DocumentValidationError('Invalid private S3 binding.')
        self.entity_id, self.bucket, self.region = entity_id, bucket, region
        self.prefix = namespace + '/' + hashlib.sha256(entity_id.encode()).hexdigest() + '/'
        self.client = client

    @property
    def scope_key(self):
        return f's3:{self.region}:{self.bucket}:{self.prefix}'

    def _scope(self, entity_id):
        if entity_id != self.entity_id:
            raise DocumentValidationError('Document storage belongs to a different business entity.')

    def _key(self, document_id):
        if not re.fullmatch('[0-9a-f]{32}', document_id):
            raise DocumentValidationError('A receipt requires a stable portable identity.')
        return self.prefix + hashlib.sha256(('receipt:' + document_id).encode()).hexdigest()

    def _locator(self, storage_key):
        key, separator, version = storage_key.partition('?versionId=')
        if (not separator or not key.startswith(self.prefix)
                or not re.fullmatch('[0-9a-f]{64}', key[len(self.prefix):])
                or not version or len(version) > 2048 or quote(unquote(version), safe='') != version
                or unquote(version) == 'null'):
            raise DocumentValidationError('Invalid receipt location for this business.')
        return key, unquote(version)

    def _reference(self, key, response):
        try:
            values = response['Metadata']
            metadata = DocumentMetadata(
                values['document-id'], _decode(values['stored-filename']), _decode(values['filename']),
                _decode(values['mime-type']), int(response['ContentLength']), values['sha256'],
            )
            version = response['VersionId']
            if (key != self._key(metadata.document_id) or values['entity-sha256'] != hashlib.sha256(self.entity_id.encode()).hexdigest()
                    or not re.fullmatch('[0-9a-f]{64}', metadata.sha256)
                    or not 0 < metadata.byte_size <= MAX_RECEIPT_BYTES
                    or response.get('ServerSideEncryption') != 'AES256'
                    or not version or version == 'null'):
                raise ValueError
            validate_receipt_upload(metadata.original_filename, b'x')
            validate_receipt_filename(metadata.stored_filename, 'Receipt filename')
            return DocumentReference(self.entity_id, metadata, key + '?versionId=' + quote(version, safe=''))
        except Exception:
            pass
        raise DocumentValidationError('Receipt integrity or retained S3 version is invalid. Stop and inspect storage.')

    def _read(self, key, version=None, *, content=False):
        try:
            response = _request(self.client, 'get_object' if content else 'head_object',
                Bucket=self.bucket, Key=key, **({'VersionId': version} if version else {}))
        except _ProviderFailure as error:
            missing = error.code in {'NoSuchKey', 'NoSuchVersion', '404', 'NotFound'}
        else:
            if version is not None and response.get('VersionId') != version:
                if content:
                    response['Body'].close()
                raise DocumentValidationError('The requested retained receipt version was not returned.')
            if not content:
                return self._reference(key, response)
            body = response['Body']
            try:
                document = self._reference(key, response)
                result = bytearray()
                while chunk := body.read(min(65536, MAX_RECEIPT_BYTES + 1 - len(result))):
                    result.extend(chunk)
                    if len(result) > MAX_RECEIPT_BYTES:
                        raise ValueError
                if (len(result) != document.metadata.byte_size
                        or hashlib.sha256(result).hexdigest() != document.metadata.sha256):
                    raise ValueError
                return document, bytes(result)
            except Exception:
                pass
            finally:
                body.close()
            raise DocumentError('Receipt byte verification failed. Stop and inspect recovery copies.')
        if missing:
            raise DocumentNotFoundError('Receipt bytes or the retained version are missing. Inspect recovery copies.')
        raise DocumentError('Private receipt storage is unavailable. Check provider access before retrying.')

    def validate(self):
        try:
            response = _request(self.client, 'get_bucket_versioning', Bucket=self.bucket)
            public = _request(self.client, 'get_public_access_block', Bucket=self.bucket)['PublicAccessBlockConfiguration']
        except _ProviderFailure:
            pass
        else:
            if (response.get('Status') == 'Enabled' and all(public.get(key) is True for key in
                    ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets'))):
                return
        raise DocumentError('Receipt storage requires an accessible private, version-enabled bucket.')

    def upload(self, entity_id, upload):
        self._scope(entity_id)
        validate_receipt_upload(upload.original_filename, upload.content)
        if hashlib.sha256(upload.content).hexdigest() != upload.sha256:
            raise DocumentValidationError('Receipt upload checksum is invalid.')
        key = self._key(upload.document_id)
        name = safe_receipt_filename(upload.original_filename)
        try:
            stored_name = validate_receipt_filename(upload.stored_filename or name, 'Receipt filename')
        except ReceiptManifestError:
            raise DocumentValidationError('Receipt filename metadata is invalid.') from None
        values = {'document-id': upload.document_id, 'filename': _encode(name),
                  'stored-filename': _encode(stored_name),
                  'mime-type': _encode(upload.mime_type), 'sha256': upload.sha256,
                  'entity-sha256': hashlib.sha256(entity_id.encode()).hexdigest()}
        for attempt in range(2):
            try:
                response = _request(self.client, 'put_object', Bucket=self.bucket, Key=key,
                    Body=BytesIO(upload.content), ContentLength=len(upload.content), ContentType=upload.mime_type,
                    Metadata=values, IfNoneMatch='*', ServerSideEncryption='AES256',
                    ChecksumSHA256=base64.b64encode(bytes.fromhex(upload.sha256)).decode())
            except _ProviderFailure as error:
                # Permission/validation failures are definitive and never retried.
                definitive = error.code in {'AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch', 'BadDigest', 'InvalidRequest'}
            else:
                return self._reference(key, {**response, 'Metadata': values, 'ContentLength': len(upload.content)})
            if definitive or attempt == 1:
                break
            try:
                existing, content = self._read(key, content=True)
            except DocumentNotFoundError:
                continue
            if (existing.metadata.document_id != upload.document_id or content != upload.content
                    or existing.metadata.original_filename != name or existing.metadata.stored_filename != stored_name
                    or existing.metadata.mime_type != upload.mime_type):
                raise DocumentValidationError('The receipt identity is already used by a different upload.')
            return existing
        raise DocumentError('Receipt upload could not be confirmed. Inspect unreferenced receipts before retrying.')

    def metadata(self, entity_id, storage_key):
        self._scope(entity_id)
        key, version = self._locator(storage_key)
        return self._read(key, version)

    def fetch(self, entity_id, storage_key):
        self._scope(entity_id)
        key, version = self._locator(storage_key)
        return self._read(key, version, content=True)[1]

    def inventory(self, entity_id, *, fresh=False):
        self._scope(entity_id)
        documents, token = [], None
        while True:
            try:
                response = _request(self.client, 'list_objects_v2', Bucket=self.bucket, Prefix=self.prefix,
                    **({'ContinuationToken': token} if token else {}))
            except _ProviderFailure:
                break
            for item in response.get('Contents', []):
                key = item['Key']
                if not key.startswith(self.prefix) or not re.fullmatch('[0-9a-f]{64}', key[len(self.prefix):]):
                    raise DocumentValidationError('Unexpected receipt object. Inspect the selected storage prefix.')
                documents.append(self._read(key))
            if not response.get('IsTruncated'):
                return ReceiptInventory(tuple(documents))
            next_token = response.get('NextContinuationToken')
            if not next_token or next_token == token:
                break
            token = next_token
        raise DocumentError('Receipt inventory is unavailable. Check private storage access.')

    def delete(self, entity_id, storage_key):
        self._scope(entity_id)
        key, _ = self._locator(storage_key)
        self.metadata(entity_id, storage_key)
        try:
            # Creates a delete marker; DeleteObjectVersion is never called.
            _request(self.client, 'delete_object', Bucket=self.bucket, Key=key)
        except _ProviderFailure:
            pass
        else:
            return
        raise DocumentError('Receipt deletion is uncertain. Inspect retained versions; do not retry automatically.')


def create_s3_document_store(entity_id, configuration, *, client=None):
    """Server provisioning seam; explicit credentials, no ambient AWS fallback."""
    try:
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client('s3', region_name=configuration['region'],
                aws_access_key_id=configuration['access_key_id'], aws_secret_access_key=configuration['secret_access_key'],
                config=Config(retries={'total_max_attempts': 1}, connect_timeout=5, read_timeout=30,
                              signature_version='s3v4'))
        if not configuration['access_key_id'] or not configuration['secret_access_key']:
            raise ValueError
        return S3DocumentStore(entity_id, configuration['bucket'], configuration['region'], configuration['namespace'], client)
    except Exception:
        pass
    raise DocumentError('Private S3 configuration is unavailable.')
