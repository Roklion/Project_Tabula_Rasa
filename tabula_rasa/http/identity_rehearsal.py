"""Explicit staging operator command; never imported by normal startup.

Trusted-process diagnostic only: caches, native clients and existing sockets
can bypass the resolver boundary. This is not a security sandbox.
"""

import argparse
from datetime import datetime, timezone
import math
import os
import re
import sys
import time
from urllib.parse import urlsplit

from tabula_rasa.http.config import HttpSettings
from tabula_rasa.infrastructure.oidc import OidcSettings


class ResolverDenied(OSError):
    """Fixed safe failure consumed by the existing Requests/OIDC boundary."""


def _hostname(value):
    if isinstance(value, bytes):
        value = value.decode('ascii')
    return value.rstrip('.').encode('idna').decode('ascii').lower()


class ResolverGate:
    def __init__(self, issuer, deadline, maximum_seconds):
        parsed = urlsplit(issuer)
        self.host = _hostname(parsed.hostname)
        self.port = parsed.port if parsed.port is not None else 443
        if not 1 <= self.port <= 65535 or any(character.isspace() for character in self.host):
            raise ValueError('Invalid rehearsal target.')
        now = datetime.now(timezone.utc)
        remaining = (deadline - now).total_seconds()
        if (not math.isfinite(maximum_seconds) or not 0 < maximum_seconds <= 300
                or not 0 < remaining <= maximum_seconds):
            raise ValueError('Invalid rehearsal window.')
        self.deadline = deadline
        self.monotonic_end = time.monotonic() + maximum_seconds
        self.expired = False

    def __call__(self, event, args):
        if event != 'socket.getaddrinfo' or self.expired:
            return
        if (time.monotonic() >= self.monotonic_end
                or datetime.now(timezone.utc) >= self.deadline):
            self.expired = True
            return
        host, port = args[:2]
        try:
            matches = _hostname(host) == self.host and int(port) == self.port
        except (ValueError, TypeError, AttributeError, UnicodeError):
            matches = False
        if matches:
            raise ResolverDenied('Identity rehearsal resolver unavailable.')


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse otherwise reflects arbitrary operator input into diagnostics.
        raise ValueError('Invalid rehearsal arguments.')


def prepare(argv):
    parser = _Parser(description=__doc__)
    parser.add_argument('--expected-origin', required=True)
    parser.add_argument('--expected-issuer', required=True)
    parser.add_argument('--expected-release', required=True)
    parser.add_argument('--deadline-utc', required=True)
    parser.add_argument('--max-seconds', required=True, type=float)
    parser.add_argument('--acknowledge-staging-cold-discovery', required=True,
                        choices=['approved'])
    args = parser.parse_args(argv)
    settings = HttpSettings.from_environment()
    oidc = OidcSettings.from_environment(settings, os.environ)
    if (settings.environment != 'staging' or settings.access_mode != 'named_user'
            or settings.public_origin != args.expected_origin
            or oidc.issuer != args.expected_issuer
            or not re.fullmatch(r'[0-9a-f]{40}', args.expected_release)
            or settings.release_id != args.expected_release):
        raise ValueError('Rehearsal binding mismatch.')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', args.deadline_utc):
        raise ValueError('Invalid rehearsal deadline.')
    deadline = datetime.strptime(args.deadline_utc, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    return ResolverGate(oidc.issuer, deadline, args.max_seconds)


def main(argv=None):
    try:
        gate = prepare(argv)
        sys.addaudithook(gate)
        # Existing audit hooks can silently prevent registration. Test the event
        # without doing DNS or making a network request before serving anything.
        try:
            sys.audit('socket.getaddrinfo', gate.host, gate.port, 0, 0, 0)
        except ResolverDenied:
            pass
        else:
            raise ValueError('Rehearsal gate not active.')
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise SystemExit('Identity rehearsal refused: check approved bindings and UTC window.') from None
    print('Identity rehearsal armed: cold discovery only; automatic resolver expiry enabled.', flush=True)
    from tabula_rasa.http.serve import main as serve
    serve()


if __name__ == '__main__':
    main()
