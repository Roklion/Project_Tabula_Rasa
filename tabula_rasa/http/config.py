"""Process-only HTTP settings. Schema export never loads settings/secrets."""

from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit

from .alpha import HASH_PATTERN


@dataclass(frozen=True)
class HttpSettings:
    environment: str
    public_origin: str
    release_id: str = "development"
    trusted_entity_id: str | None = None
    alpha_username: str = field(default="", repr=False)
    alpha_password_hash: str = field(default="", repr=False)
    access_mode: str = "restricted_alpha"

    @property
    def hosted_alpha(self):
        origin = urlsplit(self.public_origin)
        return bool(self.trusted_entity_id) and origin.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}

    def __post_init__(self):
        origin = urlsplit(self.public_origin)
        try:
            port = origin.port
        except ValueError:
            raise ValueError("Invalid HTTP configuration.") from None
        valid = (
            self.environment in {"development", "test", "staging", "production"}
            and origin.scheme in {"http", "https"} and bool(origin.hostname)
            and not origin.username and not origin.password
            and not origin.path and not origin.query and not origin.fragment
            and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", self.release_id)
        )
        if not valid:
            raise ValueError("Invalid HTTP configuration.")
        # Share the browser's origin spelling across CSRF, Host and OIDC
        # callback/configuration binding; do not relax incoming Origin checks.
        host = origin.hostname
        if ':' in host:
            host = '[' + host + ']'
        suffix = f':{port}' if port is not None and port != {'http': 80, 'https': 443}[origin.scheme] else ''
        object.__setattr__(self, 'public_origin', f'{origin.scheme}://{host}{suffix}')
        if self.access_mode not in {"restricted_alpha", "named_user"}:
            raise ValueError("An explicit supported access mode is required.")
        if self.environment == "production" and self.access_mode != "named_user":
            raise ValueError("Production requires explicit named-user access mode.")
        if self.access_mode == "named_user" and (self.trusted_entity_id or self.alpha_username or self.alpha_password_hash):
            raise ValueError("Named-user mode rejects synthetic context and alpha credentials.")
        if self.environment in {"staging", "production"} and origin.scheme != "https":
            raise ValueError("Hosted HTTP requires HTTPS.")
        hosted = origin.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}
        if self.access_mode == "named_user" and (hosted and origin.scheme != "https"
                or origin.hostname == "testserver" and self.environment != "test"):
            raise ValueError("Named-user cookies require HTTPS except explicit loopback development/test.")
        if self.environment == "production" and (self.trusted_entity_id or self.alpha_username or self.alpha_password_hash):
            raise ValueError("Production rejects alpha context and credentials.")
        if hosted and self.environment != "production" and self.access_mode != "named_user":
            if (self.environment not in {"development", "staging"} or origin.scheme != "https"
                    or self.trusted_entity_id != "alpha-synthetic"
                    or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", self.alpha_username)
                    or not HASH_PATTERN.fullmatch(self.alpha_password_hash)):
                raise ValueError("Hosted alpha requires HTTPS and explicit synthetic scope/gate configuration.")
        elif self.trusted_entity_id and (
            self.environment not in {"development", "test"}
            or (origin.hostname == "testserver" and self.environment != "test")
        ):
            raise ValueError("Trusted fixture context requires explicit loopback development/test.")
        if self.trusted_entity_id and not self.trusted_entity_id.strip():
            raise ValueError("An explicit synthetic entity is required.")

    @classmethod
    def from_environment(cls):
        origin = os.environ.get("TABULA_RASA_PUBLIC_ORIGIN", "")
        mode = os.environ.get("TABULA_RASA_ACCESS_MODE", "")
        if not mode:
            if urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
                raise ValueError("Hosted HTTP requires an explicit access mode.")
            mode = "restricted_alpha"
        return cls(
            os.environ.get("TABULA_RASA_ENVIRONMENT", ""),
            origin,
            os.environ.get("TABULA_RASA_RELEASE_ID", "development"),
            os.environ.get("TABULA_RASA_TRUSTED_ENTITY_ID") or None,
            os.environ.get("TABULA_RASA_ALPHA_USERNAME", ""),
            os.environ.get("TABULA_RASA_ALPHA_PASSWORD_HASH", ""),
            mode,
        )
