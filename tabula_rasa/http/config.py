"""Process-only HTTP settings. Schema export never loads settings/secrets."""

from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HttpSettings:
    environment: str
    public_origin: str
    release_id: str = "development"
    trusted_entity_id: str | None = None

    def __post_init__(self):
        origin = urlsplit(self.public_origin)
        valid = (
            self.environment in {"development", "test", "staging", "production"}
            and origin.scheme in {"http", "https"} and bool(origin.hostname)
            and not origin.username and not origin.password
            and not origin.path and not origin.query and not origin.fragment
            and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", self.release_id)
        )
        if not valid:
            raise ValueError("Invalid HTTP configuration.")
        if self.environment in {"staging", "production"} and origin.scheme != "https":
            raise ValueError("Hosted HTTP requires HTTPS.")
        if self.trusted_entity_id and (
            self.environment not in {"development", "test"}
            or origin.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}
            or (origin.hostname == "testserver" and self.environment != "test")
        ):
            raise ValueError("Trusted fixture context requires explicit loopback development/test.")
        if self.trusted_entity_id and not self.trusted_entity_id.strip():
            raise ValueError("An explicit synthetic entity is required.")

    @classmethod
    def from_environment(cls):
        return cls(
            os.environ.get("TABULA_RASA_ENVIRONMENT", ""),
            os.environ.get("TABULA_RASA_PUBLIC_ORIGIN", ""),
            os.environ.get("TABULA_RASA_RELEASE_ID", "development"),
            os.environ.get("TABULA_RASA_TRUSTED_ENTITY_ID") or None,
        )
