"""Real PostgreSQL only; never fall back to the application's DB URL."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.migrations import upgrade
from tabula_rasa.infrastructure.postgres.runtime import Database


@pytest.fixture
def empty_database():
    raw = os.environ.get("TABULA_RASA_TEST_DATABASE_URL", "")
    if not raw:
        if os.environ.get('TABULA_RASA_REQUIRE_BROWSER_TESTS') == '1':
            pytest.fail("Set TABULA_RASA_TEST_DATABASE_URL for the required native browser gate.")
        pytest.skip("Set TABULA_RASA_TEST_DATABASE_URL for real PostgreSQL integration tests.")
    settings = DatabaseSettings.from_environment({"TABULA_RASA_DATABASE_URL": raw}, required=True)
    name = "tabula_test_" + uuid4().hex
    # Constructed here, never from a profile, URL or external input.
    admin = create_engine(settings.url, isolation_level="AUTOCOMMIT", poolclass=NullPool,
                          hide_parameters=True, echo=False)
    created = False
    database = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        database = Database(DatabaseSettings(settings.url.set(database=name)))
        yield database
    finally:
        if database is not None:
            database.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


@pytest.fixture
def database(empty_database):
    upgrade(empty_database)
    return empty_database
