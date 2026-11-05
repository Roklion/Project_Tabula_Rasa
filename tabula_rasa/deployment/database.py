"""Bound migration and synthetic fixture tooling; reuse PostgreSQL owners."""

import argparse
import os
import subprocess
import sys

from sqlalchemy import inspect, text

from tabula_rasa.infrastructure.postgres.hosted import open_alpha_database as bound_database
from tabula_rasa.infrastructure.postgres.hosted import open_bound_neon_database
from tabula_rasa.infrastructure.postgres.migrations import head_revision, upgrade


def migrate(environ, *, bootstrap=False):
    if environ.get("TABULA_RASA_ENVIRONMENT") == "production":
        if bootstrap:
            raise ValueError("Production promotion requires an existing compatible schema.")
        migrate_production(environ)
        return
    database = bound_database(environ)
    try:
        health = database.health()
        # Head-only runtime: automation never migrates underneath incompatible old code.
        if not health["connected"] or health.get("revision") != head_revision():
            if not (bootstrap and health["connected"] and health.get("revision") is None):
                raise ValueError("Schema change requires a reviewed bridge or maintenance procedure.")
            if inspect(database.engine).get_table_names(schema="public"):
                raise ValueError("Initial bootstrap requires a blank database.")
    finally:
        database.dispose()
    for command in ("current", "upgrade", "health"):
        result = subprocess.run([sys.executable, "-m", "tabula_rasa.infrastructure.postgres", command],
                                env=dict(environ), capture_output=True, check=False)
        if result.returncode:
            raise ValueError("Migration/health step failed; application deployment stopped.")
    print("Database migration and health checks passed.")


def migrate_production(environ):
    database = open_bound_neon_database(environ)
    try:
        with database.engine.connect() as connection:
            permitted = connection.scalar(text("""
                SELECT has_schema_privilege(current_user, 'public', 'USAGE')
                    AND has_schema_privilege(current_user, 'public', 'CREATE')
                    AND pg_has_role(current_user, relowner, 'USAGE')
                FROM pg_class
                WHERE oid = to_regclass('public.alembic_version')
            """))
        if permitted is not True:
            raise ValueError("Production migration credential needs schema creation and version-table ownership.")
        upgrade(database, require_current_head=True)
        health = database.health()
        if not health.get("connected") or health.get("revision") != head_revision():
            raise ValueError("Production schema confirmation failed.")
    finally:
        database.dispose()
    print("Production migration gate passed at the compatible schema head.")


def seed(environ):
    from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
    from tabula_rasa.infrastructure.postgres.reference_data import PostgresLedgerSetupRepository

    database = bound_database(environ)
    try:
        if database.health().get("revision") != head_revision():
            raise ValueError("Seed requires the current schema.")
        with database.transaction():
            PostgresLedgerSetupRepository.create_entity(database, "alpha-synthetic", "Alpha demonstration")
            create_postgres_services(database, "alpha-synthetic").accounts.create(
                "Deployment connectivity", "Bank", "0.00")
    finally:
        database.dispose()
    print("Synthetic deployment fixture created.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "seed"])
    parser.add_argument("--bootstrap", action="store_true", help="Operator-only initial blank schema setup")
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            migrate(dict(os.environ), bootstrap=args.bootstrap)
        elif args.bootstrap:
            raise ValueError("Bootstrap applies only to initial migration.")
        else:
            seed(dict(os.environ))
    except Exception:
        raise SystemExit("Deployment database step failed. Inspect target binding, schema and fixture state.") from None


if __name__ == "__main__":
    main()
