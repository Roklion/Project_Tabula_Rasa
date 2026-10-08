"""Inspect a recovery endpoint or verify restored bookkeeping without writes."""

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.bookkeeping_export.files import read_artifact
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.cutover import database_identity
from tabula_rasa.infrastructure.postgres.recovery import verify_recovery
from tabula_rasa.infrastructure.postgres.runtime import Database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", help="Read connectivity, revision and an opaque endpoint fingerprint.")
    verify = commands.add_parser("verify", help="Compare one restored entity to a private expected-point export.")
    verify.add_argument("--entity", required=True)
    verify.add_argument("--expected", type=Path, required=True)
    verify.add_argument("--later", type=Path, help="PITR control: a distinct export after the requested point.")
    verify.add_argument("--source-database-sha256", required=True)
    verify.add_argument("--target-database-sha256", required=True)
    args = parser.parse_args(argv)
    database = None
    try:
        # Explicit mapping bypasses .env.local and the ordinary application URL.
        # A missing recovery secret cannot silently select UAT or production.
        settings = DatabaseSettings.from_environment({
            "TABULA_RASA_DATABASE_URL": os.environ.get("TABULA_RASA_RECOVERY_DATABASE_URL", ""),
        }, required=True)
        expected = later = None
        if args.command == "verify":
            expected = read_artifact(args.expected, entity_id=args.entity)
            if args.later is not None:
                later = read_artifact(args.later, entity_id=args.entity)
        database = Database(settings)
        if args.command == "inspect":
            result = database.health()
            result["database_sha256"] = database_identity(database)
            code = 0 if result["connected"] else 1
        else:
            result = verify_recovery(
                database, args.entity, expected, later=later,
                source_database_sha256=args.source_database_sha256,
                target_database_sha256=args.target_database_sha256,
            )
            code = 0
    except ExportError as error:
        result, code = {"status": "failed", "code": error.code}, 1
    except Exception:
        # Provider, filesystem and configuration messages may contain secrets.
        result, code = {"status": "failed", "code": "unavailable"}, 1
    finally:
        if database is not None:
            try:
                database.dispose()
            except Exception:
                result, code = {"status": "failed", "code": "unavailable"}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
