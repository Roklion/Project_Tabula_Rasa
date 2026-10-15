"""Tenant-owned provider references and explicit legacy claims; no tokens."""
from alembic import op

revision = '0009_external_connections'
down_revision = '0008_owner_lock_scope'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE external_connections (
        entity_id text NOT NULL,
        organization_id text NOT NULL,
        provider text NOT NULL CHECK (provider='google_drive'),
        secret_ref text NOT NULL UNIQUE CHECK (secret_ref ~ '^[0-9a-f]{32}$'),
        profile_key text NOT NULL CHECK (profile_key ~ '^[a-z][a-z0-9_-]{0,47}$'),
        store_scope_key text NOT NULL CHECK (btrim(store_scope_key)<>''),
        required_scopes jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('pending','connected','disconnected','reconnect_required')),
        revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
        updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (entity_id,provider),
        UNIQUE (provider,profile_key),
        UNIQUE (provider,store_scope_key),
        FOREIGN KEY (organization_id,entity_id) REFERENCES organization_entities(organization_id,entity_id)
    )""")
    op.execute("""CREATE TABLE legacy_entity_claims (
        entity_id text PRIMARY KEY,
        organization_id text NOT NULL,
        profile_key text NOT NULL UNIQUE,
        owner_id text NOT NULL REFERENCES identity_users(id),
        identity_binding_id text NOT NULL,
        approval_sha256 text NOT NULL CHECK (approval_sha256 ~ '^[0-9a-f]{64}$'),
        binding_sha256 text NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
        created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (identity_binding_id,owner_id) REFERENCES identity_bindings(id,user_id),
        FOREIGN KEY (organization_id,entity_id) REFERENCES organization_entities(organization_id,entity_id)
    )""")


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
