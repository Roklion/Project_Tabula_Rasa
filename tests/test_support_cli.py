"""Support HTTP client never exposes authentication or upstream error text."""
import json
from unittest.mock import Mock

import pytest

from scripts import support_diagnostics as cli


def client(monkeypatch, *, status=200, content=b'{"safe":"metadata"}'):
    response = Mock(status_code=status)
    response.raw.read.return_value = content
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    monkeypatch.setattr(cli.requests, 'Session', lambda: session)
    monkeypatch.setattr(cli, 'getpass', lambda *_: 'synthetic-private-cookie')
    return session


def arguments(operation='diagnostics'):
    return [operation, '--origin', 'https://support.example.test', '--organization', 'approved-org',
            '--entity', 'approved-entity', '--reason', 'incident']


def test_read_client_uses_named_session_csrf_bounded_response_and_no_redirects(monkeypatch, capsys):
    session = client(monkeypatch)
    assert cli.main(arguments()) == 0
    assert json.loads(capsys.readouterr().out) == {'safe': 'metadata'}
    call = session.post.call_args
    assert call.args[0].endswith('/approved-org/approved-entity/diagnostics')
    assert call.kwargs['json'] == {'reason': 'incident'}
    assert call.kwargs['cookies'] == {'__Host-tabula_session': 'synthetic-private-cookie'}
    assert call.kwargs['headers']['x-csrf-token'] == 'synthetic-private-cookie'
    assert call.kwargs['allow_redirects'] is False and session.trust_env is False


@pytest.mark.parametrize('status,content', [(403, b'private SQL secret'), (302, b'private redirect'),
                                           (500, b'private traceback'), (200, b'x' * 1048577)], ids=['denied', 'redirect', 'server-error', 'oversized'])
def test_failures_do_not_echo_sensitive_upstream_content(monkeypatch, capsys, status, content):
    client(monkeypatch, status=status, content=content)
    assert cli.main(arguments()) == 1
    result = capsys.readouterr().out
    assert json.loads(result)['error'] == 'support_refused'
    assert 'private' not in result


def test_privileged_cli_previews_without_confirmation_and_passes_explicit_confirmation(monkeypatch):
    session = client(monkeypatch)
    args = arguments('suspend_member') + ['--target-user', 'approved-user']
    assert cli.main(args) == 0
    assert session.post.call_args.kwargs['json']['confirm_plan'] is None
    assert cli.main(args + ['--confirm-plan', 'a' * 64]) == 0
    assert session.post.call_args.kwargs['json']['confirm_plan'] == 'a' * 64


@pytest.mark.parametrize('origin', ['http://public.example.test', 'https://user:password@example.test',
                                  'https://example.test/path', 'https://example.test?secret=value'])
def test_cli_rejects_unsafe_origins_before_prompting(monkeypatch, origin):
    prompt = Mock(side_effect=AssertionError('must not prompt'))
    monkeypatch.setattr(cli, 'getpass', prompt)
    args = arguments()
    args[2] = origin
    with pytest.raises(SystemExit):
        cli.main(args)
    prompt.assert_not_called()
