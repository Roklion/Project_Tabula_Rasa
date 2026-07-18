"""Create and validate a consistent backup of the Plain Ledger database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


REQUIRED_TABLES = {"accounts", "categories", "transactions"}


def backup_database(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if source == destination:
        raise ValueError("Backup destination must differ from the source database")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)

    with sqlite3.connect(destination) as backup_db:
        integrity = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            row[0]
            for row in backup_db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    if integrity != "ok":
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity check failed: {integrity}")

    missing_tables = REQUIRED_TABLES - tables
    if missing_tables:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            "Backup is missing required tables: " + ", ".join(sorted(missing_tables))
        )

    print(f"Backup created and verified: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="SQLite database to back up")
    parser.add_argument("destination", type=Path, help="New backup file to create")
    args = parser.parse_args()
    backup_database(args.source, args.destination)


if __name__ == "__main__":
    main()
