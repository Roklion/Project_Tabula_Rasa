"""Durable opaque sessions and single-use OIDC transactions."""

from alembic import op

revision = '0007_identity_sessions'
down_revision = '0006_identity_control_plane'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE identity_environments (
        environment text PRIMARY KEY CHECK (environment IN ('development','test','staging','production')),
        configuration_hash text NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
        epoch bigint NOT NULL DEFAULT 1 CHECK (epoch > 0)
    )''')
    op.execute('''CREATE TABLE identity_login_transactions (
        credential_hash text PRIMARY KEY CHECK (credential_hash ~ '^[0-9a-f]{64}$'),
        environment text NOT NULL REFERENCES identity_environments(environment),
        environment_epoch bigint NOT NULL CHECK (environment_epoch > 0),
        state text NOT NULL UNIQUE, nonce text NOT NULL, verifier text NOT NULL,
        return_path text NOT NULL CHECK (return_path IN ('/','/onboarding')),
        expires_at timestamptz NOT NULL, consumed_at timestamptz
    )''')
    op.execute('''CREATE TABLE identity_sessions (
        credential_hash text PRIMARY KEY CHECK (credential_hash ~ '^[0-9a-f]{64}$'),
        environment text NOT NULL REFERENCES identity_environments(environment),
        environment_epoch bigint NOT NULL CHECK (environment_epoch > 0),
        user_id text NOT NULL REFERENCES identity_users(id),
        binding_id text NOT NULL,
        user_epoch bigint NOT NULL CHECK (user_epoch > 0),
        csrf_token text NOT NULL, cache_id text NOT NULL UNIQUE,
        created_at timestamptz NOT NULL,
        authenticated_at timestamptz NOT NULL,
        idle_expires_at timestamptz NOT NULL, absolute_expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        organization_id text, entity_id text,
        FOREIGN KEY (binding_id,user_id) REFERENCES identity_bindings(id,user_id),
        FOREIGN KEY (organization_id,entity_id) REFERENCES organization_entities(organization_id,entity_id),
        CHECK ((organization_id IS NULL) = (entity_id IS NULL)),
        CHECK (idle_expires_at <= absolute_expires_at AND created_at < idle_expires_at),
        CHECK (absolute_expires_at <= created_at + INTERVAL '12 hours')
    )''')
    op.execute('CREATE INDEX identity_sessions_user ON identity_sessions(user_id)')


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
