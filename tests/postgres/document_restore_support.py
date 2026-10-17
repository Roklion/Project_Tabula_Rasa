"""Isolated synthetic PostgreSQL snapshot clone; never touches application DB URLs."""
from contextlib import contextmanager
import re
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.runtime import Database


@contextmanager
def cloned_database(source):
    original = source.engine.url.database
    if not re.fullmatch('tabula_test_[0-9a-f]{32}', original):
        raise ValueError('Snapshot cloning is restricted to disposable test databases.')
    name = 'tabula_restore_' + uuid4().hex
    source.dispose()
    admin = create_engine(source.engine.url.set(database='postgres'), isolation_level='AUTOCOMMIT',
                          poolclass=NullPool, hide_parameters=True)
    restored = None
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE "{original}"')
        created = True
        restored = Database(DatabaseSettings(source.engine.url.set(database=name)))
        yield restored
    finally:
        if restored is not None:
            restored.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()
