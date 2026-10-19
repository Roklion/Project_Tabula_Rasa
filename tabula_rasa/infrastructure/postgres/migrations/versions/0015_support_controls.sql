-- Provisioned manually by the production administrator, never by tenant routes.
-- Existing identity_users, sessions and memberships remain the only identity store.
CREATE TABLE support_grants (
    user_id text NOT NULL REFERENCES identity_users(id),
    environment text NOT NULL REFERENCES identity_environments(environment),
    organization_id text NOT NULL REFERENCES organizations(id),
    can_admin boolean NOT NULL DEFAULT false,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    approval_reference text NOT NULL CHECK (approval_reference ~ '^[a-zA-Z0-9_-]{1,100}$'),
    PRIMARY KEY (user_id,environment,organization_id)
);
REVOKE ALL ON support_grants FROM PUBLIC;

CREATE TABLE support_actions (
    environment text NOT NULL REFERENCES identity_environments(environment),
    entity_id text NOT NULL REFERENCES business_entities(id),
    id text NOT NULL,
    operation text NOT NULL CHECK (operation IN
        ('diagnostics','audit','preview','revoke_sessions','suspend_member','suspend_organization','provision_grant','revoke_grant')),
    target_user_id text REFERENCES identity_users(id),
    grant_environment text REFERENCES identity_environments(environment),
    grant_can_admin boolean,
    grant_expires_at timestamptz,
    approval_reference text CHECK (approval_reference ~ '^[a-zA-Z0-9_-]{1,100}$'),
    requested_operation text,
    reason_code text NOT NULL CHECK (reason_code IN
        ('incident','access_request','job_failure','migration_failure','connection_failure','audit_review')),
    PRIMARY KEY (entity_id,id)
);
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON support_actions
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT ON support_actions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('id');
ALTER TABLE support_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY scoped_support_read ON support_actions FOR SELECT
    USING (entity_id = current_setting('tabula.audit_reader_entity',true));
CREATE POLICY scoped_support_insert ON support_actions FOR INSERT WITH CHECK (
    entity_id = (NULLIF(current_setting('tabula.audit_context',true),'')::jsonb->>'entity_id')
    AND (NULLIF(current_setting('tabula.audit_context',true),'')::jsonb->>'actor_type') = 'operator'
    AND (NULLIF(current_setting('tabula.audit_context',true),'')::jsonb->>'source') = 'support'
    AND operation IN ('diagnostics','audit','preview','revoke_sessions','suspend_member','suspend_organization')
);
REVOKE ALL ON support_actions FROM PUBLIC;
