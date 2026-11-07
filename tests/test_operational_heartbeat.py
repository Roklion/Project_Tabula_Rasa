from unittest.mock import MagicMock
from urllib.error import URLError

import pytest

from scripts import operational_heartbeat as heartbeat


URL = 'https://incidents.betterstack.com/api/v1/heartbeat/synthetic-token'


@pytest.mark.parametrize('healthy,suffix', [(True, ''), (False, '/fail')])
def test_checkin_has_no_operational_payload_and_uses_bounded_timeout(healthy, suffix):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.status = 204
    heartbeat.signal(URL, healthy, opener=opener)
    request = opener.open.call_args.args[0]
    assert request.full_url == URL + suffix
    assert request.method == 'GET' and request.data is None
    assert opener.open.call_args.kwargs == {'timeout': 10}


@pytest.mark.parametrize('url', [
    URL.replace('https:', 'http:'),
    URL.replace('incidents.betterstack.com', 'other.example'),
    URL.replace('incidents.betterstack.com', 'incidents.betterstack.com:444'),
    URL.replace('incidents.betterstack.com', 'name:password@incidents.betterstack.com'),
    URL + '?private=data', URL + '#private', URL + '/fail',
])
def test_non_approved_destination_is_refused_before_contact(url):
    opener = MagicMock()
    with pytest.raises(ValueError):
        heartbeat.signal(url, True, opener=opener)
    opener.open.assert_not_called()


@pytest.mark.parametrize('status', [199, 301, 400, 500])
def test_non_success_status_does_not_confirm_delivery(status):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.status = status
    with pytest.raises(URLError):
        heartbeat.signal(URL, True, opener=opener)


def test_default_opener_disables_redirects(monkeypatch):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.status = 200
    build = MagicMock(return_value=opener)
    monkeypatch.setattr(heartbeat, 'build_opener', build)
    heartbeat.signal(URL, True)
    handler = build.call_args.args[0]
    assert isinstance(handler, heartbeat.NoRedirects)
    with pytest.raises(URLError):
        handler.redirect_request(None, None, 302, '', {}, 'https://other.example')


def test_transport_failure_is_not_successful_delivery():
    opener = MagicMock()
    opener.open.side_effect = URLError('synthetic transport failure')
    with pytest.raises(URLError):
        heartbeat.signal(URL, True, opener=opener)
