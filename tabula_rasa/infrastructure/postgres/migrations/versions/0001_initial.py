"""Initial baseline; operator confirmed all previous databases are disposable.

Revision ID: 0001_initial
Revises: None
"""

from pathlib import Path
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        for name in ("0001_canonical.sql", "0001_integrity.sql", "0001_versions.sql", "0001_domain_integrity.sql"):
            cursor.execute(Path(__file__).with_name(name).read_text(encoding="utf-8"), prepare=False)


def downgrade() -> None:
    _drop_domain_guards()
    _drop_versions()
    _drop_baseline()


def _drop_domain_guards() -> None:
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


def _drop_versions() -> None:
    # Remove the version machinery before dropping its owned baseline tables.
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


def _drop_baseline() -> None:
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
