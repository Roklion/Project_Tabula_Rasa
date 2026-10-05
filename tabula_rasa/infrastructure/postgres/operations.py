"""Small shared transaction/error boundary for PostgreSQL adapters."""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Error as PsycopgError
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from .runtime import Database, DatabaseError, safe_database_error


def application_database_error(error: DatabaseError) -> StorageError:
    code = error.code
    if code in {"duplicate", "concurrent_write"}:
        return StorageConflictError("The operation conflicts with current data. Reload before trying again.", code=code)
    if code in {"reference", "invariant", "required"}:
        return StorageValidationError("The operation violates a bookkeeping constraint.", code=code)
    if code == "read_only":
        return StorageValidationError("This operation is read-only.", code=code)
    return StorageError("The database operation could not be confirmed. Inspect current data before trying again.", code=code)


@contextmanager
def repository_operation(
    database: Database, *, read_only: bool = False, require_outer: bool = False,
) -> Iterator[Connection]:
    """Translate after rollback; nested participants still poison the outer unit.

    Occurrence/attention operations use require_outer so a returned occurrence
    cannot be mistaken for committed work inside an all-run transaction.
    """
    try:
        with database.transaction(read_only=read_only, require_outer=require_outer) as connection:
            yield connection
    except DatabaseError as error:
        failure = application_database_error(error)
    except (SQLAlchemyError, PsycopgError) as error:
        # Nested Database boundaries defer provider translation to the outer
        # transaction. An adapter must never expose that provider exception.
        failure = application_database_error(safe_database_error(error))
    else:
        return
    try:
        raise failure from None
    except StorageError:
        failure.__context__ = None
        raise
