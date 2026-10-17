-- No existing entity is activated by this migration.
ALTER TABLE jobs ADD COLUMN target_id text;
ALTER TABLE jobs ADD COLUMN business_date date;
ALTER TABLE jobs ADD COLUMN generation_revision bigint;
CREATE TABLE recurring_generation_policy (
    entity_id text PRIMARY KEY REFERENCES business_entities(id),
    authority text NOT NULL CHECK (authority IN ('explicit','worker')),
    time_zone text NOT NULL,
    revision bigint NOT NULL DEFAULT 1
);

CREATE TABLE accounting_period_policy (
    entity_id text PRIMARY KEY REFERENCES business_entities(id),
    enabled boolean NOT NULL DEFAULT false,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    version bigint NOT NULL DEFAULT 1
);
CREATE TABLE accounting_periods (
    entity_id text NOT NULL REFERENCES business_entities(id),
    period_start date NOT NULL CHECK (extract(day FROM period_start)=1),
    closed boolean NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    version bigint NOT NULL DEFAULT 1,
    PRIMARY KEY (entity_id,period_start)
);
CREATE TABLE entry_corrections (
    entity_id text NOT NULL REFERENCES business_entities(id),
    id text NOT NULL,
    original_entry_id text NOT NULL,
    reversal_entry_id text NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    PRIMARY KEY(entity_id,id),
    UNIQUE(entity_id,original_entry_id),
    UNIQUE(entity_id,reversal_entry_id),
    CHECK (original_entry_id <> reversal_entry_id),
    FOREIGN KEY(entity_id,original_entry_id) REFERENCES entries(entity_id,id),
    FOREIGN KEY(entity_id,reversal_entry_id) REFERENCES entries(entity_id,id)
);
-- Keep each close/unlock/adoption reason after the current state changes again.
CREATE TABLE accounting_period_actions (
    entity_id text NOT NULL REFERENCES business_entities(id),
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    control_action text NOT NULL CHECK (control_action IN ('enable','disable','close','unlock')),
    period_start date,
    previous_state boolean,
    new_state boolean NOT NULL,
    version bigint NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(entity_id,id)
);
CREATE TRIGGER capture_only BEFORE INSERT ON accounting_period_actions
    FOR EACH ROW EXECUTE FUNCTION audit_insert_guard();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON accounting_period_actions
    FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON accounting_period_actions
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
CREATE FUNCTION capture_period_action() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE enabled boolean; previous boolean; month date; action text;
BEGIN
    IF TG_TABLE_NAME='accounting_period_policy' THEN
        enabled := NEW.enabled; IF TG_OP='UPDATE' THEN previous := OLD.enabled; END IF;
        action := CASE WHEN enabled THEN 'enable' ELSE 'disable' END;
    ELSE
        enabled := NEW.closed; month := NEW.period_start;
        IF TG_OP='UPDATE' THEN previous := OLD.closed; END IF;
        action := CASE WHEN enabled THEN 'close' ELSE 'unlock' END;
    END IF;
    INSERT INTO accounting_period_actions(entity_id,control_action,period_start,previous_state,new_state,version,reason)
        VALUES (NEW.entity_id,action,month,previous,enabled,NEW.version,NEW.reason);
    RETURN NULL;
END $$;
CREATE TRIGGER action_history AFTER INSERT OR UPDATE ON accounting_period_policy
    FOR EACH ROW EXECUTE FUNCTION capture_period_action();
CREATE TRIGGER action_history AFTER INSERT OR UPDATE ON accounting_periods
    FOR EACH ROW EXECUTE FUNCTION capture_period_action();
REVOKE ALL ON FUNCTION capture_period_action() FROM PUBLIC;
REVOKE ALL ON accounting_period_actions FROM PUBLIC;
ALTER TABLE accounting_period_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY scoped_period_action_read ON accounting_period_actions FOR SELECT
    USING (entity_id=current_setting('tabula.audit_reader_entity',true));

