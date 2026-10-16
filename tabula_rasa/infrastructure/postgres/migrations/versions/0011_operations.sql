-- Private bookkeeping history, deliberately excluded from ordinary entity exports.
CREATE TABLE audit_activation (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO audit_activation DEFAULT VALUES;
CREATE TABLE audit_events (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    entity_id text NOT NULL REFERENCES business_entities(id),
    organization_id text,
    operation_id text NOT NULL CHECK (btrim(operation_id) <> ''),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_type text NOT NULL CHECK (actor_type IN ('user','system','worker','operator')),
    actor_id text NOT NULL CHECK (btrim(actor_id) <> ''),
    correlation_id text NOT NULL,
    source text NOT NULL CHECK (btrim(source) <> ''),
    action text NOT NULL CHECK (action IN ('create','update','delete')),
    target_type text NOT NULL,
    target_key jsonb NOT NULL,
    before_summary jsonb,
    after_summary jsonb,
    after_digest text,
    batch_id text,
    UNIQUE (entity_id,operation_id,target_type,target_key)
);
CREATE INDEX audit_entity_time ON audit_events(entity_id,occurred_at,sequence);
CREATE INDEX audit_entity_target ON audit_events(entity_id,target_type);
CREATE INDEX audit_entity_operation ON audit_events(entity_id,operation_id);
-- A watermark is evidence of unavailable history, never a fabricated create event.
CREATE TABLE audit_baseline (
    entity_id text NOT NULL REFERENCES business_entities(id),
    target_type text NOT NULL,
    target_key jsonb NOT NULL,
    row_digest text NOT NULL,
    history_status text NOT NULL DEFAULT 'pre_activation_unavailable'
        CHECK (history_status = 'pre_activation_unavailable'),
    PRIMARY KEY (entity_id,target_type,target_key)
);

CREATE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit history is append-only' USING ERRCODE='23514';
END $$;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON audit_baseline
    FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON audit_baseline
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_activation
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
CREATE FUNCTION audit_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'Audit events require a bookkeeping mutation' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER capture_only BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_insert_guard();

-- Safe summaries exclude all free text, filenames, locations, receipt bytes and credentials.
-- Digests support accidental integrity checks, not cryptographic tamper evidence.
CREATE FUNCTION audit_summary(value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN value IS NULL THEN NULL ELSE
        COALESCE(jsonb_object_agg(key,val), '{}'::jsonb) || jsonb_build_object('_redacted',true) END
    FROM jsonb_each(value) AS fields(key,val)
    WHERE key = ANY (ARRAY['id','entity_id','version','kind','projection_kind','status','active',
        'txn_date','trip_date','amount','miles','side','account_id','category_id','entry_id',
        'mixed_use_source_id','source_kind','schedule_id','scheduled_date','asset_id','sequence',
        'document_id','batch_id','source_position','record_kind','format_version','occurrence_type',
        'parent_id','classification','opening_balance','total_expense','business_amount',
        'source_id','tag_id','payee_id','position']);
$$;

CREATE FUNCTION audit_row_digest(value jsonb, table_name text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT md5((value - CASE WHEN table_name='recurring_schedules'
        THEN ARRAY['updated_at','attention_code','attention_at'] ELSE ARRAY['updated_at'] END)::text);
$$;

CREATE FUNCTION capture_bookkeeping_audit() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE old_row jsonb; row_value jsonb; final_row jsonb; key_value jsonb := '{}';
    field text; scope text; context jsonb; org text; batch text; summary jsonb;
    predicate text := ''; event_action text; previous_xid xid8;
BEGIN
    IF TG_OP <> 'INSERT' THEN old_row := to_jsonb(OLD); END IF;
    IF TG_OP = 'DELETE' THEN row_value := old_row; ELSE row_value := to_jsonb(NEW); END IF;
    -- Deferred capture reads final state, so intermediate versions coalesce.
    IF TG_OP = 'UPDATE' AND
        (row_value - ARRAY['updated_at','attention_code','attention_at']) IS NOT DISTINCT FROM
        (old_row - ARRAY['updated_at','attention_code','attention_at']) THEN RETURN NULL; END IF;
    scope := row_value->>'entity_id';
    context := NULLIF(current_setting('tabula.audit_context',true),'')::jsonb;
    IF context IS NULL OR COALESCE(context->>'actor_type','') NOT IN ('user','system','worker','operator')
        OR btrim(COALESCE(context->>'actor_id','')) = ''
        OR btrim(COALESCE(context->>'operation_id','')) = ''
        OR btrim(COALESCE(context->>'source','')) = ''
        OR (COALESCE(context->>'entity_id','') <> '' AND context->>'entity_id' <> scope) THEN
        RAISE EXCEPTION 'Trusted audit context required' USING ERRCODE='23514';
    END IF;
    SELECT organization_id INTO org FROM organization_entities WHERE entity_id=scope;
    IF context->>'actor_type' = 'user' AND NOT EXISTS (
        SELECT 1 FROM memberships m JOIN identity_users u ON u.id=m.user_id
        JOIN organizations o ON o.id=m.organization_id
        JOIN organization_entities e ON e.organization_id=o.id AND e.entity_id=scope AND e.state='active'
        WHERE m.organization_id=org AND m.user_id=context->>'actor_id'
        AND m.state='active' AND u.state='active' AND o.state='active'
        AND m.role IN ('owner','admin','editor','accountant')) THEN
        RAISE EXCEPTION 'Audit actor is not an authorized member' USING ERRCODE='23514';
    END IF;
    FOREACH field IN ARRAY TG_ARGV LOOP
        key_value := key_value || jsonb_build_object(field,row_value->field);
        predicate := predicate || format(' AND t.%I=k.%I',field,field);
    END LOOP;
    SELECT transaction_id INTO previous_xid FROM audit_events WHERE entity_id=scope
        AND operation_id=context->>'operation_id' AND target_type=TG_TABLE_NAME AND target_key=key_value;
    IF previous_xid IS NOT NULL THEN
        IF previous_xid<>pg_current_xact_id() THEN
            RAISE EXCEPTION 'Audit operation identity already committed' USING ERRCODE='23505';
        END IF;
        RETURN NULL;
    END IF;
    -- Typed primary-key equality uses the existing entity-leading indexes.
    EXECUTE format('SELECT to_jsonb(t) FROM public.%I t CROSS JOIN
        jsonb_populate_record(NULL::public.%I,$1) k WHERE t.entity_id=$2 %s',
        TG_TABLE_NAME,TG_TABLE_NAME,predicate)
        INTO final_row USING key_value,scope;
    IF old_row IS NULL AND final_row IS NULL THEN RETURN NULL; END IF;
    event_action := CASE WHEN old_row IS NULL THEN 'create' WHEN final_row IS NULL THEN 'delete' ELSE 'update' END;
    summary := audit_summary(final_row);
    batch := COALESCE(row_value->>'batch_id',NULLIF(context->>'batch_id',''),
        CASE WHEN TG_TABLE_NAME='import_batches' THEN row_value->>'id' END);
    IF TG_TABLE_NAME='import_batches' AND final_row IS NOT NULL THEN
        SELECT summary || jsonb_build_object(
            CASE WHEN event_action='create' THEN 'committed_count' ELSE 'remaining_record_count' END,count(*),
            'first_position',min(source_position),'last_position',max(source_position)) INTO summary
            FROM import_records WHERE entity_id=scope AND batch_id=row_value->>'id';
    ELSIF TG_TABLE_NAME IN ('entries','mileage_records') THEN
        SELECT batch_id INTO batch FROM import_records WHERE entity_id=scope
            AND CASE WHEN TG_TABLE_NAME='entries' THEN entry_id ELSE mileage_id END = row_value->>'id'
            LIMIT 1;
    END IF;
    INSERT INTO audit_events(entity_id,organization_id,operation_id,actor_type,actor_id,correlation_id,
        source,action,target_type,target_key,before_summary,after_summary,after_digest,batch_id)
    VALUES (scope,org,context->>'operation_id',context->>'actor_type',context->>'actor_id',
        COALESCE(context->>'correlation_id',''),context->>'source',
        event_action,
        TG_TABLE_NAME,key_value,audit_summary(old_row),summary,audit_row_digest(final_row,TG_TABLE_NAME),batch);
    RETURN NULL;
END $$;

DO $$
DECLARE definition text[]; table_name text; keys text[]; key_sql text;
BEGIN
    FOREACH definition SLICE 1 IN ARRAY ARRAY[
        ['accounts','id'],['categories','id'],['payees','id'],['tags','id'],
        ['entries','id'],['postings','id'],['mixed_use_sources','id'],
        ['recurring_schedules','id'],['fixed_assets','id'],['mileage_records','id'],
        ['documents','id'],['import_batches','id'],['migration_runs','id'],
        ['entry_tags','entry_id,tag_id'],['mixed_use_tags','source_id,tag_id'],
        ['schedule_tags','schedule_id,tag_id'],['asset_tags','asset_id,tag_id'],
        ['mileage_tags','mileage_id,tag_id'],['document_links','document_id'],
        ['recurring_occurrences','schedule_id,scheduled_date'],
        ['asset_period_overrides','asset_id,sequence'],['depreciation_events','asset_id,sequence'],
        ['import_records','batch_id,source_position']
    ] LOOP
        table_name := definition[1]; keys := string_to_array(definition[2],',');
        SELECT string_agg(format('%L,to_jsonb(t)->%L',k,k),',') INTO key_sql FROM unnest(keys) k;
        EXECUTE format('INSERT INTO audit_baseline(entity_id,target_type,target_key,row_digest)
            SELECT entity_id,%L,jsonb_build_object(%s),audit_row_digest(to_jsonb(t),%L) FROM %I t',
            table_name,key_sql,table_name,table_name);
        SELECT string_agg(quote_literal(k),',') INTO key_sql FROM unnest(keys) k;
        EXECUTE format('CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT OR UPDATE OR DELETE ON %I
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit(%s)',
            table_name,key_sql);
    END LOOP;
END $$;

-- The activation snapshot is frozen after the one-time backfill above.
CREATE TRIGGER immutable_insert BEFORE INSERT ON audit_baseline
    FOR EACH ROW EXECUTE FUNCTION audit_immutable();

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_baseline ENABLE ROW LEVEL SECURITY;
CREATE POLICY scoped_audit_read ON audit_events FOR SELECT
    USING (entity_id = current_setting('tabula.audit_reader_entity',true));
CREATE POLICY scoped_baseline_read ON audit_baseline FOR SELECT
    USING (entity_id = current_setting('tabula.audit_reader_entity',true));
REVOKE ALL ON audit_events,audit_baseline,audit_activation FROM PUBLIC;
REVOKE ALL ON FUNCTION capture_bookkeeping_audit() FROM PUBLIC;

CREATE TABLE job_definitions (
    entity_id text NOT NULL REFERENCES business_entities(id),
    id text NOT NULL,
    job_type text NOT NULL,
    interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 60 AND 31536000),
    next_due timestamptz NOT NULL,
    paused boolean NOT NULL DEFAULT false,
    PRIMARY KEY(entity_id,id)
);
CREATE TABLE jobs (
    entity_id text NOT NULL REFERENCES business_entities(id),
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    job_type text NOT NULL,
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    definition_id text,
    due_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','succeeded','cancelled','dead')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    lease_id uuid,
    lease_until timestamptz,
    failure_code text CHECK (failure_code IN ('transient','poison','lease_expired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    PRIMARY KEY(entity_id,id),
    UNIQUE(entity_id,idempotency_key),
    FOREIGN KEY(entity_id,definition_id) REFERENCES job_definitions(entity_id,id),
    CHECK ((state='running') = (lease_id IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX jobs_due ON jobs(entity_id,due_at) WHERE state IN ('queued','running');
CREATE TABLE job_attempts (
    entity_id text NOT NULL REFERENCES business_entities(id),
    job_id uuid NOT NULL,
    lease_id uuid NOT NULL,
    worker_id text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    outcome text NOT NULL DEFAULT 'running' CHECK (outcome IN ('running','succeeded','transient','poison','lease_expired','cancelled')),
    PRIMARY KEY(entity_id,job_id,lease_id),
    FOREIGN KEY(entity_id,job_id) REFERENCES jobs(entity_id,id)
);
