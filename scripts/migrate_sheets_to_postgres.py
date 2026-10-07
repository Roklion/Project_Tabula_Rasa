"""Explicit live Sheets migration rehearsal. Dry-run is the default."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import select_profile_secrets
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.migration.model import Binding, MigrationError
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.infrastructure.sheets_migration import extract_workbook
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError


def run_migration(all_secrets, *, profile_key, entity_id, load=False):
    # Explicit profile selection has no fallback to a previously selected profile.
    settings = select_profile_secrets(all_secrets, profile_key)
    binding = Binding(profile_key, str(settings["spreadsheet_id"]).strip(), entity_id)
    storage = GoogleSheetsStorage.from_secrets_read_only(settings)
    plan = build_plan(extract_workbook(storage._workbook, binding))
    database = None
    try:
        # Dry-run never creates a DB pool, checks health or writes run metadata.
        if load:
            database = Database(DatabaseSettings.from_environment(required=True))
        return PostgresMigrationRunner(database).execute(plan, dry_run=not load)
    finally:
        if database is not None:
            database.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--secrets", type=Path, default=PROJECT_ROOT / ".streamlit/secrets.toml")
    parser.add_argument("--load", action="store_true", help="Write only to an empty/inactive rehearsal entity.")
    args = parser.parse_args(argv)
    try:
        secrets = load_business_profile_document(args.secrets)
        report = run_migration(secrets, profile_key=args.profile, entity_id=args.entity, load=args.load)
    except (MigrationError, DatabaseError) as error:
        print(json.dumps({"error": str(error), "cutover_authorized": False}, sort_keys=True))
        return 1
    except Exception:
        # Configuration/auth/provider exceptions can carry credentials or names.
        print(json.dumps({"error": "Migration setup or extraction failed; inspect configuration privately.",
                          "cutover_authorized": False}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
