"""Operator preparation, activation, smoke checks and pre-divergence rollback."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate_sheets_to_postgres import extract_plan
from tabula_rasa.business_profiles import select_profile_secrets
from tabula_rasa.composition import create_application
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.migration.model import Binding, MigrationError
from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.cutover import PostgresCutoverController
from tabula_rasa.infrastructure.postgres.migration_acceptance import PostgresMigrationAcceptance
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError


def smoke_application(profile_key, secrets, database, plan):
    """Read application services/reports/export before releasing maintenance."""
    application = create_application(profile_key, secrets, database=database)
    services = application.services
    services.ledger.get_info()
    services.accounts.list(active_only=False)
    services.categories.list()
    services.payees.list()
    services.tags.list()
    services.transactions.list(fresh=True)
    services.journals.list(fresh=True)
    services.assets.list(fresh=True)
    services.mixed_use.sources(fresh=True)
    services.recurring.list(fresh=True)
    services.mileage.list_trips(fresh=True)
    snapshot = services.reporting.read_ledger(force_refresh=True)
    services.reporting.period_report(snapshot)
    if services.receipts is not None:
        for row in plan.snapshot.tables["Transactions"]:
            if row["source_type"] != "depreciation":
                services.receipts.references(plan.target_id("Transactions", row["id"]), fresh=True)
    report = PostgresMigrationAcceptance(database).accept(plan)
    return {"application_reads_passed": True, "acceptance_report": report,
            "passed": report["whole_profile_accepted"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "prepare", "activate", "smoke", "rollback"))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--secrets", type=Path, default=PROJECT_ROOT / ".streamlit/secrets.toml")
    parser.add_argument("--mode", choices=("rehearsal", "commercial_production"),
                        help="Cutover evidence policy, independent of app deployment environment. "
                             "rehearsal also supports documented lasting owner operation.")
    parser.add_argument("--evidence", type=Path, help="Private operator evidence reference JSON; never ledger content.")
    parser.add_argument("--production-database-sha256")
    parser.add_argument("--staging-database-sha256")
    args = parser.parse_args(argv)
    if args.action == "prepare" and (args.mode is None or args.evidence is None):
        parser.error("prepare requires --mode and --evidence")
    database = None
    try:
        secrets = load_business_profile_document(args.secrets)
        selected = select_profile_secrets(secrets, args.profile)
        binding = Binding(args.profile, str(selected["spreadsheet_id"]).strip(), args.entity)
        # Extraction/preflight and local evidence parsing precede DB allocation.
        plan = extract_plan(secrets, profile_key=args.profile, entity_id=args.entity) if args.action in {
            "prepare", "smoke", "rollback"} else None
        evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.action == "prepare" else None
        database = Database(DatabaseSettings.from_environment(required=True))
        controller = PostgresCutoverController(database)
        if args.action == "inspect":
            report = controller.inspect(binding)
        elif args.action == "prepare":
            report = controller.prepare(plan, mode=args.mode, evidence=evidence)
        elif args.action == "activate":
            report = controller.activate(binding, production_database_sha256=args.production_database_sha256,
                                         staging_database_sha256=args.staging_database_sha256)
        elif args.action == "rollback":
            report = controller.rollback(plan)
        else:
            report = smoke_application(args.profile, secrets, database, plan)
        print(json.dumps(report, sort_keys=True))
        return 1 if report.get("passed") is False else 0
    except (MigrationError, ExportError, DatabaseError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "cutover_authorized": False}))
        return 1
    except Exception:
        # Provider/configuration/JSON exceptions may include private contents.
        print(json.dumps({"status": "failed", "error": "Cutover operation failed; inspect the gates and configuration privately.",
                          "cutover_authorized": False}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
