CREATE TABLE customer_lifecycle_requests (
    id text PRIMARY KEY,
    requester_id text NOT NULL REFERENCES identity_users(id),
    entity_id text REFERENCES business_entities(id),
    kind text NOT NULL CHECK (kind IN ('business_closure','account_closure','privacy_erasure')),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','confirmed','cancelled')),
    version bigint NOT NULL DEFAULT 1,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    confirmed_at timestamptz,
    recover_until timestamptz,
    CHECK ((kind='business_closure' AND entity_id IS NOT NULL) OR kind<>'business_closure'),
    CHECK (kind='business_closure' OR entity_id IS NULL),
    CHECK ((kind='business_closure' AND confirmed_at IS NOT NULL) = (recover_until IS NOT NULL))
);
CREATE UNIQUE INDEX one_business_closure ON customer_lifecycle_requests(entity_id)
    WHERE kind='business_closure' AND state<>'cancelled';
CREATE UNIQUE INDEX one_personal_request ON customer_lifecycle_requests(requester_id,kind)
    WHERE entity_id IS NULL AND state<>'cancelled';

-- Separate control-plane audit: no receipt contents, reasons, names or credentials.
CREATE TABLE customer_lifecycle_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL REFERENCES customer_lifecycle_requests(id),
    actor_id text NOT NULL REFERENCES identity_users(id),
    action text NOT NULL CHECK (action IN ('requested','confirmed','cancelled')),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    policy_version text NOT NULL,
    UNIQUE(request_id,action)
);
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON customer_lifecycle_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
REVOKE ALL ON customer_lifecycle_requests,customer_lifecycle_events FROM PUBLIC;

-- Drain in-flight ledger mutations before closure and fence workers/imports too.
-- Closure takes the exclusive form of this lock before any identity/org locks.
CREATE FUNCTION guard_customer_closure() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE scope text;
BEGIN
    scope := CASE WHEN TG_TABLE_NAME='business_entities' THEN
        COALESCE(to_jsonb(NEW)->>'id',to_jsonb(OLD)->>'id') ELSE
        COALESCE(to_jsonb(NEW)->>'entity_id',to_jsonb(OLD)->>'entity_id') END;
    PERFORM pg_advisory_xact_lock_shared(346,hashtext(scope));
    IF EXISTS (SELECT 1 FROM customer_lifecycle_requests WHERE entity_id=scope
        AND kind='business_closure' AND state='confirmed') THEN
        RAISE EXCEPTION 'Business closure prevents bookkeeping mutations' USING ERRCODE='TR403';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
DO $$ DECLARE name text; BEGIN
    FOREACH name IN ARRAY ARRAY['business_entities','accounts','categories','payees','tags','entries',
        'postings','entry_tags','mixed_use_sources','mixed_use_tags','recurring_schedules','schedule_tags',
        'recurring_occurrences','fixed_assets','asset_tags','asset_period_overrides','depreciation_events',
        'mileage_records','mileage_tags','documents','document_links','import_batches','import_records','migration_runs',
        'migration_units','migration_id_mappings','accounting_period_policy','accounting_periods',
        'entry_corrections','recurring_generation_policy'] LOOP
        EXECUTE format('CREATE TRIGGER customer_closure_guard BEFORE INSERT OR UPDATE OR DELETE ON %I
            FOR EACH ROW EXECUTE FUNCTION guard_customer_closure()',name);
    END LOOP;
END $$;
