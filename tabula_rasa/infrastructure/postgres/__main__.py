"""Explicit operator CLI; prints fixed diagnostics and schema revisions only."""

import argparse
import json

from alembic.util.exc import CommandError

from .config import DatabaseConfigurationError, DatabaseSettings
from .migrations import downgrade, head_revision, upgrade
from .runtime import Database, DatabaseError


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL schema and connectivity tools")
    parser.add_argument("command", choices=["upgrade", "current", "health", "downgrade"])
    parser.add_argument("--revision", default="base")
    parser.add_argument("--allow-destructive", action="store_true")
    args = parser.parse_args()
    database = None
    try:
        settings = DatabaseSettings.from_environment(required=True)
        database = Database(settings)
        if args.command == "upgrade":
            upgrade(database)
        elif args.command == "downgrade":
            downgrade(database, args.revision, allow_destructive=args.allow_destructive)
        result = database.health()
        result["head"] = head_revision()
        result["at_head"] = result.get("connected", False) and result.get("revision") == result["head"]
        print(json.dumps(result, sort_keys=True))
        return 0 if result["connected"] and (args.command in {"current", "downgrade"} or result["at_head"]) else 1
    except (DatabaseConfigurationError, DatabaseError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except CommandError:
        print(json.dumps({"error": "Invalid or unknown migration revision."}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
