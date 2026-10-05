"""Portable loaded-record metadata; tokens confer no authorization."""

import base64
import binascii
from dataclasses import dataclass
import json

from tabula_rasa.errors import StorageValidationError


@dataclass(frozen=True, repr=False)
class RecordBaseline:
    entity_id: str
    kind: str
    record_id: str
    incarnation_id: str
    version: int

    def __post_init__(self):
        if (any(not isinstance(value, str) or not value.strip() for value in (
                self.entity_id, self.kind, self.record_id, self.incarnation_id,
        )) or type(self.version) is not int or not 0 < self.version < 2**63):
            raise StorageValidationError("Invalid loaded-record baseline", code="baseline_invalid")

    def encode(self) -> str:
        payload = json.dumps([
            self.entity_id, self.kind, self.record_id, self.incarnation_id, self.version,
        ], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return "v1." + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, token: str) -> "RecordBaseline":
        try:
            if not isinstance(token, str) or not token.startswith("v1."):
                raise ValueError
            encoded = token[3:]
            payload = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True,
            )
            values = json.loads(payload)
            if not isinstance(values, list) or len(values) != 5:
                raise ValueError
            return cls(*values)
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            pass
        # Leave the decoder's exception handler before raising so its payload
        # never remains attached as exception context.
        raise StorageValidationError("Invalid loaded-record baseline", code="baseline_invalid")
