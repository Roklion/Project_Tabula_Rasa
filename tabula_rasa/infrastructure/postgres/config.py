"""Explicit database configuration, separate from legacy profile secrets."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(ValueError):
    """A configuration failure with no credential-bearing detail."""


@dataclass(frozen=True)
class DatabaseSettings:
    url: URL = field(repr=False)
    connect_timeout: int = 5
    pool_size: int = 5
    max_overflow: int = 5

    def __post_init__(self) -> None:
        if (
            self.url.drivername != "postgresql+psycopg"
            or not self.url.database
            or not 1 <= self.connect_timeout <= 60
            or not 1 <= self.pool_size <= 50
            or not 0 <= self.max_overflow <= 50
        ):
            raise DatabaseConfigurationError("Invalid PostgreSQL settings.")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None, *, required: bool = False,
    ) -> "DatabaseSettings | None":
        values = os.environ if environ is None else environ
        raw = values.get("TABULA_DATABASE_URL", "").strip()
        if not raw:
            if required:
                raise DatabaseConfigurationError("Set TABULA_DATABASE_URL to use PostgreSQL.")
            return None
        try:
            url = make_url(raw)
            if url.drivername == "postgresql":
                url = url.set(drivername="postgresql+psycopg")
            # Operational settings have dedicated bounded options; URL options
            # are limited to transport security, never echo/logging or SQL.
            if set(url.query) - {"sslmode", "sslrootcert", "sslcert", "sslkey"}:
                raise ValueError
            return cls(
                url=url,
                connect_timeout=int(values.get("TABULA_DATABASE_CONNECT_TIMEOUT", "5")),
                pool_size=int(values.get("TABULA_DATABASE_POOL_SIZE", "5")),
                max_overflow=int(values.get("TABULA_DATABASE_MAX_OVERFLOW", "5")),
            )
        except (ArgumentError, TypeError, ValueError):
            pass
        # Raise outside the handler so the public error does not retain a raw
        # parser exception (which may contain the credential-bearing URL).
        raise DatabaseConfigurationError("Invalid PostgreSQL settings.")
