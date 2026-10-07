"""Whole-profile acceptance over the existing migration and export owners."""

from sqlalchemy import text

from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.bookkeeping_export.format import build_artifact, validate_artifact
from tabula_rasa.migration.model import digest
from tabula_rasa.errors import StorageNotFoundError
from tabula_rasa.reference_data import normalize_tag_ids
from .entity_export import PostgresEntityExportRepository
from .migration import PostgresMigrationRunner, validate_plan
from .migration_reconciliation import PostgresMigrationReconciler

SOURCE_CONTRACT = {"issue": 261, "pull_request": 263, "format": 13,
                   "commit": "5d51134c20e56d9adaaa0e18f890dc39f9f978fc"}


class PostgresMigrationAcceptance:
    def __init__(self, database):
        self.database = database

    def accept(self, plan, *, periods=()):
        """Read-only sign-off evidence; authority switching is a separate operation."""
        validate_plan(plan)
        with self.database.transaction(read_only=True, require_outer=True) as connection:
            return self.evaluate(connection, plan, periods=periods)

    def evaluate(self, connection, plan, *, periods=()):
        # The caller owns one coherent target snapshot, including complete export.
        validate_plan(plan)
        report = PostgresMigrationReconciler(self.database)._reconcile(connection, plan, periods)
        checks, differences = report["checks"], report["exceptions"]

        def check(domain, name, passed):
            checks.append(dict(domain=domain, check=name, passed=bool(passed)))
            if not passed:
                differences.append(dict(domain=domain, fields=[name]))

        dry_run = PostgresMigrationRunner(None, secondary=True).execute(plan)
        check("Migration", "complete_supported_loader_coverage", not dry_run["missing_loaders"])
        metadata = plan.snapshot.metadata
        check("Documents", "complete_selected_folder_inventory",
              not metadata.get("document_scope") or metadata.get("inventory_complete") is True)
        # A structurally valid export may contain additional relationships.
        # Final source equivalence requires exactly the source-owned edge sets.
        scope = plan.snapshot.binding.entity_id
        tables = plan.snapshot.tables
        for title, table, owner in (
            ("Transactions", "entry_tags", "entry_id"),
            ("MixedUseExpenses", "mixed_use_tags", "source_id"),
            ("RecurringSchedules", "schedule_tags", "schedule_id"),
            ("Assets", "asset_tags", "asset_id"),
            ("Mileage", "mileage_tags", "mileage_id"),
        ):
            expected = {(plan.target_id(title, row["id"]), plan.target_id("Tags", tag))
                        for row in tables[title] for tag in normalize_tag_ids(row["tag_ids"])}
            actual = set(connection.execute(text(
                f"SELECT {owner},tag_id FROM {table} WHERE entity_id=:scope"), {"scope": scope}).all())
            check(title, "complete_tag_relationships", actual == expected)
        check("Migration", "no_invented_import_records", connection.scalar(text(
            "SELECT count(*) FROM import_records WHERE entity_id=:scope"), {"scope": scope}) == 0)
        manifest = None
        try:
            artifact = build_artifact(PostgresEntityExportRepository(None, scope).read_snapshot(connection))
            validate_artifact(artifact, entity_id=scope)
            manifest = artifact["manifest"]
        except (ExportError, StorageNotFoundError) as error:
            check("Export", getattr(error, "code", None) or "entity_available", False)
        else:
            check("Export", "complete_entity_format_and_relationships", manifest["status"] == "complete")
        report.update(acceptance_version="1", acceptance="whole_profile",
                      source_contract=SOURCE_CONTRACT.copy(), source_preflight="shared_format_13_and_domain_validators",
                      database_revision=manifest["database_schema_version"] if manifest else None,
                      unit_counts=dry_run["unit_counts"], export_verified=bool(manifest and manifest["status"] == "complete"),
                      export_content_sha256=manifest["content_sha256"] if manifest else None,
                      export_domain_counts=manifest["counts"] if manifest else {},
                      passed=not differences, whole_profile_accepted=not differences, cutover_authorized=False)
        report["evidence_sha256"] = digest(report)
        return report
