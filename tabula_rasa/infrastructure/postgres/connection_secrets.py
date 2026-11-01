"""Shared ciphertext persistence for the existing tenant-bound grant envelopes.

Provision in a dedicated credential database, outside bookkeeping migrations,
exports and recovery. Runtime may only SELECT/INSERT; never create or overwrite.
"""
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets

from .config import DatabaseSettings


class PostgresConnectionSecrets(ConnectionSecrets):
    def __init__(self, database_url, key):
        try:
            self._cipher = Fernet(key.encode())
            settings = DatabaseSettings.from_environment(
                {'TABULA_RASA_DATABASE_URL': database_url}, required=True)
            if (settings.url.host not in {'localhost', '127.0.0.1', '::1'}
                    and settings.url.query.get('sslmode') not in {'require', 'verify-ca', 'verify-full'}):
                raise ValueError
            # No idle credential connections per replica; each operation closes
            # its connection. Keep this separate from ledger transactions/locks.
            self.engine = create_engine(settings.url, poolclass=NullPool,
                echo=False, hide_parameters=True,
                connect_args={'connect_timeout': 5, 'options': '-c statement_timeout=5000'})
        except Exception:
            pass
        else:
            return
        raise IdentityError('unavailable')

    def _write_ciphertext(self, reference, content):
        with self.engine.begin() as connection:
            connection.execute(text('INSERT INTO connection_custody.grants (reference,ciphertext) '
                                    'VALUES (:reference,:ciphertext)'),
                               {'reference': reference, 'ciphertext': content})

    def _read_ciphertext(self, reference):
        with self.engine.connect() as connection:
            content = connection.scalar(text('SELECT ciphertext FROM connection_custody.grants '
                                             'WHERE reference=:reference'), {'reference': reference})
        if content is None:
            raise ValueError
        return bytes(content)
