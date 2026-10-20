"""Read-only recovery-point verification; provider restores remain operator work."""

import re

from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.bookkeeping_export.format import validate_artifact
from .composition import create_postgres_export_service
from .cutover import database_identity


def verify_recovery(
    database, entity_id, expected, *, source_database_sha256,
    target_database_sha256, later=None,
):
    """Match one restored entity to a private, independently retained export.

    Endpoint fingerprints are operator bindings, not proof of provider lineage
    or isolation. A match attests neither a provider restore nor cutover approval.
    Bookkeeping reads use the complete export's read-only snapshot and validators.
    """
    if any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value)
           for value in (source_database_sha256, target_database_sha256)):
        raise ExportError("recovery_target")
    if (source_database_sha256 == target_database_sha256
            or database_identity(database) != target_database_sha256):
        raise ExportError("recovery_target")
    validate_artifact(expected, entity_id=entity_id)
    if later is not None:
        validate_artifact(later, entity_id=entity_id)
        if later["manifest"]["content_sha256"] == expected["manifest"]["content_sha256"]:
            raise ExportError("pitr_control_unchanged")
    restored = create_postgres_export_service(database, entity_id).export()
    if restored["manifest"]["database_schema_version"] != expected["manifest"]["database_schema_version"]:
        raise ExportError("recovery_schema_mismatch")
    if restored["manifest"]["content_sha256"] != expected["manifest"]["content_sha256"]:
        raise ExportError("recovery_point_mismatch")
    return {
        "status": "matched", "scope": "entity_bookkeeping",
        "database_schema_version": restored["manifest"]["database_schema_version"],
        "content_sha256": restored["manifest"]["content_sha256"],
        "diagnostic_count": len(restored["manifest"]["diagnostics"]),
        "later_state_distinct": later is not None,
    }
