"""Encrypted operator-provisioned grants, independent of login and SQL exports."""
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from cryptography.fernet import Fernet

from tabula_rasa.application.identity import IdentityError


class ConnectionSecrets:
    """Key comes from environment secret injection; directory holds ciphertext only.

    Provisioning is an explicit operator action. Runtime needs read-only directory
    access. Never accept a path/key/reference from browser transport.
    """
    def __init__(self, directory, key):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise IdentityError('unavailable')
        try:
            self._cipher = Fernet(key.encode())
        except Exception:
            pass
        else:
            return
        raise IdentityError('unavailable')

    @classmethod
    def from_environment(cls, environment):
        directory = environment.get('TABULA_RASA_CONNECTION_SECRETS_DIR', '')
        key = environment.get('TABULA_RASA_CONNECTION_SECRETS_KEY', '')
        if not directory and not key:
            return None
        return cls(directory, key)

    def _path(self, reference, *, reading=False):
        if not isinstance(reference, str) or not re.fullmatch('[0-9a-f]{32}', reference):
            raise IdentityError('unavailable')
        path = self.directory / (reference + '.grant')
        if reading:
            # Mounted secrets can point into a versioned child directory. Resolve
            # once, retain containment, then open that regular target without
            # following a replacement leaf symlink. The root is operator-owned.
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(self.directory.resolve(strict=True)):
                raise IdentityError('unavailable')
            return resolved
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise IdentityError('unavailable')
        return path

    def put(self, payload):
        """No replacement/overwrite; failed registration leaves recoverable ciphertext."""
        # Render secret filenames must start with a letter. Keep the existing
        # 32-hex format, including support for previously provisioned references.
        reference = uuid4().hex
        while not reference[0].isalpha():
            reference = uuid4().hex
        try:
            content = self._cipher.encrypt(json.dumps(payload).encode())
            descriptor = os.open(self._path(reference), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as output:
                output.write(content)
            return reference
        except Exception:
            pass
        raise IdentityError('unavailable')

    def get(self, reference, *, environment, organization_id, entity_id, provider):
        try:
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            descriptor = os.open(self._path(reference, reading=True), flags)
            try:
                source = os.fdopen(descriptor, 'rb')
            except Exception:
                os.close(descriptor)
                raise
            with source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError
                content = source.read(131073)
            if len(content) > 131072:
                raise ValueError
            payload = json.loads(self._cipher.decrypt(content))
            expected = dict(environment=environment, organization_id=organization_id,
                            entity_id=entity_id, provider=provider)
            if any(payload.get(key) != value for key, value in expected.items()):
                raise ValueError
            return payload
        except Exception:
            pass
        # No original exception/context survives; never surface paths or tokens.
        raise IdentityError('unavailable')
