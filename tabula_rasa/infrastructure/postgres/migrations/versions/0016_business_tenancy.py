"""One retained business per private authorization container; no data conversion."""

from alembic import op

revision = '0016_business_tenancy'
down_revision = '0015_support_controls'
branch_labels = None
depends_on = None


def upgrade():
    # Freeze bindings before the preflight; the explicit migration transaction
    # either installs the constraint or leaves the old schema/data unchanged.
    op.execute('LOCK TABLE organization_entities IN ACCESS EXCLUSIVE MODE')
    op.execute('''DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM organization_entities
                   GROUP BY organization_id HAVING count(*) > 1) THEN
            RAISE EXCEPTION 'Business tenancy reconciliation required; see the business tenancy runbook'
                USING ERRCODE='23514';
        END IF;
    END $$''')
    # Inactive bindings reserve their container too. Entity uniqueness and
    # immutable ownership are already enforced by the published identity schema.
    op.execute('ALTER TABLE organization_entities ADD CONSTRAINT one_business_per_organization UNIQUE (organization_id)')


def downgrade():
    raise ValueError('Business tenancy is forward-only; use compatible recovery.')
