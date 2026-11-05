"""Explicit operator launcher for one synthetic staging Drive download fault."""

from datetime import datetime
from hashlib import sha256
import re
from urllib.parse import parse_qs, urlsplit

import requests

from tabula_rasa.google_drive.errors import DRIVE_API_ROOT
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.identity_rehearsal import RehearsalWindow, _Parser


class DownloadGate:
    def __init__(self, path_sha256, window):
        self.path_sha256 = path_sha256
        self.window = window
        self.root = urlsplit(DRIVE_API_ROOT)

    def wrap(self, send):
        def guarded_send(session, request, **kwargs):
            if self.window.active() and request.method == 'GET':
                target = urlsplit(request.url)
                if (target.scheme == self.root.scheme and target.netloc == self.root.netloc
                        and target.path.startswith(self.root.path + '/files/')
                        and sha256(target.path.encode()).hexdigest() == self.path_sha256
                        and parse_qs(target.query).get('alt') == ['media']):
                    raise requests.ConnectionError('Staging Drive download rehearsal unavailable.')
            return send(session, request, **kwargs)

        return guarded_send


def prepare(argv):
    parser = _Parser(description=__doc__)
    parser.add_argument('--expected-origin', required=True)
    parser.add_argument('--expected-release', required=True)
    parser.add_argument('--download-path-sha256', required=True)
    parser.add_argument('--deadline-utc', required=True)
    parser.add_argument('--max-seconds', required=True, type=float)
    parser.add_argument('--acknowledge-staging-drive-download', required=True, choices=['approved'])
    args = parser.parse_args(argv)
    settings = HttpSettings.from_environment()
    if (settings.environment != 'staging' or settings.access_mode != 'named_user'
            or settings.public_origin != args.expected_origin
            or settings.release_id != args.expected_release
            or not re.fullmatch(r'[0-9a-f]{40}', args.expected_release)
            or not re.fullmatch(r'[0-9a-f]{64}', args.download_path_sha256)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', args.deadline_utc)):
        raise ValueError('Rehearsal binding mismatch.')
    deadline = datetime.fromisoformat(args.deadline_utc)
    return DownloadGate(args.download_path_sha256, RehearsalWindow(deadline, args.max_seconds))


def main(argv=None):
    try:
        gate = prepare(argv)
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise SystemExit('Drive rehearsal refused: check approved bindings and UTC window.') from None
    requests.Session.send = gate.wrap(requests.Session.send)
    print('Drive rehearsal armed: one download path; automatic expiry enabled.', flush=True)
    from tabula_rasa.http.serve import main as serve

    serve()


if __name__ == '__main__':
    main()
