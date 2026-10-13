CREATE TABLE identity_users (
    id text PRIMARY KEY CHECK (id <> '' AND id = btrim(id)),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','disabled')),
    session_epoch bigint NOT NULL DEFAULT 1 CHECK (session_epoch > 0),
    email text NOT NULL CHECK (btrim(email) <> ''),
    display_name text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE identity_bindings (
    id text PRIMARY KEY CHECK (id <> '' AND id = btrim(id)),
    user_id text NOT NULL UNIQUE REFERENCES identity_users(id),
    issuer text NOT NULL CHECK (btrim(issuer) <> ''),
    subject text NOT NULL CHECK (btrim(subject) <> ''),
    UNIQUE (issuer,subject),
    UNIQUE (id,user_id)
);
CREATE TABLE organizations (
    id text PRIMARY KEY CHECK (id <> '' AND id = btrim(id)),
    name text NOT NULL CHECK (btrim(name) <> ''),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','suspended')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE memberships (
    organization_id text NOT NULL REFERENCES organizations(id),
    user_id text NOT NULL REFERENCES identity_users(id),
    role text NOT NULL CHECK (role IN ('owner','admin','editor','accountant','read_only')),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','inactive')),
    authorization_version bigint NOT NULL DEFAULT 1 CHECK (authorization_version > 0),
    PRIMARY KEY (organization_id,user_id)
);
CREATE INDEX memberships_user ON memberships(user_id,organization_id);
-- Ownership attaches to existing entities without changing ledger baselines,
-- cutover divergence, accounting IDs or export fields. No implicit backfill.
CREATE TABLE organization_entities (
    entity_id text PRIMARY KEY REFERENCES business_entities(id),
    organization_id text NOT NULL REFERENCES organizations(id),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','inactive')),
    UNIQUE (organization_id,entity_id)
);

CREATE FUNCTION guard_identity_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME='identity_users' THEN
        IF NEW.id <> OLD.id OR NEW.session_epoch < OLD.session_epoch THEN
            RAISE EXCEPTION 'Immutable identity or epoch' USING ERRCODE='23514';
        END IF;
        IF NEW.state IS DISTINCT FROM OLD.state THEN
            NEW.session_epoch := OLD.session_epoch + 1;
        END IF;
    ELSIF TG_TABLE_NAME='identity_bindings' THEN
        IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'Identity rebinding requires explicit migration' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='organization_entities' THEN
        IF (NEW.entity_id,NEW.organization_id) IS DISTINCT FROM (OLD.entity_id,OLD.organization_id) THEN
            RAISE EXCEPTION 'Entity ownership cannot change implicitly' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='organizations' THEN
        IF NEW.id IS DISTINCT FROM OLD.id THEN
            RAISE EXCEPTION 'Organization identity cannot change' USING ERRCODE='23514';
        END IF;
    ELSE
        IF (NEW.organization_id,NEW.user_id) IS DISTINCT FROM (OLD.organization_id,OLD.user_id) THEN
            RAISE EXCEPTION 'Membership identity cannot change' USING ERRCODE='23514';
        END IF;
        NEW.authorization_version := OLD.authorization_version + 1;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER identity_change BEFORE UPDATE ON identity_users FOR EACH ROW EXECUTE FUNCTION guard_identity_change();
CREATE TRIGGER identity_change BEFORE UPDATE ON identity_bindings FOR EACH ROW EXECUTE FUNCTION guard_identity_change();
CREATE TRIGGER identity_change BEFORE UPDATE ON organization_entities FOR EACH ROW EXECUTE FUNCTION guard_identity_change();
CREATE TRIGGER identity_change BEFORE UPDATE ON memberships FOR EACH ROW EXECUTE FUNCTION guard_identity_change();
CREATE TRIGGER identity_change BEFORE UPDATE ON organizations FOR EACH ROW EXECUTE FUNCTION guard_identity_change();

CREATE FUNCTION lock_owner_organizations() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME='identity_users' THEN
        PERFORM 1 FROM organizations o JOIN memberships m ON m.organization_id=o.id
            WHERE m.user_id=OLD.id ORDER BY o.id FOR UPDATE OF o;
    ELSE
        PERFORM 1 FROM identity_users WHERE id=COALESCE(NEW.user_id,OLD.user_id) FOR UPDATE;
        PERFORM 1 FROM organizations WHERE id=COALESCE(NEW.organization_id,OLD.organization_id) FOR UPDATE;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END $$;
CREATE TRIGGER owner_locks BEFORE UPDATE OR DELETE ON identity_users FOR EACH ROW EXECUTE FUNCTION lock_owner_organizations();
CREATE TRIGGER owner_locks BEFORE INSERT OR UPDATE OR DELETE ON memberships FOR EACH ROW EXECUTE FUNCTION lock_owner_organizations();

CREATE FUNCTION require_active_owner() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE org text;
BEGIN
    IF TG_TABLE_NAME='organizations' THEN
        org := NEW.id;
    ELSIF TG_TABLE_NAME='identity_users' THEN
        FOR org IN SELECT organization_id FROM memberships WHERE user_id=OLD.id LOOP
            IF EXISTS (SELECT 1 FROM organizations WHERE id=org AND state='active')
                AND NOT EXISTS (SELECT 1 FROM memberships m JOIN identity_users u ON u.id=m.user_id
                    WHERE m.organization_id=org AND m.role='owner' AND m.state='active' AND u.state='active') THEN
                RAISE EXCEPTION 'Active organization requires an active owner' USING ERRCODE='23514';
            END IF;
        END LOOP;
        RETURN NULL;
    ELSE
        org := COALESCE(NEW.organization_id,OLD.organization_id);
    END IF;
    IF EXISTS (SELECT 1 FROM organizations WHERE id=org AND state='active')
        AND NOT EXISTS (SELECT 1 FROM memberships m JOIN identity_users u ON u.id=m.user_id
            WHERE m.organization_id=org AND m.role='owner' AND m.state='active' AND u.state='active') THEN
        RAISE EXCEPTION 'Active organization requires an active owner' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER active_owner AFTER INSERT OR UPDATE ON organizations DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_active_owner();
CREATE CONSTRAINT TRIGGER active_owner AFTER INSERT OR UPDATE OR DELETE ON memberships DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_active_owner();
CREATE CONSTRAINT TRIGGER active_owner AFTER UPDATE OR DELETE ON identity_users DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_active_owner();
