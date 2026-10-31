"""Immutable, content-free customer export request and availability evidence."""

from alembic import op

revision = '0017_customer_exports'
down_revision = '0016_business_tenancy'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE customer_export_actions (
        entity_id text NOT NULL REFERENCES business_entities(id),
        id text NOT NULL,
        status text NOT NULL CHECK (status IN ('requested','available','failed')),
        PRIMARY KEY (entity_id,id)
    )''')
    op.execute('''CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON customer_export_actions FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable()''')
    op.execute('''CREATE CONSTRAINT TRIGGER audit_capture AFTER INSERT ON customer_export_actions
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('id')''')
    op.execute('REVOKE ALL ON customer_export_actions FROM PUBLIC')


def downgrade():
    raise ValueError('Customer export evidence is forward-only; use compatible recovery.')
