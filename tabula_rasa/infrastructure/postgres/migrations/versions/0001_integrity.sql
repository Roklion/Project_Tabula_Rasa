-- Baseline aggregate checks. Domain preparation and specialized repository
-- version/baseline enforcement belong to #245-#253, never stored algorithms.

CREATE FUNCTION protect_object_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(OLD)->'entity_id') IS DISTINCT FROM (to_jsonb(NEW)->'entity_id')
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.incarnation_id IS DISTINCT FROM NEW.incarnation_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_object_identity',
            MESSAGE = 'Immutable object identity';
    END IF;
    IF NEW.version < OLD.version THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_object_version',
            MESSAGE = 'Aggregate version cannot decrease';
    END IF;
    IF TG_TABLE_NAME = 'entries' AND
       (to_jsonb(OLD)->'projection_kind' IS DISTINCT FROM to_jsonb(NEW)->'projection_kind'
        OR to_jsonb(OLD)->'mixed_use_source_id' IS DISTINCT FROM to_jsonb(NEW)->'mixed_use_source_id'
        OR to_jsonb(OLD)->'depreciation_asset_id' IS DISTINCT FROM to_jsonb(NEW)->'depreciation_asset_id') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_entry_identity',
            MESSAGE = 'Immutable entry projection and owner';
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
        EXECUTE format('CREATE TRIGGER protect_identity BEFORE UPDATE ON %I
            FOR EACH ROW EXECUTE FUNCTION protect_object_identity()', t);
    END LOOP;
END;
$$;

CREATE FUNCTION lock_hierarchy_entity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM business_entities WHERE id = COALESCE(NEW.entity_id, OLD.entity_id) FOR UPDATE;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE FUNCTION check_hierarchy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE scope text := COALESCE(NEW.entity_id, OLD.entity_id);
BEGIN
    IF EXISTS (SELECT 1 FROM accounts child JOIN accounts parent
        ON parent.entity_id = child.entity_id AND parent.id = child.parent_id
        WHERE child.entity_id = scope AND
        (parent.parent_id IS NOT NULL OR child.classification <> parent.classification))
       OR EXISTS (SELECT 1 FROM categories child JOIN categories parent
        ON parent.entity_id = child.entity_id AND parent.id = child.parent_id
        WHERE child.entity_id = scope AND (parent.parent_id IS NOT NULL OR child.kind <> parent.kind)) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_reference_hierarchy',
            MESSAGE = 'Invalid two-level hierarchy';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER lock_hierarchy BEFORE INSERT OR UPDATE OR DELETE ON accounts
    FOR EACH ROW EXECUTE FUNCTION lock_hierarchy_entity();
CREATE TRIGGER lock_hierarchy BEFORE INSERT OR UPDATE OR DELETE ON categories
    FOR EACH ROW EXECUTE FUNCTION lock_hierarchy_entity();
CREATE CONSTRAINT TRIGGER reference_hierarchy AFTER INSERT OR UPDATE OR DELETE ON accounts
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_hierarchy();
CREATE CONSTRAINT TRIGGER reference_hierarchy AFTER INSERT OR UPDATE OR DELETE ON categories
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_hierarchy();

CREATE FUNCTION lock_posting_entry() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (OLD.entity_id, OLD.entry_id, OLD.projection_kind, OLD.id)
        IS DISTINCT FROM (NEW.entity_id, NEW.entry_id, NEW.projection_kind, NEW.id) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_posting_identity',
            MESSAGE = 'Immutable posting identity';
    END IF;
    PERFORM 1 FROM entries WHERE entity_id = COALESCE(NEW.entity_id, OLD.entity_id)
        AND id = COALESCE(NEW.entry_id, OLD.entry_id) FOR UPDATE;
    RETURN COALESCE(NEW, OLD);
END;
$$;
CREATE TRIGGER lock_entry BEFORE INSERT OR UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION lock_posting_entry();

CREATE FUNCTION check_entry(scope text, entry_key text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE e entries%ROWTYPE; p1 postings%ROWTYPE; p2 postings%ROWTYPE;
        n bigint; largest integer; total numeric; smallest numeric;
BEGIN
    SELECT * INTO e FROM entries WHERE entity_id = scope AND id = entry_key FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    SELECT count(*), max(position),
        sum(CASE side WHEN 'Debit' THEN amount ELSE -amount END), min(amount)
        INTO n, largest, total, smallest FROM postings
        WHERE entity_id = scope AND entry_id = entry_key;
    IF n < 2 OR largest <> n OR total <> 0 THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_entry_balance',
            MESSAGE = 'Incomplete or unbalanced entry';
    END IF;
    IF e.projection_kind = 'journal' THEN
        IF smallest <= 0 OR EXISTS (SELECT 1 FROM entry_tags WHERE entity_id = scope AND entry_id = entry_key) THEN
            RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_shape',
                MESSAGE = 'Invalid journal shape';
        END IF;
        RETURN;
    END IF;
    SELECT * INTO p1 FROM postings WHERE entity_id = scope AND entry_id = entry_key AND position = 1;
    SELECT * INTO p2 FROM postings WHERE entity_id = scope AND entry_id = entry_key AND position = 2;
    IF n <> 2 OR p1.id <> entry_key || ':1' OR p2.id <> entry_key || ':2'
       OR p1.side <> 'Debit' OR p2.side <> 'Credit' OR p1.amount <> p2.amount
       OR p1.payee_id IS NOT NULL OR p2.payee_id IS NOT NULL
       OR p1.description <> '' OR p2.description <> ''
       OR (smallest <= 0 AND e.depreciation_asset_id IS NULL)
       OR (e.simple_kind = 'Income' AND (p1.account_id IS NULL OR p2.category_id IS NULL))
       OR (e.simple_kind = 'Expense' AND (p1.category_id IS NULL OR p2.account_id IS NULL))
       OR (e.simple_kind = 'Transfer' AND
           (p1.account_id IS NULL OR p2.account_id IS NULL OR p1.account_id = p2.account_id)) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_simple_shape',
            MESSAGE = 'Invalid simple entry shape';
    END IF;
    IF e.simple_kind IN ('Income','Expense') AND NOT EXISTS (
        SELECT 1 FROM categories WHERE entity_id = scope
        AND id = COALESCE(p1.category_id,p2.category_id) AND kind = e.simple_kind) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_simple_category',
            MESSAGE = 'Invalid simple category kind';
    END IF;
    IF e.depreciation_asset_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM depreciation_events event JOIN fixed_assets asset
            ON asset.entity_id = event.entity_id AND asset.id = event.asset_id
        JOIN accounts offset_account ON offset_account.entity_id = asset.entity_id
            AND offset_account.id = asset.accumulated_depreciation_account_id
        WHERE event.entity_id = scope AND event.entry_id = entry_key
            AND event.asset_id = e.depreciation_asset_id AND event.amount = p1.amount
            AND event.scheduled_date = e.txn_date AND event.sequence <= asset.useful_life_quarters
            AND asset.expense_category_id = p1.category_id
            AND asset.accumulated_depreciation_account_id = p2.account_id
            AND offset_account.type = 'Other' AND offset_account.classification = 'Asset') THEN
        RAISE EXCEPTION USING ERRCODE = '23514', CONSTRAINT = 'ck_depreciation_entry',
            MESSAGE = 'Invalid depreciation entry relationship';
    END IF;
END;
$$;

CREATE FUNCTION enforce_entry() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'entries' THEN
        PERFORM check_entry(COALESCE(NEW.entity_id,OLD.entity_id),COALESCE(NEW.id,OLD.id));
    ELSE
        PERFORM check_entry(COALESCE(NEW.entity_id,OLD.entity_id),COALESCE(NEW.entry_id,OLD.entry_id));
        IF TG_OP = 'UPDATE' AND OLD.entry_id IS DISTINCT FROM NEW.entry_id THEN
            PERFORM check_entry(OLD.entity_id,OLD.entry_id);
        END IF;
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER entry_integrity AFTER INSERT OR UPDATE OR DELETE ON entries
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_entry();
CREATE CONSTRAINT TRIGGER entry_integrity AFTER INSERT OR UPDATE OR DELETE ON postings
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_entry();
CREATE CONSTRAINT TRIGGER entry_integrity AFTER INSERT OR UPDATE OR DELETE ON entry_tags
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_entry();
CREATE CONSTRAINT TRIGGER entry_integrity AFTER INSERT OR UPDATE OR DELETE ON depreciation_events
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_entry();

-- Changing referenced kinds/settings must not silently invalidate an existing
-- simple entry, including the zero-valued depreciation exception.
CREATE FUNCTION recheck_reference_entries() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target record;
BEGIN
    FOR target IN SELECT DISTINCT e.entity_id,e.id FROM entries e
        JOIN postings p ON p.entity_id = e.entity_id AND p.entry_id = e.id
        WHERE e.entity_id = COALESCE(NEW.entity_id,OLD.entity_id) AND
        ((TG_TABLE_NAME = 'categories' AND p.category_id = COALESCE(NEW.id,OLD.id))
         OR (TG_TABLE_NAME = 'accounts' AND p.account_id = COALESCE(NEW.id,OLD.id))
         OR (TG_TABLE_NAME = 'fixed_assets' AND e.depreciation_asset_id = COALESCE(NEW.id,OLD.id))) LOOP
        PERFORM check_entry(target.entity_id,target.id);
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER entry_references AFTER UPDATE ON categories
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION recheck_reference_entries();
CREATE CONSTRAINT TRIGGER entry_references AFTER UPDATE ON accounts
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION recheck_reference_entries();
CREATE CONSTRAINT TRIGGER entry_references AFTER UPDATE ON fixed_assets
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION recheck_reference_entries();
