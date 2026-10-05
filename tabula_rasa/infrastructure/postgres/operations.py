"""Small shared transaction/error boundary for PostgreSQL adapters."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager

from psycopg import Error as PsycopgError
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from .runtime import Database, DatabaseError, safe_database_error
from .concurrency import AggregateKey, check_baseline, lock_aggregates


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


@contextmanager
def guarded_mutation(
    database: Database, entity_id: str, keys: Iterable[AggregateKey], *,
    expected: Mapping[AggregateKey, str | None], require_baselines: bool = True,
) -> Iterator[tuple[Connection, dict[AggregateKey, Mapping[str, object]]]]:
    """Check the whole selected entity/bulk baseline set before yielding writes.

    Keys include every root this operation changes. Commercial composition
    leaves require_baselines enabled; the explicit legacy/internal path may
    disable it, while retaining fresh locks and supplied-token checks.
    Domain/reference validation remains the adapter's responsibility.
    """
    selected = set(keys)
    if (not isinstance(entity_id, str) or not entity_id.strip()
            or any(key.entity_id != entity_id for key in selected)
            or set(expected) - selected):
        raise StorageValidationError("Invalid mutation scope.", code="baseline_invalid")
    with repository_operation(database) as connection:
        rows = lock_aggregates(connection, selected)
        for key, row in rows.items():
            check_baseline(key, row, expected.get(key), required=require_baselines)
        yield connection, rows
