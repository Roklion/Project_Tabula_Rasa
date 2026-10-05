"""Canonical v1 baseline from ADR 0001; no runtime schema auto-generation.

Revision ID: 0001_canonical
Revises: None
"""

from pathlib import Path

from alembic import op

revision = "0001_canonical"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    # Multi-statement SQL with PL/pgSQL bodies belongs to this frozen revision.
    # Use the driver's cursor without interpolating parameters or credentials.
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)
        cursor.execute(Path(__file__).with_name("0001_integrity.sql").read_text(encoding="utf-8"), prepare=False)


def downgrade() -> None:
    # Whole-baseline removal is intentionally destructive and explicitly gated
    # by the operator CLI. No CASCADE: unexpected external dependencies stop it.
    tables = (
        "migration_id_mappings migration_units migration_runs import_records import_batches "
        "document_links documents mileage_tags mileage_records depreciation_events "
        "asset_period_overrides asset_tags recurring_occurrences schedule_tags "
        "recurring_schedules mixed_use_tags entry_tags postings"
    ).split()
    for table in tables:
        op.execute(f'DROP TABLE "{table}"')
    # Cyclic source/entry relationships are removed explicitly, never CASCADE.
    op.execute("ALTER TABLE entries DROP CONSTRAINT fk_entries_mixed_use_source")
    op.execute("ALTER TABLE entries DROP CONSTRAINT fk_entries_depreciation_asset")
    for table in "fixed_assets mixed_use_sources entries tags payees categories accounts business_entities".split():
        op.execute(f'DROP TABLE "{table}"')
    for function in (
        "check_entry(text,text)", "enforce_entry()", "lock_posting_entry()",
        "check_hierarchy()", "lock_hierarchy_entity()", "protect_object_identity()",
        "recheck_reference_entries()",
    ):
        op.execute(f"DROP FUNCTION {function}")
