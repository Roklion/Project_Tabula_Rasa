"""Deferred source/occurrence integrity and committed history protection."""

from pathlib import Path

from alembic import op

revision = "0003_domain_integrity"
down_revision = "0002_aggregate_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"), prepare=False)


def downgrade() -> None:
    for table in ("mixed_use_sources", "entries", "postings", "entry_tags", "mixed_use_tags",
                  "recurring_schedules", "recurring_occurrences", "fixed_assets",
                  "depreciation_events", "asset_period_overrides", "document_links",
                  "import_records", "categories", "accounts"):
        op.execute(f"DROP TRIGGER domain_integrity ON {table}")
    for table in ("recurring_schedules", "recurring_occurrences", "depreciation_events",
                  "fixed_assets", "asset_period_overrides", "entries", "postings", "entry_tags"):
        op.execute(f"DROP TRIGGER protect_history ON {table}")
    op.execute("DROP FUNCTION enforce_domain_integrity()")
    op.execute("DROP FUNCTION check_mixed_relationship(text,text)")
    op.execute("DROP FUNCTION check_schedule_relationship(text,text)")
    op.execute("DROP FUNCTION check_asset_relationship(text,text)")
    op.execute("DROP FUNCTION protect_committed_history()")
    op.execute("DROP TRIGGER version_entry ON recurring_occurrences")
    op.execute("DROP TRIGGER version_source ON recurring_occurrences")
