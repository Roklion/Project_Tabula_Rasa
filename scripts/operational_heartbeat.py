"""Explicit payload-free operational check-in to an approved Better Stack URL."""

import re
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise URLError('Heartbeat redirect refused.')


def signal(url, healthy, *, opener=None):
    """Send only the approved heartbeat token; never attach operational data."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'incidents.betterstack.com'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not re.fullmatch(
                r'/api/v1/heartbeat/[A-Za-z0-9_-]{8,256}', parsed.path)):
        raise ValueError('Invalid heartbeat destination.')
    request = Request(url if healthy else url + '/fail', method='GET',
        headers={'User-Agent': 'Tabula-Rasa-Recurring-Monitor'})
    with (opener or build_opener(NoRedirects())).open(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise URLError('Heartbeat not confirmed.')
