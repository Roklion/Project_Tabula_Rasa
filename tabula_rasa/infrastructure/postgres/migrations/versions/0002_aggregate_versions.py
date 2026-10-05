"""Aggregate baselines advance for persisted fields and owned details.

Revision ID: 0002_aggregate_versions
Revises: 0001_canonical
"""

from pathlib import Path
from alembic import op

revision = "0002_aggregate_versions"
down_revision = "0001_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"), prepare=False)


def downgrade() -> None:
    # Remove only this revision's triggers/functions; preserve rows and counters.
    for table in (
        "business_entities accounts categories payees tags entries mixed_use_sources "
        "recurring_schedules fixed_assets mileage_records documents import_batches migration_runs"
    ).split():
        op.execute(f"DROP TRIGGER advance_version ON {table}")
    for table, trigger in (
        ("postings", "version_entry"), ("entry_tags", "version_entry"),
        ("mixed_use_tags", "version_source"), ("schedule_tags", "version_schedule"),
        ("asset_tags", "version_asset"), ("asset_period_overrides", "version_asset"),
        ("depreciation_events", "version_asset"), ("mileage_tags", "version_mileage"),
        ("document_links", "version_document"), ("document_links", "version_entry"),
        ("document_links", "version_source"), ("import_records", "version_batch"),
        ("import_records", "version_entry"), ("import_records", "version_mileage"),
        ("entries", "version_owner"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION advance_entry_owner_version()")
    op.execute("DROP FUNCTION advance_detail_owner_version()")
    op.execute("DROP FUNCTION advance_aggregate_version()")
