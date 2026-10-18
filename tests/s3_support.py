"""Synthetic S3 API boundary with conditional creates and retained versions."""
from copy import deepcopy
from io import BytesIO

from botocore.exceptions import ClientError

from tabula_rasa.infrastructure.s3_documents import S3DocumentStore


def provider_error(code):
    return ClientError({'Error': {'Code': code, 'Message': 'private provider detail'}}, 'synthetic')


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.current = {}
        self.calls = []
        self.put_failures = []
        self.read_failure = None
        self.versioning = 'Enabled'
        self.page_size = 1000

    def put_object(self, **kwargs):
        self.calls.append(('put', kwargs['Key']))
        failure = self.put_failures.pop(0) if self.put_failures else None
        if failure == 'before':
            raise provider_error('SlowDown')
        if failure == 'denied':
            raise provider_error('AccessDenied')
        key = kwargs['Bucket'], kwargs['Key']
        if key in self.current:
            raise provider_error('PreconditionFailed')
        assert kwargs['IfNoneMatch'] == '*'
        assert kwargs['ServerSideEncryption'] == 'AES256'
        content = kwargs['Body'].read()
        version = str(len(self.objects) + 1)
        self.objects[(*key, version)] = {'Metadata': deepcopy(kwargs['Metadata']), 'ContentLength': len(content),
            'VersionId': version, 'ServerSideEncryption': 'AES256', 'content': content}
        self.current[key] = version
        if failure == 'after':
            raise provider_error('RequestTimeout')
        return {'VersionId': version, 'ServerSideEncryption': 'AES256'}

    def head_object(self, **kwargs):
        self.calls.append(('head', kwargs['Key']))
        if self.read_failure:
            raise provider_error(self.read_failure)
        key = kwargs['Bucket'], kwargs['Key']
        version = kwargs.get('VersionId') or self.current.get(key)
        if (*key, version) not in self.objects:
            raise provider_error('NoSuchVersion' if kwargs.get('VersionId') else 'NoSuchKey')
        return deepcopy(self.objects[(*key, version)])

    def get_object(self, **kwargs):
        response = self.head_object(**kwargs)
        self.calls[-1] = ('get', kwargs['Key'])
        response['Body'] = BytesIO(response.pop('content'))
        return response

    def list_objects_v2(self, **kwargs):
        self.calls.append(('list', kwargs['Prefix']))
        if self.read_failure:
            raise provider_error(self.read_failure)
        keys = sorted(key for bucket, key in self.current if bucket == kwargs['Bucket'] and key.startswith(kwargs['Prefix']))
        start = int(kwargs.get('ContinuationToken', '0'))
        end = start + self.page_size
        return {'Contents': [{'Key': key} for key in keys[start:end]], 'IsTruncated': end < len(keys),
                'NextContinuationToken': str(end)}

    def delete_object(self, **kwargs):
        assert 'VersionId' not in kwargs
        self.calls.append(('delete-marker', kwargs['Key']))
        self.current.pop((kwargs['Bucket'], kwargs['Key']), None)
        return {}

    def get_bucket_versioning(self, **kwargs):
        return {'Status': self.versioning}

    def get_public_access_block(self, **kwargs):
        return {'PublicAccessBlockConfiguration': dict.fromkeys(
            ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets'), True)}


def s3_store(entity='alpha', client=None, *, namespace='staging/' + '1' * 32):
    return S3DocumentStore(entity, 'synthetic-receipts', 'us-east-1', namespace, client or FakeS3())
