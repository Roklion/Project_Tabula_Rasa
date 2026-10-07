"""Per-entity authority evidence and the committed-divergence rollback boundary."""

from alembic import op

revision = "0005_bookkeeping_cutover"
down_revision = "0004_mileage_order"
branch_labels = None
depends_on = None

# Frozen at this revision. Future bookkeeping tables must extend the guard.
GUARDED_TABLES = (
    "business_entities", "accounts", "categories", "payees", "tags", "entries", "postings", "entry_tags",
    "mixed_use_sources", "mixed_use_tags", "recurring_schedules", "schedule_tags", "recurring_occurrences",
    "fixed_assets", "asset_tags", "asset_period_overrides", "depreciation_events", "mileage_records", "mileage_tags",
    "documents", "document_links", "import_batches", "import_records", "migration_runs", "migration_units",
    "migration_id_mappings",
)


def upgrade():
    op.execute("""CREATE TABLE bookkeeping_cutovers (
        entity_id text PRIMARY KEY REFERENCES business_entities(id),
        source_profile_key text NOT NULL UNIQUE CHECK (btrim(source_profile_key) <> ''),
        source_workbook_key text NOT NULL CHECK (btrim(source_workbook_key) <> ''),
        run_id text NOT NULL,
        source_snapshot_sha256 text NOT NULL CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
        accepted_export_sha256 text NOT NULL CHECK (accepted_export_sha256 ~ '^[0-9a-f]{64}$'),
        acceptance_sha256 text NOT NULL CHECK (acceptance_sha256 ~ '^[0-9a-f]{64}$'),
        state text NOT NULL CHECK (state IN ('prepared','postgres','sheets')),
        activation_mode text NOT NULL CHECK (activation_mode IN ('rehearsal','commercial_production')),
        evidence jsonb NOT NULL,
        divergent boolean NOT NULL DEFAULT false,
        prepared_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
        activated_at timestamptz,
        rolled_back_at timestamptz,
        FOREIGN KEY (entity_id,run_id) REFERENCES migration_runs(entity_id,id),
        CHECK (NOT divergent OR state='postgres')
    )""")
    op.execute("""CREATE FUNCTION guard_bookkeeping_cutover() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE scope text; previous_scope text; authority text;
    BEGIN
        IF TG_TABLE_NAME='business_entities' THEN
            scope := CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
            IF TG_OP='UPDATE' THEN previous_scope := OLD.id; END IF;
        ELSE
            scope := CASE WHEN TG_OP='DELETE' THEN OLD.entity_id ELSE NEW.entity_id END;
            IF TG_OP='UPDATE' THEN previous_scope := OLD.entity_id; END IF;
        END IF;
        IF previous_scope IS NOT NULL AND previous_scope <> scope THEN
            RAISE EXCEPTION 'Bookkeeping entity identity cannot change' USING ERRCODE='23514';
        END IF;
        -- The same narrow lock is used by acceptance/cutover operators. It
        -- serializes the authority decision with mutations, including creates.
        PERFORM pg_advisory_xact_lock(hashtextextended(scope,258));
        SELECT state INTO authority FROM bookkeeping_cutovers WHERE entity_id=scope FOR UPDATE;
        IF authority IN ('prepared','sheets') THEN
            RAISE EXCEPTION 'Bookkeeping backend is inactive' USING ERRCODE='55000';
        ELSIF authority='postgres' THEN
            UPDATE bookkeeping_cutovers SET divergent=true WHERE entity_id=scope AND NOT divergent;
        END IF;
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END $$""")
    for table in GUARDED_TABLES:
        op.execute(f"CREATE TRIGGER bookkeeping_cutover_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION guard_bookkeeping_cutover()")


def downgrade():
    # This is destructive control-plane removal; use only the existing explicit
    # operator downgrade boundary with an appropriate recovery plan.
    for table in GUARDED_TABLES:
        op.execute(f"DROP TRIGGER bookkeeping_cutover_guard ON {table}")
    op.execute("DROP FUNCTION guard_bookkeeping_cutover()")
    op.execute("DROP TABLE bookkeeping_cutovers")
