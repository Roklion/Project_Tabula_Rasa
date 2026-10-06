-- Every business-field update and detail change invalidates a loaded aggregate.
-- Counters may advance more than once per operation; consumers test equality,
-- never assume a particular increment. No-op/display/attention changes are excluded.

CREATE FUNCTION advance_aggregate_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ignored text[] := ARRAY['version','updated_at'];
BEGIN
    IF NEW.version < OLD.version OR NEW.version > OLD.version + 1 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_object_version',
            MESSAGE = 'Invalid aggregate version advancement';
    END IF;
    IF TG_TABLE_NAME = 'recurring_schedules' THEN
        ignored := ignored || ARRAY['attention_code','attention_at'];
    END IF;
    IF (to_jsonb(NEW) - ignored) IS DISTINCT FROM (to_jsonb(OLD) - ignored) THEN
        NEW.version := OLD.version + 1;
    END IF;
    IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        NEW.updated_at := clock_timestamp();
    ELSE
        NEW.updated_at := OLD.updated_at;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['business_entities','accounts','categories','payees','tags',
        'entries','mixed_use_sources','recurring_schedules','fixed_assets','mileage_records',
        'documents','import_batches','migration_runs'] LOOP
        EXECUTE format('CREATE TRIGGER advance_version BEFORE UPDATE ON %I
            FOR EACH ROW EXECUTE FUNCTION advance_aggregate_version()', t);
    END LOOP;
END;
$$;

CREATE FUNCTION advance_detail_owner_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE before_row jsonb; after_row jsonb; owner record;
BEGIN
    IF TG_OP <> 'INSERT' THEN before_row := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN after_row := to_jsonb(NEW); END IF;
    IF before_row IS NOT DISTINCT FROM after_row THEN RETURN NULL; END IF;
    -- UPDATE supports repointing relationships. Invalidate both old and new
    -- owners, in deterministic scope/ID order, with bound values only.
    FOR owner IN
        SELECT DISTINCT r->>'entity_id' AS scope, r->>TG_ARGV[1] AS id
        FROM (VALUES (before_row), (after_row)) AS rows(r)
        WHERE r->>TG_ARGV[1] IS NOT NULL
        ORDER BY scope, id
    LOOP
        EXECUTE format('UPDATE %I SET version = version + 1 WHERE entity_id = $1 AND id = $2', TG_ARGV[0])
            USING owner.scope, owner.id;
    END LOOP;
    RETURN NULL;
END;
$$;

CREATE TRIGGER version_entry AFTER INSERT OR UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('entries','entry_id');
CREATE TRIGGER version_entry AFTER INSERT OR UPDATE OR DELETE ON entry_tags
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('entries','entry_id');
CREATE TRIGGER version_source AFTER INSERT OR UPDATE OR DELETE ON mixed_use_tags
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('mixed_use_sources','source_id');
CREATE TRIGGER version_schedule AFTER INSERT OR UPDATE OR DELETE ON schedule_tags
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('recurring_schedules','schedule_id');
CREATE TRIGGER version_asset AFTER INSERT OR UPDATE OR DELETE ON asset_tags
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('fixed_assets','asset_id');
CREATE TRIGGER version_asset AFTER INSERT OR UPDATE OR DELETE ON asset_period_overrides
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('fixed_assets','asset_id');
CREATE TRIGGER version_asset AFTER INSERT OR UPDATE OR DELETE ON depreciation_events
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('fixed_assets','asset_id');
CREATE TRIGGER version_mileage AFTER INSERT OR UPDATE OR DELETE ON mileage_tags
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('mileage_records','mileage_id');
CREATE TRIGGER version_document AFTER INSERT OR UPDATE OR DELETE ON document_links
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('documents','document_id');
CREATE TRIGGER version_entry AFTER INSERT OR UPDATE OR DELETE ON document_links
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('entries','entry_id');
CREATE TRIGGER version_source AFTER INSERT OR UPDATE OR DELETE ON document_links
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('mixed_use_sources','mixed_use_source_id');
CREATE TRIGGER version_batch AFTER INSERT OR UPDATE OR DELETE ON import_records
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('import_batches','batch_id');
CREATE TRIGGER version_entry AFTER INSERT OR UPDATE OR DELETE ON import_records
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('entries','entry_id');
CREATE TRIGGER version_mileage AFTER INSERT OR UPDATE OR DELETE ON import_records
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('mileage_records','mileage_id');

CREATE FUNCTION advance_entry_owner_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE entry_row jsonb;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.version = OLD.version THEN RETURN NULL; END IF;
    IF TG_OP = 'DELETE' THEN entry_row := to_jsonb(OLD); ELSE entry_row := to_jsonb(NEW); END IF;
    UPDATE mixed_use_sources SET version = version + 1
        WHERE entity_id = entry_row->>'entity_id' AND id = entry_row->>'mixed_use_source_id';
    UPDATE fixed_assets SET version = version + 1
        WHERE entity_id = entry_row->>'entity_id' AND id = entry_row->>'depreciation_asset_id';
    RETURN NULL;
END;
$$;
CREATE TRIGGER version_owner AFTER INSERT OR UPDATE OR DELETE ON entries
    FOR EACH ROW EXECUTE FUNCTION advance_entry_owner_version();
