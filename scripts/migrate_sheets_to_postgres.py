"""Explicit live Sheets migration rehearsal. Dry-run is the default."""

import argparse
import json
from pathlib import Path
import sys
from collections.abc import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import select_profile_secrets
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.migration.model import Binding, MigrationError
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.migration.documents import enrich_snapshot
from tabula_rasa.infrastructure.sheets_migration import extract_workbook
from tabula_rasa.infrastructure.google_drive_migration import GoogleDriveMigrationInventory
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
from tabula_rasa.infrastructure.postgres.migration_reconciliation import PostgresMigrationReconciler
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError


def run_migration(all_secrets, *, profile_key, entity_id, load=False, reconcile=False, document_store=None):
    # Explicit profile selection has no fallback to a previously selected profile.
    settings = select_profile_secrets(all_secrets, profile_key)
    binding = Binding(profile_key, str(settings["spreadsheet_id"]).strip(), entity_id)
    storage = GoogleSheetsStorage.from_secrets_read_only(settings)
    snapshot = extract_workbook(storage._workbook, binding)
    if document_store is None:
        drive_settings = settings.get("google_drive", {})
        folder = drive_settings.get("receipt_folder", {}) if isinstance(drive_settings, Mapping) else {}
        folder_id = str(folder.get("id", "")) if isinstance(folder, Mapping) else ""
        if folder_id:
            from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config
            document_store = GoogleDriveMigrationInventory(
                profile_key, folder_id, lambda: GoogleDriveClient(load_oauth_config(all_secrets), drive_settings))
    inventory = None
    if document_store is not None:
        inventory = document_store.inventory(profile_key, fresh=True)
        if inventory.unverified_storage_keys:
            raise MigrationError("Document inventory contains unreadable metadata; inspect the selected profile privately.")
    snapshot = enrich_snapshot(snapshot, entity_name=str(settings.get("name", profile_key)).strip(),
                               document_scope=document_store.scope_key if document_store is not None else "",
                               documents=inventory.documents if inventory is not None else (),
                               inventory_complete=inventory is not None,
                               document_timestamps=getattr(inventory, "timestamps", {}))
    plan = build_plan(snapshot)
    database = None
    try:
        # Dry-run never creates a DB pool, checks health or writes run metadata.
        if load or reconcile:
            database = Database(DatabaseSettings.from_environment(required=True))
        report = PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=not load)
        if reconcile:
            report["reconciliation"] = PostgresMigrationReconciler(database).reconcile(plan)
        return report
    finally:
        if database is not None:
            database.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--secrets", type=Path, default=PROJECT_ROOT / ".streamlit/secrets.toml")
    parser.add_argument("--load", action="store_true", help="Write only to an empty/inactive rehearsal entity.")
    parser.add_argument("--reconcile", action="store_true", help="Read-only comparison with the frozen source; no acceptance or cutover.")
    args = parser.parse_args(argv)
    try:
        secrets = load_business_profile_document(args.secrets)
        report = run_migration(secrets, profile_key=args.profile, entity_id=args.entity, load=args.load, reconcile=args.reconcile)
    except (MigrationError, DatabaseError) as error:
        print(json.dumps({"error": str(error), "cutover_authorized": False}, sort_keys=True))
        return 1
    except Exception:
        # Configuration/auth/provider exceptions can carry credentials or names.
        print(json.dumps({"error": "Migration setup or extraction failed; inspect configuration privately.",
                          "cutover_authorized": False}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 1 if report.get("reconciliation", {}).get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
