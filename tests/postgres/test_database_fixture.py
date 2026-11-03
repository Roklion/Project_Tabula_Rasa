"""Verify cleanup of fixture-owned databases when tests leave connections open."""

from contextlib import ExitStack

import pytest
from sqlalchemy import text

from tests.postgres.conftest import _test_database


def test_database_cleanup_preserves_failure_with_checked_out_connection(database):
    with ExitStack() as connections:
        with pytest.raises(RuntimeError, match="test failed"):
            with _test_database(template=database.engine.url.database) as clone:
                name = clone.engine.url.database
                connection = connections.enter_context(clone.engine.connect())
                assert connection.scalar(text("SELECT 1")) == 1
                connection.commit()
                raise RuntimeError("test failed")

    with database.engine.connect() as connection:
        assert not connection.scalar(
            text("SELECT EXISTS (SELECT FROM pg_database WHERE datname = :name)"),
            {"name": name},
        )