-- Revalidate named authority in the same transaction as the privileged action.
-- GUC actor attribution is trusted server infrastructure, as in #335.
CREATE FUNCTION require_period_authority(scope text, action text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE context jsonb; member_role text;
BEGIN
    context := NULLIF(current_setting('tabula.audit_context',true),'')::jsonb;
    IF context->>'entity_id' IS DISTINCT FROM scope THEN
        RAISE EXCEPTION 'Period action denied' USING ERRCODE='TR403';
    END IF;
    IF context->>'actor_type'='operator' AND btrim(context->>'actor_id')<>'' THEN RETURN; END IF;
    IF context->>'actor_type'='user' AND action<>'configure' THEN
        SELECT m.role INTO member_role FROM memberships m
        JOIN identity_users u ON u.id=m.user_id
        JOIN organizations o ON o.id=m.organization_id
        JOIN organization_entities e ON e.organization_id=o.id AND e.entity_id=scope
        WHERE m.user_id=context->>'actor_id' AND m.state='active' AND u.state='active'
          AND o.state='active' AND e.state='active'
        FOR SHARE OF m,u,o,e;
        IF (action='close' AND member_role IN ('owner','admin'))
           OR (action='unlock' AND member_role='owner')
           OR (action='correct' AND member_role IN ('owner','admin','accountant')) THEN RETURN; END IF;
    END IF;
    RAISE EXCEPTION 'Period action denied' USING ERRCODE='TR403';
END $$;

CREATE FUNCTION guard_period_control() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE scope text;
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Period history cannot be removed' USING ERRCODE='23514';
    END IF;
    scope := NEW.entity_id;
    PERFORM pg_advisory_xact_lock(336,hashtext(scope));
    IF TG_TABLE_NAME='accounting_period_policy' THEN
        PERFORM require_period_authority(scope,'configure');
    ELSE
        PERFORM require_period_authority(scope,CASE WHEN NEW.closed THEN 'close' ELSE 'unlock' END);
        IF NOT EXISTS (SELECT 1 FROM accounting_period_policy WHERE entity_id=scope AND enabled) THEN
            RAISE EXCEPTION 'Period policy is disabled' USING ERRCODE='TR409';
        END IF;
    END IF;
    IF TG_OP='UPDATE' THEN
        IF NEW.entity_id<>OLD.entity_id THEN RAISE EXCEPTION 'Invalid scope' USING ERRCODE='23514'; END IF;
        NEW.version := OLD.version+1;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER period_control BEFORE INSERT OR UPDATE OR DELETE ON accounting_period_policy
    FOR EACH ROW EXECUTE FUNCTION guard_period_control();
CREATE TRIGGER period_control BEFORE INSERT OR UPDATE OR DELETE ON accounting_periods
    FOR EACH ROW EXECUTE FUNCTION guard_period_control();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON entry_corrections
    FOR EACH ROW EXECUTE FUNCTION audit_immutable();

CREATE FUNCTION closed_accounting_date(scope text, day date) RETURNS boolean LANGUAGE sql VOLATILE AS $$
    SELECT EXISTS (SELECT 1 FROM accounting_periods WHERE entity_id=scope AND closed
        AND period_start=date_trunc('month',day)::date);
$$;

-- Shared transaction locks let unrelated writers proceed concurrently. Close,
-- unlock and activation take the exclusive counterpart, so a write either
-- commits before close or observes the closed month. Runtime writes use READ COMMITTED.
CREATE FUNCTION guard_accounting_period() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE value jsonb; values_to_check jsonb[]; scope text; day date; linked_id text; locked boolean;
BEGIN
    IF TG_OP='UPDATE' AND (to_jsonb(OLD)-ARRAY['version','updated_at']) =
        (to_jsonb(NEW)-ARRAY['version','updated_at']) THEN RETURN NEW; END IF;
    IF TG_OP='INSERT' THEN values_to_check := ARRAY[to_jsonb(NEW)];
    ELSIF TG_OP='DELETE' THEN values_to_check := ARRAY[to_jsonb(OLD)];
    ELSE values_to_check := ARRAY[to_jsonb(OLD),to_jsonb(NEW)]; END IF;
    FOREACH value IN ARRAY values_to_check LOOP
        scope := value->>'entity_id'; day := NULL; linked_id := NULL; locked := false;
        PERFORM pg_advisory_xact_lock_shared(336,hashtext(scope));
        -- Corrected entries remain immutable even after unlocking/disabling.
        IF TG_TABLE_NAME='entries' THEN linked_id := value->>'id';
        ELSIF TG_TABLE_NAME IN ('postings','entry_tags') THEN linked_id := value->>'entry_id'; END IF;
        IF linked_id IS NOT NULL AND EXISTS (SELECT 1 FROM entry_corrections WHERE entity_id=scope
            AND linked_id IN (original_entry_id,reversal_entry_id)) THEN
            RAISE EXCEPTION 'Corrected history is immutable' USING ERRCODE='TR409';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM accounting_period_policy WHERE entity_id=scope AND enabled) THEN CONTINUE; END IF;
        IF TG_TABLE_NAME IN ('entries','mixed_use_sources') THEN day := (value->>'txn_date')::date;
        ELSIF TG_TABLE_NAME IN ('postings','entry_tags') THEN
            SELECT txn_date INTO day FROM entries WHERE entity_id=scope AND id=linked_id;
        ELSIF TG_TABLE_NAME='mixed_use_tags' THEN
            SELECT txn_date INTO day FROM mixed_use_sources WHERE entity_id=scope AND id=value->>'source_id';
        ELSIF TG_TABLE_NAME IN ('depreciation_events','recurring_occurrences') THEN day := (value->>'scheduled_date')::date;
        ELSIF TG_TABLE_NAME IN ('fixed_assets','asset_tags','asset_period_overrides') THEN
            SELECT EXISTS (SELECT 1 FROM depreciation_events WHERE entity_id=scope
                AND asset_id=CASE WHEN TG_TABLE_NAME='fixed_assets' THEN value->>'id' ELSE value->>'asset_id' END
                AND closed_accounting_date(scope,scheduled_date)) INTO locked;
        ELSIF TG_TABLE_NAME='accounts' THEN
            IF (TG_OP='INSERT' AND (value->>'opening_balance')::numeric<>0) OR TG_OP='DELETE'
               OR (TG_OP='UPDATE' AND (to_jsonb(OLD)->'opening_balance',to_jsonb(OLD)->'classification',
                to_jsonb(OLD)->'parent_id',to_jsonb(OLD)->'type') IS DISTINCT FROM
                (to_jsonb(NEW)->'opening_balance',to_jsonb(NEW)->'classification',to_jsonb(NEW)->'parent_id',to_jsonb(NEW)->'type')) THEN
                SELECT EXISTS (SELECT 1 FROM accounting_periods WHERE entity_id=scope AND closed) INTO locked;
            END IF;
        ELSIF TG_TABLE_NAME='categories' AND TG_OP='UPDATE' AND
            (to_jsonb(OLD)->'kind',to_jsonb(OLD)->'parent_id') IS DISTINCT FROM
            (to_jsonb(NEW)->'kind',to_jsonb(NEW)->'parent_id') THEN
            SELECT EXISTS (SELECT 1 FROM postings p JOIN entries e ON e.entity_id=p.entity_id AND e.id=p.entry_id
                WHERE p.entity_id=scope AND p.category_id=value->>'id' AND closed_accounting_date(scope,e.txn_date)) INTO locked;
        END IF;
        IF locked OR closed_accounting_date(scope,day) THEN
            RAISE EXCEPTION 'Accounting period is closed' USING ERRCODE='TR423';
        END IF;
    END LOOP;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;

