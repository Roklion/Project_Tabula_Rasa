"""Recipient-bound invitations and atomic bootstrap receipts; no ledger rewrite."""

from alembic import op

revision = '0010_workspace_lifecycle'
down_revision = '0009_external_connections'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE identity_sessions ADD COLUMN verified_email text')
    op.execute('''CREATE TABLE workspace_invitations (
        id text PRIMARY KEY,
        credential_hash text NOT NULL UNIQUE,
        organization_id text NOT NULL REFERENCES organizations(id),
        email_key text NOT NULL,
        role text NOT NULL CHECK (role IN ('admin','editor','accountant','read_only')),
        inviter_id text NOT NULL REFERENCES identity_users(id),
        expires_at timestamptz NOT NULL,
        state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','accepted','declined','revoked')),
        responded_by text REFERENCES identity_users(id),
        created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    op.execute('CREATE INDEX workspace_invitations_org ON workspace_invitations(organization_id)')
    op.execute('''CREATE TABLE workspace_bootstraps (
        user_id text NOT NULL REFERENCES identity_users(id),
        request_id text NOT NULL,
        payload_hash text NOT NULL,
        organization_id text NOT NULL REFERENCES organizations(id),
        entity_id text NOT NULL REFERENCES business_entities(id),
        PRIMARY KEY (user_id,request_id),
        FOREIGN KEY (organization_id,entity_id) REFERENCES organization_entities(organization_id,entity_id)
    )''')


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
