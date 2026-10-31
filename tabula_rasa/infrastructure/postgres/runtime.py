"""Infrastructure-owned connections and supported-operation boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn
from uuid import uuid4

from psycopg import Error as PsycopgError
from psycopg.pq import TransactionStatus
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as PoolTimeoutError

from .config import DatabaseSettings


class DatabaseError(RuntimeError):
    """Safe failure code; never retain SQL, parameters, or driver messages."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"PostgreSQL operation failed ({code}).")


def safe_database_error(error: SQLAlchemyError | PsycopgError) -> DatabaseError:
    state = getattr(getattr(error, "orig", error), "sqlstate", None)
    codes = {
        "23505": "duplicate", "23503": "reference", "23514": "invariant",
        "23502": "required", "40001": "concurrent_write", "40P01": "concurrent_write",
        "25006": "read_only", "55P03": "concurrent_write",
        "55000": "backend_inactive",
        "TR423": "period_closed", "TR403": "forbidden", "TR409": "conflict",
        "53300": "database_exhausted",
    }
    return DatabaseError("database_exhausted" if isinstance(error, PoolTimeoutError) else codes.get(state, "unavailable"))


def raise_database_error(failure: DatabaseError) -> NoReturn:
    # contextlib throws the provider exception into the generator while its
    # caller is still handling it. Clear that implicit context before re-raise.
    try:
        raise failure from None
    except DatabaseError:
        failure.__context__ = None
        raise


@dataclass
class _Operation:
    connection: Connection
    read_only: bool
    failed: bool = False


class Database:
    """One pool. Repositories composed with this instance join its operation.

    Connections stay inside infrastructure adapters. Services still consume
    repository records. No mutation retries or post-success readbacks occur.
    """

    def __init__(self, settings: DatabaseSettings, *, statement_timeout_ms=None):
        if statement_timeout_ms is not None and (type(statement_timeout_ms) is not int or not 1 <= statement_timeout_ms <= 30000):
            raise ValueError('Invalid statement timeout.')
        connect_args = {"connect_timeout": settings.connect_timeout}
        if statement_timeout_ms is not None:
            connect_args['options'] = f'-c statement_timeout={statement_timeout_ms}'
        self.engine = create_engine(
            settings.url,
            pool_pre_ping=True,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            echo=False,
            hide_parameters=True,
            connect_args=connect_args,
        )
        self._operation: ContextVar[_Operation | None] = ContextVar(
            "tabula_postgres_operation", default=None,
        )
        from .audit import INTERNAL_AUDIT
        self._audit_context = ContextVar('tabula_postgres_audit_context', default=INTERNAL_AUDIT)

    @contextmanager
    def transaction(
        self, *, read_only: bool = False, require_outer: bool = False,
    ) -> Iterator[Connection]:
        current = self._operation.get()
        if current is not None:
            if require_outer or (current.read_only and not read_only):
                current.failed = True
                raise DatabaseError("boundary_mismatch")
            try:
                yield current.connection
            except BaseException:
                current.failed = True
                raise
            return
        try:
            with self.engine.connect() as connection:
                if read_only:
                    connection = connection.execution_options(isolation_level="REPEATABLE READ")
                with connection.begin():
                    # UTC is for instants only; SQL date retains calendar meaning.
                    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                    if read_only:
                        connection.execute(text("SET TRANSACTION READ ONLY"))
                    else:
                        from .audit import configure_audit
                        configure_audit(connection, self._audit_context.get(), uuid4().hex)
                    operation = _Operation(connection, read_only)
                    token = self._operation.set(operation)
                    try:
                        yield connection
                        if (operation.failed or connection.connection.driver_connection.info.transaction_status
                                == TransactionStatus.INERROR):
                            raise DatabaseError("operation_aborted")
                    finally:
                        self._operation.reset(token)
        except (SQLAlchemyError, PsycopgError) as error:
            failure = safe_database_error(error)
        else:
            return
        # Suppressing display with `from None` still retains __context__. Drop
        # the provider exception entirely before exposing the safe failure.
        raise_database_error(failure)

    def dispose(self) -> None:
        """Release pooled resources on worker/test shutdown."""
        self.engine.dispose()

    def health(self) -> dict[str, object]:
        from .migrations import current_revision

        try:
            with self.transaction(read_only=True) as connection:
                connection.execute(text("SELECT 1"))
                revision = current_revision(connection)
            return {"connected": True, "revision": revision}
        except DatabaseError as error:
            return {"connected": False, "code": error.code}