DO $$ DECLARE name text; BEGIN
    FOREACH name IN ARRAY ARRAY['entries','postings','entry_tags','mixed_use_sources','mixed_use_tags',
        'depreciation_events','recurring_occurrences','fixed_assets','asset_tags','asset_period_overrides','accounts','categories'] LOOP
        EXECUTE format('CREATE TRIGGER accounting_period_guard BEFORE INSERT OR UPDATE OR DELETE ON %I
            FOR EACH ROW EXECUTE FUNCTION guard_accounting_period()',name);
    END LOOP;
    FOREACH name IN ARRAY ARRAY['accounting_period_policy','accounting_periods','entry_corrections'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON %I
            FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable()',name);
    END LOOP;
END $$;

CREATE FUNCTION guard_entry_correction() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM require_period_authority(NEW.entity_id,'correct');
    RETURN NEW;
END $$;
CREATE TRIGGER correction_authority BEFORE INSERT ON entry_corrections
    FOR EACH ROW EXECUTE FUNCTION guard_entry_correction();

-- Extend the existing minimization owner; reasons remain in restricted tables,
-- never in ordinary telemetry or audit summaries. Digests still bind final state.
CREATE OR REPLACE FUNCTION audit_summary(value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN value IS NULL THEN NULL ELSE
        COALESCE(jsonb_object_agg(key,val), '{}'::jsonb) || jsonb_build_object('_redacted',true) END
    FROM jsonb_each(value) AS fields(key,val)
    WHERE key = ANY (ARRAY['id','entity_id','version','kind','projection_kind','status','active',
        'txn_date','trip_date','amount','miles','side','account_id','category_id','entry_id',
        'mixed_use_source_id','source_kind','schedule_id','scheduled_date','asset_id','sequence',
        'document_id','batch_id','source_position','record_kind','format_version','occurrence_type',
        'parent_id','classification','opening_balance','total_expense','business_amount',
        'source_id','tag_id','payee_id','position','period_start','closed','enabled',
        'original_entry_id','reversal_entry_id','authority','time_zone','revision',
        'control_action','previous_state','new_state']);
$$;
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON accounting_period_policy
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('entity_id');
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON accounting_periods
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('period_start');
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON entry_corrections
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('id');
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON recurring_generation_policy
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('entity_id');
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON accounting_period_actions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('id');
