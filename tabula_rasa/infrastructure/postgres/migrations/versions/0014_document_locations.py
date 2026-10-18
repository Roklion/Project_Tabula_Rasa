"""Managed byte connections and retained source locators, never receipt blobs."""
from alembic import op

revision = '0014_document_locations'
down_revision = '0013_accounting_controls'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE external_connections DROP CONSTRAINT external_connections_provider_check")
    op.execute("ALTER TABLE external_connections ADD CONSTRAINT external_connections_provider_check CHECK (provider IN ('google_drive','s3'))")
    op.execute("""CREATE TABLE document_locations (
        entity_id text NOT NULL,
        document_id text NOT NULL,
        store_kind text NOT NULL CHECK (btrim(store_kind)<>''),
        store_scope_key text NOT NULL CHECK (btrim(store_scope_key)<>''),
        storage_key text NOT NULL CHECK (btrim(storage_key)<>''),
        open_url text NOT NULL DEFAULT '',
        retained_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (entity_id,document_id,store_kind,store_scope_key,storage_key),
        FOREIGN KEY (entity_id,document_id) REFERENCES documents(entity_id,id)
    )""")


def downgrade():
    raise ValueError('Document migrations are forward-only; use a verified recovery procedure.')
