CREATE TABLE beta_program (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    stage text NOT NULL DEFAULT 'initial' CHECK (stage IN ('initial','expanded')),
    business_cap integer NOT NULL DEFAULT 3,
    user_cap integer,
    invitations_paused boolean NOT NULL DEFAULT true,
    creation_paused boolean NOT NULL DEFAULT true,
    suspended boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1,
    CHECK ((stage='initial' AND business_cap BETWEEN 1 AND 3 AND user_cap IS NULL)
        OR (stage='expanded' AND user_cap IS NOT NULL AND business_cap BETWEEN 1 AND 10 AND user_cap BETWEEN 1 AND 20))
);
INSERT INTO beta_program(id) VALUES (true);
CREATE TABLE beta_internal_users (
    user_id text PRIMARY KEY REFERENCES identity_users(id),
    approval_reference text NOT NULL
);
-- Preserve only the already-operated internal owners, without claiming any books.
INSERT INTO beta_internal_users SELECT DISTINCT user_id,'existing-owner-baseline'
    FROM memberships WHERE role='owner' AND state='active';
CREATE TABLE beta_operator_grants (
    user_id text NOT NULL REFERENCES identity_users(id),
    environment text NOT NULL REFERENCES identity_environments(environment),
    expires_at timestamptz NOT NULL,
    approval_reference text NOT NULL,
    PRIMARY KEY(user_id,environment)
);
CREATE TABLE beta_admissions (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES identity_users(id),
    request_id text NOT NULL,
    business_name text NOT NULL,
    country text NOT NULL CHECK (country IN ('US','CA')),
    currency text NOT NULL CHECK ((country='US' AND currency='USD') OR (country='CA' AND currency='CAD')),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','approved','active','suspended','denied','withdrawn','closed')),
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp()+interval '48 hours'),
    organization_id text UNIQUE REFERENCES organizations(id),
    UNIQUE(user_id,request_id)
);
CREATE TABLE beta_named_users (
    admission_id text NOT NULL REFERENCES beta_admissions(id),
    user_id text NOT NULL REFERENCES identity_users(id),
    state text NOT NULL CHECK (state IN ('approved','invited','active','withdrawn')),
    ever_active boolean NOT NULL DEFAULT false,
    expires_at timestamptz NOT NULL,
    invitation_id text REFERENCES workspace_invitations(id),
    membership_version bigint,
    PRIMARY KEY(admission_id,user_id)
);
CREATE TABLE beta_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id text NOT NULL REFERENCES identity_users(id),
    action text NOT NULL,
    target_id text NOT NULL,
    reason text NOT NULL,
    approval_reference text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON beta_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
REVOKE ALL ON beta_program,beta_internal_users,beta_operator_grants,beta_admissions,beta_named_users,beta_events FROM PUBLIC;
