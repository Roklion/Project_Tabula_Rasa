"""Explicit fixed synthetic fixture; never executed on application startup."""

import os

from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository
from tabula_rasa.infrastructure.postgres.runtime import Database

from .config import HttpSettings


def main():
    settings = HttpSettings.from_environment()
    if settings.environment != "development" or settings.trusted_entity_id != "alpha-synthetic":
        raise SystemExit("Seed requires loopback development and trusted ID alpha-synthetic.")
    # Restrict this tooling to the documented disposable local target.
    database_settings = DatabaseSettings.from_environment(dict(os.environ), required=True)
    if (database_settings.url.host not in {"127.0.0.1", "localhost", "::1"}
            or database_settings.url.database != "tabula_dev"):
        raise SystemExit("Seed requires the disposable loopback tabula_dev database.")
    database = Database(database_settings)
    try:
        PostgresLedgerSetupRepository.create_entity(database, "alpha-synthetic", "Alpha demonstration")
        PostgresLedgerSetupRepository.create_entity(database, "beta-synthetic", "Beta demonstration")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
