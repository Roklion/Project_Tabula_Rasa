"""Mounted grants keep the same containment and tenant boundaries as regular files."""
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets


def link(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        if os.name == 'nt':
            pytest.skip('Windows account cannot create symbolic links; Linux CI covers mounted secrets.')
        raise


def test_versioned_mounted_grants_read_freshly_and_preserve_two_business_isolation(tmp_path):
    key = Fernet.generate_key().decode()
    store = ConnectionSecrets(tmp_path, key)
    scopes = [dict(environment='staging', organization_id='org-' + name,
                   entity_id='entity-' + name, provider='google_drive') for name in ('a', 'b')]
    references = [store.put(dict(scope, refresh_token='synthetic-' + scope['entity_id'])) for scope in scopes]
    first = tmp_path / '..version-1'
    first.mkdir()
    link(tmp_path / '..data', first, directory=True)
    for reference in references:
        filename = reference + '.grant'
        (tmp_path / filename).rename(first / filename)
        link(tmp_path / filename, Path('..data') / filename)
    for reference, scope in zip(references, scopes):
        assert store.get(reference, **scope)['refresh_token'] == 'synthetic-' + scope['entity_id']
        for field in scope:
            with pytest.raises(IdentityError) as error:
                store.get(reference, **{**scope, field: 'foreign'})
            assert error.value.__context__ is None
    with pytest.raises(IdentityError):
        store.get(references[0], **scopes[1])

    # A platform's atomic version switch must be observed on the next read.
    second = tmp_path / '..version-2'
    second.mkdir()
    for reference, scope in zip(references, scopes):
        (second / (reference + '.grant')).write_bytes(
            Fernet(key.encode()).encrypt(json.dumps(dict(scope, refresh_token='synthetic-new')).encode()))
    link(tmp_path / '..next', second, directory=True)
    (tmp_path / '..next').replace(tmp_path / '..data')
    for reference, scope in zip(references, scopes):
        assert store.get(reference, **scope)['refresh_token'] == 'synthetic-new'


@pytest.mark.parametrize('target_kind', ['outside', 'missing', 'directory'])
def test_mounted_grant_refuses_escape_missing_and_non_file_targets(tmp_path, target_kind):
    root = tmp_path / 'secrets'
    root.mkdir()
    store = ConnectionSecrets(root, Fernet.generate_key().decode())
    scope = dict(environment='test', organization_id='org', entity_id='entity', provider='google_drive')
    reference = store.put(scope)
    path = root / (reference + '.grant')
    if target_kind == 'outside':
        target = tmp_path / 'outside.grant'
        path.rename(target)
    else:
        path.unlink()
        target = root / target_kind
        if target_kind == 'directory':
            target.mkdir()
    link(path, target, directory=target_kind == 'directory')
    with pytest.raises(IdentityError) as error:
        store.get(reference, **scope)
    assert error.value.__context__ is None


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='Named pipes are a Unix filesystem case.')
def test_fifo_is_refused_without_blocking(tmp_path):
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    reference = 'a' * 32
    os.mkfifo(tmp_path / (reference + '.grant'))
    with pytest.raises(IdentityError):
        store.get(reference, environment='test', organization_id='org', entity_id='entity', provider='google_drive')


@pytest.mark.skipif(os.name == 'nt', reason='Windows refuses directory descriptors before fdopen.')
def test_directory_rejection_closes_open_descriptor(tmp_path, monkeypatch):
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    reference = 'a' * 32
    (tmp_path / (reference + '.grant')).mkdir()
    descriptors = []
    real_open = os.open

    def record_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, 'open', record_open)
    with pytest.raises(IdentityError) as error:
        store.get(reference, environment='test', organization_id='org', entity_id='entity', provider='google_drive')
    assert error.value.__context__ is None
    assert len(descriptors) == 1
    try:
        with pytest.raises(OSError) as closed:
            os.fstat(descriptors[0])
        assert closed.value.errno == errno.EBADF
    finally:
        try:
            os.close(descriptors[0])
        except OSError:
            pass


@pytest.mark.skipif(not hasattr(os, 'O_NOFOLLOW'), reason='No-follow descriptor flag is a Unix case.')
def test_replacement_leaf_symlink_is_not_followed(tmp_path, monkeypatch):
    root = tmp_path / 'secrets'
    root.mkdir()
    store = ConnectionSecrets(root, Fernet.generate_key().decode())
    scope = dict(environment='test', organization_id='org', entity_id='entity', provider='google_drive')
    reference = store.put(scope)
    target = root / (reference + '.grant')
    outside = tmp_path / 'outside.grant'
    real_open = os.open

    def swap_before_open(path, flags, *args, **kwargs):
        target.rename(outside)
        target.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', swap_before_open)
    with pytest.raises(IdentityError):
        store.get(reference, **scope)


def test_new_reference_is_render_compatible_and_existing_numeric_reference_still_reads(tmp_path, monkeypatch):
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    scope = dict(environment='test', organization_id='org', entity_id='entity', provider='google_drive')
    monkeypatch.setattr('tabula_rasa.infrastructure.connection_secrets.uuid4',
                        Mock(side_effect=[SimpleNamespace(hex='1' * 32), SimpleNamespace(hex='a' * 32)]))
    reference = store.put(scope)
    assert reference == 'a' * 32
    (tmp_path / (reference + '.grant')).rename(tmp_path / ('1' * 32 + '.grant'))
    assert store.get('1' * 32, **scope) == scope


def test_provisioning_never_replaces_existing_mounted_grant(tmp_path, monkeypatch):
    store = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    reference = 'a' * 32
    target = tmp_path / 'operator-file'
    target.write_bytes(b'preserve-ciphertext')
    link(tmp_path / (reference + '.grant'), target)
    monkeypatch.setattr('tabula_rasa.infrastructure.connection_secrets.uuid4',
                        lambda: SimpleNamespace(hex=reference))
    with pytest.raises(IdentityError):
        store.put({'synthetic': True})
    assert target.read_bytes() == b'preserve-ciphertext'
