"""Temporary deployment-wide operator gate; #222 owns commercial sessions."""

import base64
import binascii
from hashlib import scrypt
from hmac import compare_digest
import re
import secrets

from .errors import error_response


HASH_PATTERN = re.compile(r"scrypt\$([0-9a-f]{32})\$([0-9a-f]{64})")
PUBLIC_PROBES = frozenset({"/health/live", "/health/ready", "/version"})


def password_hash(password):
    if not password:
        raise ValueError("Alpha password must not be empty.")
    salt = secrets.token_bytes(16)
    digest = scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def gate_response(request, settings):
    """Return a challenge or mark this request authenticated before routing."""
    request.state.alpha_authenticated = False
    if not settings.hosted_alpha or request.url.path in PUBLIC_PROBES:
        return None
    valid = False
    header = request.headers.get("authorization", "")
    try:
        scheme, encoded = header.split(" ", 1)
        if scheme.lower() == "basic" and len(encoded) <= 2048:
            username, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
            if not password:
                raise ValueError("Alpha password must not be empty.")
            salt, expected = HASH_PATTERN.fullmatch(settings.alpha_password_hash).groups()
            digest = scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
            valid = (compare_digest(username.encode(), settings.alpha_username.encode())
                     & compare_digest(digest, bytes.fromhex(expected)))
    except (ValueError, UnicodeError, binascii.Error):
        pass
    if valid:
        request.state.alpha_authenticated = True
        return None
    response = error_response(request, "unauthorized")
    response.headers["WWW-Authenticate"] = 'Basic realm="Tabula Rasa technical alpha", charset="UTF-8"'
    return response


if __name__ == "__main__":
    from getpass import getpass
    try:
        print(password_hash(getpass("Environment-specific alpha password: ")))
    except ValueError:
        raise SystemExit("Alpha password must not be empty.") from None
