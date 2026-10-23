"""Explicit operator authority transitions for one frozen migrated profile."""

import json
import re

from sqlalchemy import text

from tabula_rasa.bookkeeping_export.format import build_artifact, validate_artifact
from tabula_rasa.migration.model import MigrationError, digest
from .entity_export import PostgresEntityExportRepository
from .migrations import current_revision, head_revision
from .identity import database_identity as database_identity


class CutoverError(MigrationError):
    """Fixed operator diagnostics, without source values, URLs or credentials."""


def evidence_reference(value):
    # Evidence content stays private; store only reviewed issue/PR links or
    # hashes of operator records. Arbitrary free text could contain secrets.
    return isinstance(value, str) and bool(re.fullmatch(
        r"(?:sha256:[0-9a-f]{64}|https://github\.com/Roklion/Project_Tabula_Rasa/(?:issues|pull)/[1-9][0-9]*(?:#[A-Za-z0-9-]+)?)",
        value))


class PostgresCutoverController:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _lock(connection, binding):
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,258))"),
                           {"scope": binding.entity_id})

    @staticmethod
    def _row(connection, binding, *, lock=False):
        row = connection.execute(text("SELECT * FROM bookkeeping_cutovers WHERE entity_id=:scope" +
                                      (" FOR UPDATE" if lock else "")), {"scope": binding.entity_id}).mappings().first()
        if row is not None and (row["source_profile_key"], row["source_workbook_key"]) != (
                binding.profile_key, binding.workbook_key):
            raise CutoverError("The cutover belongs to a different profile/source binding.")
        return row

    @staticmethod
    def _report(row):
        return dict(state=row["state"], activation_mode=row["activation_mode"],
                    divergent=row["divergent"], rollback_available=row["state"] in {"prepared", "postgres"} and not row["divergent"],
                    run_id=row["run_id"], acceptance_sha256=row["acceptance_sha256"],
                    export_content_sha256=row["accepted_export_sha256"],
                    source_snapshot_sha256=row["source_snapshot_sha256"],
                    cutover_authorized=row["state"] == "postgres")

    def inspect(self, binding):
        with self.database.transaction(read_only=True) as connection:
            row = self._row(connection, binding)
            return {"database_sha256": database_identity(self.database),
                    **(self._report(row) if row else {"state": "unprepared", "cutover_authorized": False})}

    def _export(self, connection, binding):
        artifact = build_artifact(PostgresEntityExportRepository(None, binding.entity_id).read_snapshot(connection))
        validate_artifact(artifact, entity_id=binding.entity_id)
        if artifact["manifest"]["status"] != "complete":
            raise CutoverError("Complete entity export has unresolved diagnostics; activation is blocked.")
        return artifact["manifest"]["content_sha256"]

    def prepare(self, plan, *, mode, evidence):
        """Finalize acceptance while workers/source jobs are drained and paused.

        No source mutation or backend activation occurs. The resulting target
        is protected against bookkeeping writes pending the operator decision.
        """
        from .migration import validate_plan
        from .migration_acceptance import PostgresMigrationAcceptance, SOURCE_CONTRACT

        validate_plan(plan)
        if mode not in {"rehearsal", "commercial_production"}:
            raise CutoverError("An explicit cutover environment is required.")
        required = {"source_freeze", "schema_baseline"}
        if mode == "commercial_production":
            required |= {"production_setup", "transaction_integrity", "backup_restore", "point_in_time_recovery"}
        if not isinstance(evidence, dict) or set(evidence) != required or any(
                not evidence_reference(evidence[field]) for field in required):
            raise CutoverError("Required operator evidence is missing or invalid.")
        binding = plan.snapshot.binding
        with self.database.transaction(require_outer=True) as connection:
            self._lock(connection, binding)
            row = self._row(connection, binding, lock=True)
            if row is not None:
                if (row["state"] != "prepared" or row["run_id"] != plan.run_id or row["activation_mode"] != mode
                        or row["evidence"]["operator"] != evidence):
                    raise CutoverError("A different or already activated cutover exists; inspect its authority.")
                if self._export(connection, binding) != row["accepted_export_sha256"]:
                    raise CutoverError("The prepared target has changed; activation is blocked.")
                return self._report(row)
            # Every canonical mutation takes this same entity lock. Once held,
            # all reads see a stable committed target until prepared commits.
            acceptance = PostgresMigrationAcceptance(self.database).evaluate(connection, plan)
            if not acceptance["whole_profile_accepted"]:
                raise CutoverError("Whole-profile migration acceptance failed; authority remains with Sheets.")
            connection.execute(text("UPDATE migration_runs SET status='validated' WHERE entity_id=:scope AND id=:run"),
                               {"scope": binding.entity_id, "run": plan.run_id})
            export_sha = self._export(connection, binding)
            params = dict(scope=binding.entity_id, profile=binding.profile_key, workbook=binding.workbook_key,
                          run=plan.run_id, snapshot=plan.snapshot.sha256, export=export_sha,
                          acceptance=acceptance["evidence_sha256"], mode=mode,
                          evidence=json.dumps({"operator": evidence, "source_contract": SOURCE_CONTRACT,
                                               "whole_profile_acceptance": acceptance["evidence_sha256"],
                                               "complete_entity_export": export_sha, "schema_revision": head_revision(),
                                               "document_scope_sha256": digest(plan.snapshot.metadata.get("document_scope", ""))}))
            connection.execute(text("""INSERT INTO bookkeeping_cutovers (
                entity_id,source_profile_key,source_workbook_key,run_id,source_snapshot_sha256,
                accepted_export_sha256,acceptance_sha256,state,activation_mode,evidence)
                VALUES (:scope,:profile,:workbook,:run,:snapshot,:export,:acceptance,'prepared',:mode,CAST(:evidence AS jsonb))"""), params)
            return self._report(self._row(connection, binding))

    def activate(self, binding, *, production_database_sha256=None, staging_database_sha256=None):
        """Switch the recorded authority only after independent gates pass."""
        with self.database.transaction(require_outer=True) as connection:
            self._lock(connection, binding)
            row = self._row(connection, binding, lock=True)
            if row is None or row["state"] != "prepared":
                raise CutoverError("A prepared whole-profile cutover is required before activation.")
            if current_revision(connection) != head_revision():
                raise CutoverError("The target schema differs from the validated revision chain.")
            if row["activation_mode"] == "commercial_production":
                if (production_database_sha256 != database_identity(self.database)
                        or not isinstance(staging_database_sha256, str)
                        or not re.fullmatch("[0-9a-f]{64}", staging_database_sha256)
                        or staging_database_sha256 == production_database_sha256):
                    raise CutoverError("Confirm the intended provisioned production database and a distinct staging database.")
            if self._export(connection, binding) != row["accepted_export_sha256"]:
                raise CutoverError("The accepted target has changed; activation is blocked.")
            connection.execute(text("""UPDATE bookkeeping_cutovers SET state='postgres',activated_at=CURRENT_TIMESTAMP,
                evidence=evidence || CAST(:environment AS jsonb) WHERE entity_id=:scope"""),
                {"scope": binding.entity_id, "environment": json.dumps({
                    "database_sha256": database_identity(self.database),
                    "production_database_sha256": production_database_sha256,
                    "staging_database_sha256": staging_database_sha256})})
            return self._report(self._row(connection, binding))

    def rollback(self, plan):
        """Use a freshly extracted frozen-format source; refuse any divergence."""
        from .migration import validate_plan

        validate_plan(plan)
        binding = plan.snapshot.binding
        with self.database.transaction(require_outer=True) as connection:
            self._lock(connection, binding)
            row = self._row(connection, binding, lock=True)
            if row is None or row["state"] not in {"prepared", "postgres"}:
                raise CutoverError("No prepared or active cutover is available for Sheets rollback.")
            if row["divergent"]:
                raise CutoverError("PostgreSQL has committed divergent bookkeeping writes; use PostgreSQL recovery.")
            if row["source_snapshot_sha256"] != plan.snapshot.sha256 or row["run_id"] != plan.run_id:
                raise CutoverError("The preserved format-13 source has changed; stop before reactivating Sheets.")
            if self._export(connection, binding) != row["accepted_export_sha256"]:
                raise CutoverError("The target differs from accepted bookkeeping; use PostgreSQL recovery.")
            connection.execute(text("UPDATE bookkeeping_cutovers SET state='sheets',rolled_back_at=CURRENT_TIMESTAMP WHERE entity_id=:scope"),
                               {"scope": binding.entity_id})
            return self._report(self._row(connection, binding))

    def require_postgres(self, binding, *, mode, document_scope=None):
        with self.database.transaction(read_only=True) as connection:
            row = self._row(connection, binding)
            if row is None or row["state"] != "postgres" or row["activation_mode"] != mode:
                raise CutoverError("This entity is not activated for the configured PostgreSQL environment.")
            if row["evidence"].get("database_sha256") != database_identity(self.database):
                raise CutoverError("The configured database differs from the activated target.")
            if document_scope is not None and row["evidence"]["document_scope_sha256"] != digest(document_scope):
                raise CutoverError("The configured document folder differs from the accepted source.")
            return self._report(row)
