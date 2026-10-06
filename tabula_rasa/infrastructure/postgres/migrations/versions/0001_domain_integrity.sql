-- Relational parity/history checks only. Domain calculations stay in Python.
CREATE FUNCTION check_mixed_relationship(scope text, source_key text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s mixed_use_sources%ROWTYPE; e entries%ROWTYPE; matches boolean;
BEGIN
    SELECT * INTO s FROM mixed_use_sources WHERE entity_id=scope AND id=source_key FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF NOT EXISTS (SELECT 1 FROM categories WHERE entity_id=scope AND id=s.category_id AND kind='Expense') THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_mixed_category', MESSAGE='Invalid mixed category';
    END IF;
    SELECT * INTO e FROM entries WHERE entity_id=scope AND mixed_use_source_id=source_key;
    IF NOT FOUND THEN
        IF s.relationship_state <> 'missing_projection' THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_mixed_relationship', MESSAGE='Invalid mixed relationship';
        END IF;
        RETURN;
    END IF;
    matches := e.id=s.expected_projection_entry_id AND e.txn_date=s.txn_date
        AND e.payee_id IS NOT DISTINCT FROM s.payee_id AND e.reference=s.reference
        AND e.description=(CASE WHEN s.description='' THEN '' ELSE s.description || chr(10) END)
            || 'Allocation rationale: ' || s.allocation_rationale
        AND EXISTS (SELECT 1 FROM postings WHERE entity_id=scope AND entry_id=e.id
            AND position=1 AND category_id=s.category_id AND amount=s.allocated_amount)
        AND EXISTS (SELECT 1 FROM postings WHERE entity_id=scope AND entry_id=e.id
            AND position=2 AND account_id=s.account_id AND amount=s.allocated_amount)
        AND NOT EXISTS (
            (SELECT tag_id FROM mixed_use_tags WHERE entity_id=scope AND source_id=source_key
             EXCEPT SELECT tag_id FROM entry_tags WHERE entity_id=scope AND entry_id=e.id)
            UNION ALL
            (SELECT tag_id FROM entry_tags WHERE entity_id=scope AND entry_id=e.id
             EXCEPT SELECT tag_id FROM mixed_use_tags WHERE entity_id=scope AND source_id=source_key));
    IF (s.relationship_state='complete' AND NOT matches)
       OR (s.relationship_state='projection_mismatch' AND matches)
       OR s.relationship_state='missing_projection' THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_mixed_relationship', MESSAGE='Invalid mixed relationship';
    END IF;
END;
$$;

CREATE FUNCTION check_schedule_relationship(scope text, schedule_key text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s recurring_schedules%ROWTYPE;
BEGIN
    SELECT * INTO s FROM recurring_schedules WHERE entity_id=scope AND id=schedule_key FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF NOT EXISTS (SELECT 1 FROM categories WHERE entity_id=scope AND id=s.category_id AND kind='Expense')
       OR EXISTS (SELECT 1 FROM recurring_occurrences o
            LEFT JOIN entries e ON e.entity_id=o.entity_id AND e.id=o.entry_id
            LEFT JOIN mixed_use_sources m ON m.entity_id=o.entity_id AND m.id=o.mixed_use_source_id
            WHERE o.entity_id=scope AND o.schedule_id=schedule_key AND
            (o.source_kind<>s.source_kind OR
             (o.source_kind='transaction' AND
              (e.projection_kind IS DISTINCT FROM 'simple' OR e.simple_kind IS DISTINCT FROM 'Expense'
               OR e.mixed_use_source_id IS NOT NULL OR e.depreciation_asset_id IS NOT NULL))
             OR (o.source_kind='mixed_use' AND m.relationship_state IS DISTINCT FROM 'complete'))) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_recurring_relationship', MESSAGE='Invalid recurring relationship';
    END IF;
END;
$$;

CREATE FUNCTION check_asset_relationship(scope text, asset_key text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE a fixed_assets%ROWTYPE;
BEGIN
    SELECT * INTO a FROM fixed_assets WHERE entity_id=scope AND id=asset_key FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    IF (a.expense_category_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM categories WHERE entity_id=scope AND id=a.expense_category_id AND kind='Expense'))
       OR (a.accumulated_depreciation_account_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM accounts WHERE entity_id=scope AND id=a.accumulated_depreciation_account_id
           AND type='Other' AND classification='Asset'))
       OR EXISTS (SELECT 1 FROM asset_period_overrides WHERE entity_id=scope AND asset_id=asset_key
                  AND sequence>a.useful_life_quarters)
       OR EXISTS (SELECT 1 FROM entries WHERE entity_id=scope AND id=a.source_entry_id
                  AND projection_kind<>'simple')
       OR EXISTS (SELECT 1 FROM depreciation_events d JOIN entries e
                  ON e.entity_id=d.entity_id AND e.id=d.entry_id
                  WHERE d.entity_id=scope AND d.asset_id=asset_key
                  AND (e.depreciation_asset_id IS DISTINCT FROM asset_key
                       OR (a.retired_date IS NOT NULL AND d.scheduled_date>a.retired_date))) THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_asset_relationship', MESSAGE='Invalid asset relationship';
    END IF;
END;
$$;

CREATE FUNCTION enforce_domain_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r jsonb; scope text; target record; entry_key text; source_key text;
BEGIN
    -- Repointable detail relationships recheck both roots. Identity-protected
    -- roots themselves have one key. Checks inspect final committed shape.
    FOR r IN SELECT DISTINCT row_value FROM
        (VALUES (CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END),
                (CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END)) AS rows(row_value)
        WHERE row_value IS NOT NULL
    LOOP
        scope := r->>'entity_id';
        entry_key := CASE WHEN TG_TABLE_NAME='entries' THEN r->>'id' ELSE r->>'entry_id' END;
        source_key := CASE WHEN TG_TABLE_NAME='mixed_use_sources' THEN r->>'id'
                          WHEN TG_TABLE_NAME='mixed_use_tags' THEN r->>'source_id'
                          ELSE r->>'mixed_use_source_id' END;
        IF TG_TABLE_NAME IN ('mixed_use_sources','mixed_use_tags','entries','document_links') THEN
            PERFORM check_mixed_relationship(scope,source_key);
        END IF;
        IF TG_TABLE_NAME IN ('entries','postings','entry_tags') THEN
            FOR target IN SELECT mixed_use_source_id AS id FROM entries
                WHERE entity_id=scope AND id=entry_key AND mixed_use_source_id IS NOT NULL
            LOOP PERFORM check_mixed_relationship(scope,target.id); END LOOP;
            FOR target IN SELECT schedule_id AS id FROM recurring_occurrences
                WHERE entity_id=scope AND entry_id=entry_key
            LOOP PERFORM check_schedule_relationship(scope,target.id); END LOOP;
        END IF;
        IF TG_TABLE_NAME='mixed_use_sources' THEN
            FOR target IN SELECT schedule_id AS id FROM recurring_occurrences
                WHERE entity_id=scope AND mixed_use_source_id=source_key
            LOOP PERFORM check_schedule_relationship(scope,target.id); END LOOP;
        END IF;
        IF TG_TABLE_NAME IN ('recurring_schedules','recurring_occurrences') THEN
            PERFORM check_schedule_relationship(scope,CASE WHEN TG_TABLE_NAME='recurring_schedules'
                THEN r->>'id' ELSE r->>'schedule_id' END);
        END IF;
        IF TG_TABLE_NAME IN ('fixed_assets','asset_period_overrides','depreciation_events') THEN
            PERFORM check_asset_relationship(scope,CASE WHEN TG_TABLE_NAME='fixed_assets'
                THEN r->>'id' ELSE r->>'asset_id' END);
        END IF;
        IF TG_TABLE_NAME='document_links' AND entry_key IS NOT NULL AND EXISTS
            (SELECT 1 FROM document_links l JOIN entries e ON e.entity_id=l.entity_id AND e.id=l.entry_id
             WHERE l.entity_id=scope AND l.document_id=r->>'document_id'
               AND (e.projection_kind<>'simple' OR e.mixed_use_source_id IS NOT NULL
                    OR e.depreciation_asset_id IS NOT NULL)) THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_document_target', MESSAGE='Invalid document target';
        END IF;
        IF TG_TABLE_NAME='import_records' AND EXISTS
            (SELECT 1 FROM import_records i JOIN entries e ON e.entity_id=i.entity_id AND e.id=i.entry_id
             WHERE i.entity_id=scope AND i.batch_id=r->>'batch_id'
               AND i.source_position=(r->>'source_position')::integer AND e.projection_kind<>'simple') THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_import_target', MESSAGE='Invalid import target';
        END IF;
        IF TG_TABLE_NAME='categories' THEN
            FOR target IN SELECT id FROM mixed_use_sources WHERE entity_id=scope AND category_id=r->>'id' ORDER BY id
            LOOP PERFORM check_mixed_relationship(scope,target.id); END LOOP;
            FOR target IN SELECT id FROM recurring_schedules WHERE entity_id=scope AND category_id=r->>'id' ORDER BY id
            LOOP PERFORM check_schedule_relationship(scope,target.id); END LOOP;
        END IF;
        IF TG_TABLE_NAME IN ('categories','accounts') THEN
            FOR target IN SELECT id FROM fixed_assets WHERE entity_id=scope
                AND ((TG_TABLE_NAME='categories' AND expense_category_id=r->>'id')
                 OR (TG_TABLE_NAME='accounts' AND accumulated_depreciation_account_id=r->>'id')) ORDER BY id
            LOOP PERFORM check_asset_relationship(scope,target.id); END LOOP;
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;

CREATE FUNCTION protect_committed_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE scope text := COALESCE(NEW.entity_id,OLD.entity_id); asset_key text;
        has_events boolean; fields text[]; target record;
BEGIN
    IF TG_TABLE_NAME='recurring_schedules' AND TG_OP='UPDATE'
        AND to_jsonb(NEW)->'source_kind' IS DISTINCT FROM to_jsonb(OLD)->'source_kind' THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_recurring_identity', MESSAGE='Immutable schedule source kind';
    ELSIF TG_TABLE_NAME='recurring_occurrences' AND TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_recurring_identity', MESSAGE='Immutable occurrence provenance';
    ELSIF TG_TABLE_NAME='depreciation_events' THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_depreciation_history', MESSAGE='Immutable depreciation event';
    ELSIF TG_TABLE_NAME='fixed_assets' THEN
        asset_key := OLD.id;
        has_events := EXISTS (SELECT 1 FROM depreciation_events WHERE entity_id=scope AND asset_id=asset_key);
        IF has_events
           OR EXISTS (SELECT 1 FROM asset_period_overrides WHERE entity_id=scope AND asset_id=asset_key) THEN
            fields := ARRAY['cost_basis','salvage_value','depreciation_start_date',
                            'useful_life_quarters','depreciation_method'];
            IF has_events THEN
                fields := fields || ARRAY['expense_category_id','accumulated_depreciation_account_id'];
            END IF;
            IF TG_OP='DELETE' OR EXISTS (SELECT 1 FROM unnest(fields) AS field
                WHERE to_jsonb(NEW)->field IS DISTINCT FROM to_jsonb(OLD)->field) THEN
                RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_asset_history', MESSAGE='Asset terms have saved history';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME='asset_period_overrides' THEN
        asset_key := COALESCE(NEW.asset_id,OLD.asset_id);
        -- History checks must see a posting that committed while this caller
        -- waited; take the same root guard before reading saved events.
        PERFORM 1 FROM fixed_assets WHERE entity_id=scope AND id=asset_key FOR UPDATE;
        IF TG_OP='UPDATE' AND (OLD.entity_id,OLD.asset_id,OLD.sequence,OLD.created_at)
            IS DISTINCT FROM (NEW.entity_id,NEW.asset_id,NEW.sequence,NEW.created_at) THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_asset_history', MESSAGE='Immutable override identity';
        END IF;
        IF (EXISTS (SELECT 1 FROM depreciation_events WHERE entity_id=scope AND asset_id=asset_key)
            OR EXISTS (SELECT 1 FROM asset_period_overrides WHERE entity_id=scope AND asset_id=asset_key
                       AND sequence>COALESCE(OLD.sequence,NEW.sequence)))
            AND (TG_OP<>'UPDATE' OR (to_jsonb(NEW)-'updated_at') IS DISTINCT FROM (to_jsonb(OLD)-'updated_at')) THEN
            RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_asset_history', MESSAGE='Override has committed history';
        END IF;
    ELSIF TG_TABLE_NAME IN ('entries','postings','entry_tags') THEN
        -- Repointable tag rows must preserve both the old and new owner,
        -- including their separate entity scopes. Root/posting identities
        -- themselves remain protected by the canonical migration.
        FOR target IN SELECT DISTINCT r->>'entity_id' AS entity_id,
            CASE WHEN TG_TABLE_NAME='entries' THEN r->>'id' ELSE r->>'entry_id' END AS entry_id
            FROM (VALUES (CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END),
                         (CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END)) AS rows(r)
            WHERE r IS NOT NULL
        LOOP
            IF EXISTS (SELECT 1 FROM depreciation_events WHERE entity_id=target.entity_id AND entry_id=target.entry_id)
               AND (TG_OP<>'UPDATE' OR (to_jsonb(NEW)-ARRAY['version','updated_at'])
                     IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','updated_at'])) THEN
                RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_depreciation_history', MESSAGE='Immutable posted depreciation';
            END IF;
        END LOOP;
    END IF;
    RETURN COALESCE(NEW,OLD);
END;
$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['mixed_use_sources','entries','postings','entry_tags','mixed_use_tags',
        'recurring_schedules','recurring_occurrences','fixed_assets','depreciation_events',
        'asset_period_overrides','document_links','import_records','categories','accounts'] LOOP
        EXECUTE format('CREATE CONSTRAINT TRIGGER domain_integrity AFTER INSERT OR UPDATE OR DELETE ON %I
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_domain_integrity()',t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['recurring_schedules','recurring_occurrences','depreciation_events',
        'fixed_assets','entries','postings'] LOOP
        EXECUTE format('CREATE TRIGGER protect_history BEFORE UPDATE OR DELETE ON %I
            FOR EACH ROW EXECUTE FUNCTION protect_committed_history()',t);
    END LOOP;
END;
$$;

CREATE TRIGGER protect_history BEFORE INSERT OR UPDATE OR DELETE ON asset_period_overrides
    FOR EACH ROW EXECUTE FUNCTION protect_committed_history();
CREATE TRIGGER protect_history BEFORE INSERT OR UPDATE OR DELETE ON entry_tags
    FOR EACH ROW EXECUTE FUNCTION protect_committed_history();

-- Current occurrence membership is part of its target's loaded baseline.
CREATE TRIGGER version_entry AFTER INSERT OR UPDATE OR DELETE ON recurring_occurrences
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('entries','entry_id');
CREATE TRIGGER version_source AFTER INSERT OR UPDATE OR DELETE ON recurring_occurrences
    FOR EACH ROW EXECUTE FUNCTION advance_detail_owner_version('mixed_use_sources','mixed_use_source_id');

-- One-time upgrade validation also covers roots that no later write will touch.
-- Refuse incompatible data atomically; never repair accounting history here.
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT entity_id,id FROM mixed_use_sources ORDER BY entity_id,id LOOP
        PERFORM check_mixed_relationship(r.entity_id,r.id);
    END LOOP;
    FOR r IN SELECT entity_id,id FROM recurring_schedules ORDER BY entity_id,id LOOP
        PERFORM check_schedule_relationship(r.entity_id,r.id);
    END LOOP;
    FOR r IN SELECT entity_id,id FROM fixed_assets ORDER BY entity_id,id LOOP
        PERFORM check_asset_relationship(r.entity_id,r.id);
    END LOOP;
    IF EXISTS (SELECT 1 FROM document_links l JOIN entries e ON e.entity_id=l.entity_id AND e.id=l.entry_id
               WHERE e.projection_kind<>'simple' OR e.mixed_use_source_id IS NOT NULL
                  OR e.depreciation_asset_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM import_records i JOIN entries e ON e.entity_id=i.entity_id AND e.id=i.entry_id
                  WHERE e.projection_kind<>'simple') THEN
        RAISE EXCEPTION USING ERRCODE='23514', CONSTRAINT='ck_link_target', MESSAGE='Invalid existing link target';
    END IF;
END;
$$;
