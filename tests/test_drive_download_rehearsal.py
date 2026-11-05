"""Validate the scoped transport failure through the real Drive client."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests

from tabula_rasa.google_drive import GoogleDriveClient
from tabula_rasa.google_drive.errors import (
    DRIVE_API_ROOT,
    TOKEN_ENDPOINT,
    GoogleDriveAccessError,
)
from tabula_rasa.http import drive_download_rehearsal as rehearsal
from tabula_rasa.http import identity_rehearsal
from tests.google_drive._support import FakeResponse, drive_settings, oauth_config

TARGET = f'{DRIVE_API_ROOT}/files/synthetic-us'


@pytest.fixture
def arguments(monkeypatch):
    for name, value in {
        'ENVIRONMENT': 'staging',
        'ACCESS_MODE': 'named_user',
        'PUBLIC_ORIGIN': 'https://app.example.test',
        'RELEASE_ID': 'a' * 40,
    }.items():
        monkeypatch.setenv('TABULA_RASA_' + name, value)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=60)
    return [
        '--expected-origin', 'https://app.example.test',
        '--expected-release', 'a' * 40,
        '--download-path-sha256', sha256(urlsplit(TARGET).path.encode()).hexdigest(),
        '--deadline-utc', deadline.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '--max-seconds', '60',
        '--acknowledge-staging-drive-download', 'approved',
    ]


def test_drive_download_fails_safely_and_recovers(arguments, monkeypatch):
    gate = rehearsal.prepare(arguments)
    us_bytes, ca_bytes = b'synthetic US receipt', b'synthetic CA receipt'

    def send(_session, request, **_kwargs):
        if request.url == TOKEN_ENDPOINT:
            return FakeResponse(200, {'access_token': 'synthetic', 'expires_in': 3600})
        if urlsplit(request.url).path.endswith('/synthetic-ca'):
            return FakeResponse(200, content=ca_bytes)
        return FakeResponse(200, content=us_bytes)

    transport = Mock(side_effect=send)
    monkeypatch.setattr(requests.Session, 'send', gate.wrap(transport))
    client = GoogleDriveClient(oauth_config(), drive_settings(), sleeper=lambda _: None)
    control = GoogleDriveClient(oauth_config(), drive_settings(
        email='control@example.test', refresh_token='control-refresh'
    ), sleeper=lambda _: None)
    with pytest.raises(GoogleDriveAccessError) as failure:
        client.download_file('synthetic-us')
    assert failure.value.retryable
    assert transport.call_count == 1
    assert control.download_file('synthetic-ca') == ca_bytes
    assert client.session.get(TARGET).content == us_bytes

    monkeypatch.setattr(identity_rehearsal.time, 'monotonic', lambda: gate.window.monotonic_end)
    assert client.download_file('synthetic-us') == us_bytes
    monkeypatch.setattr(identity_rehearsal.time, 'monotonic', lambda: 0)
    assert client.download_file('synthetic-us') == us_bytes


@pytest.mark.parametrize(('flag', 'value'), [
    ('--expected-origin', 'https://other.example.test'),
    ('--expected-release', 'b' * 40),
    ('--download-path-sha256', 'not-a-digest'),
    ('--deadline-utc', '2000-01-01T00:00:00Z'),
    ('--max-seconds', '301'),
])
def test_refuses_wrong_binding_or_invalid_window(arguments, flag, value):
    arguments[arguments.index(flag) + 1] = value
    with pytest.raises(ValueError):
        rehearsal.prepare(arguments)


def test_refuses_non_staging_environment(arguments, monkeypatch):
    monkeypatch.setenv('TABULA_RASA_ENVIRONMENT', 'production')
    with pytest.raises(ValueError):
        rehearsal.prepare(arguments)
