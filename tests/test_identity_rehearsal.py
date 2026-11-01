"""Operator binding checks and real TLS transport in an isolated interpreter."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests

from tabula_rasa.http import identity_rehearsal as rehearsal


@pytest.fixture
def arguments(monkeypatch):
    values = dict(ENVIRONMENT='staging', ACCESS_MODE='named_user',
                  PUBLIC_ORIGIN='https://app.example.test', RELEASE_ID='a' * 40,
                  OIDC_ISSUER='https://id.example.test', OIDC_CLIENT_ID='synthetic-client',
                  OIDC_CLIENT_SECRET='synthetic-secret', SESSION_GENERATION='s' * 64)
    for key, value in values.items():
        monkeypatch.setenv('TABULA_RASA_' + key, value)
    for key in ('TRUSTED_ENTITY_ID', 'ALPHA_USERNAME', 'ALPHA_PASSWORD_HASH'):
        monkeypatch.delenv('TABULA_RASA_' + key, raising=False)
    deadline = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return ['--expected-origin', values['PUBLIC_ORIGIN'], '--expected-issuer', values['OIDC_ISSUER'],
            '--expected-release', values['RELEASE_ID'], '--deadline-utc', deadline,
            '--max-seconds', '60', '--acknowledge-staging-cold-discovery', 'approved']


def test_bindings_preserved_and_matching_normalized(arguments, monkeypatch):
    monkeypatch.setenv('TABULA_RASA_OIDC_ISSUER', 'https://ID.example.test:443')
    arguments[3] = 'https://ID.example.test:443'
    gate = rehearsal.prepare(arguments)
    for host in ('id.example.test', b'ID.example.test', 'id.example.test.'):
        with pytest.raises(rehearsal.ResolverDenied):
            gate('socket.getaddrinfo', (host, 443))
    gate('socket.getaddrinfo', ('id.example.test', 444))
    gate('socket.getaddrinfo', ('other.example.test', 443))
    gate('socket.connect', ('id.example.test', 443))
    assert rehearsal.os.environ['TABULA_RASA_OIDC_ISSUER'] == arguments[3]


@pytest.mark.parametrize('issuer', ['https://faß.example', 'https://faß.example:8443',
                                  'https://xn--fa-hia.example', 'https://[::1]:8443'])
def test_gate_matches_hostname_prepared_by_requests(arguments, monkeypatch, issuer):
    monkeypatch.setenv('TABULA_RASA_OIDC_ISSUER', issuer)
    arguments[3] = issuer
    gate = rehearsal.prepare(arguments)
    prepared = requests.Request('GET', issuer + '/.well-known/openid-configuration').prepare()
    target = urlsplit(prepared.url)
    port = target.port or 443
    with pytest.raises(rehearsal.ResolverDenied):
        gate('socket.getaddrinfo', (target.hostname, port, 0, 0, 0))
    gate('socket.getaddrinfo', (target.hostname, port + 1, 0, 0, 0))
    gate('socket.getaddrinfo', ('unrelated.example', port, 0, 0, 0))
    assert rehearsal.os.environ['TABULA_RASA_OIDC_ISSUER'] == issuer


@pytest.mark.parametrize('key,value', [('ENVIRONMENT', 'production'), ('ENVIRONMENT', ''),
    ('ACCESS_MODE', 'restricted_alpha'), ('OIDC_ISSUER', ''), ('OIDC_ISSUER', 'https://id.example.test:bad'),
    ('OIDC_CLIENT_SECRET', ''), ('SESSION_GENERATION', ''), ('RELEASE_ID', 'b' * 40),
    ('PUBLIC_ORIGIN', 'https://different.example.test')])
def test_refuses_configuration_mismatch(arguments, monkeypatch, key, value):
    monkeypatch.setenv('TABULA_RASA_' + key, value)
    with pytest.raises(ValueError):
        rehearsal.prepare(arguments)


@pytest.mark.parametrize('flag,value', [('--deadline-utc', '2030-01-01T00:00:00Z'),
    ('--deadline-utc', '2020-01-01T00:00:00Z'), ('--deadline-utc', '2030-01-01T00:00:00+00:00'),
    ('--deadline-utc', 'private-invalid'), ('--max-seconds', '301'), ('--max-seconds', '0'),
    ('--max-seconds', 'nan'), ('--max-seconds', 'inf'), ('--max-seconds', '1'),
    ('--acknowledge-staging-cold-discovery', 'no'), ('--expected-issuer', 'https://other.test')])
def test_invalid_window_or_acknowledgement(arguments, flag, value):
    arguments[arguments.index(flag) + 1] = value
    with pytest.raises(ValueError):
        rehearsal.prepare(arguments)


def test_monotonic_expiry_latches_even_if_wall_clock_moves_back(arguments, monkeypatch):
    gate = rehearsal.prepare(arguments)
    monkeypatch.setattr(rehearsal.time, 'monotonic', lambda: gate.monotonic_end)
    gate('socket.getaddrinfo', (gate.host, gate.port))
    monkeypatch.setattr(rehearsal.time, 'monotonic', lambda: 0)
    gate('socket.getaddrinfo', (gate.host, gate.port))
    assert gate.expired


def test_absolute_expiry_and_expired_process_restart(arguments, monkeypatch):
    gate = rehearsal.prepare(arguments)
    class ExpiredClock:
        @staticmethod
        def now(zone):
            return gate.deadline
    monkeypatch.setattr(rehearsal, 'datetime', ExpiredClock)
    gate('socket.getaddrinfo', (gate.host, gate.port))
    assert gate.expired
    arguments[arguments.index('--deadline-utc') + 1] = '2020-01-01T00:00:00Z'
    result = subprocess.run([sys.executable, '-m', 'tabula_rasa.http.identity_rehearsal', *arguments],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert 'Identity rehearsal refused' in result.stderr
    assert 'armed' not in result.stdout


def test_launcher_installs_then_calls_normal_serve(arguments, monkeypatch, capsys):
    from tabula_rasa.http import serve
    installed = []
    monkeypatch.setattr(rehearsal.sys, 'addaudithook', installed.append)
    monkeypatch.setattr(rehearsal.sys, 'audit', lambda event, *args: installed[0](event, args))
    called = Mock()
    monkeypatch.setattr(serve, 'main', called)
    rehearsal.main(arguments)
    called.assert_called_once_with()
    assert 'id.example.test' not in capsys.readouterr().out


def test_refusal_does_not_echo_input_or_start_server(arguments, monkeypatch):
    from tabula_rasa.http import serve
    called = Mock()
    monkeypatch.setattr(serve, 'main', called)
    for args in (['--private-secret'], arguments[:-1] + ['private-secret']):
        with pytest.raises(SystemExit) as caught:
            rehearsal.main(args)
        assert 'private-secret' not in str(caught.value)
    monkeypatch.setattr(rehearsal.sys, 'addaudithook', lambda _: None)
    with pytest.raises(SystemExit):
        rehearsal.main(arguments)
    called.assert_not_called()


def test_real_tls_resolver_boundary_in_fresh_process():
    result = subprocess.run([sys.executable, '-m', 'tests._identity_rehearsal_scenario'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_tls_setup_failure_exits_without_cleanup_hang():
    result = subprocess.run([sys.executable, '-c',
        "import runpy, ssl; from unittest.mock import patch; "
        "failure = patch.object(ssl.SSLContext, 'load_cert_chain', side_effect=ValueError('synthetic setup failure')); "
        "failure.start(); runpy.run_module('tests._identity_rehearsal_scenario', run_name='__main__')"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'synthetic_TLS_fixture' in result.stdout
    assert '"error_types": ["ValueError"]' in result.stdout
    assert not result.stderr


def test_normal_startup_does_not_import_rehearsal():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import tabula_rasa.http.serve; "
        "assert 'tabula_rasa.http.identity_rehearsal' not in sys.modules"],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
