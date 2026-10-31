"""Single-use customer Drive authorization transactions; credentials stay encrypted."""
from alembic import op

revision = '0017_drive_oauth'
down_revision = '0016_business_tenancy'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE drive_oauth_requests (
        entity_id text PRIMARY KEY,
        organization_id text NOT NULL,
        actor_id text NOT NULL REFERENCES identity_users(id),
        session_hash text NOT NULL,
        state_hash text NOT NULL UNIQUE,
        secret_ref text NOT NULL,
        expected_revision bigint NOT NULL,
        expires_at timestamptz NOT NULL,
        consumed boolean NOT NULL DEFAULT false,
        outcome text NOT NULL CHECK (outcome IN ('connecting','failed','complete')),
        FOREIGN KEY (organization_id,entity_id) REFERENCES organization_entities(organization_id,entity_id)
    )''')


def downgrade():
    raise ValueError('Connection migrations are forward-only; use verified recovery.')
