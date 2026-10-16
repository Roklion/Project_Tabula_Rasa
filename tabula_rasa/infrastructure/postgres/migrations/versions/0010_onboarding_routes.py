"""Allow the explicit invitation return route without changing ledger inventory."""

from alembic import op

revision = '0010_onboarding_routes'
down_revision = '0010_workspace_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE identity_login_transactions DROP CONSTRAINT identity_login_transactions_return_path_check')
    op.execute("""ALTER TABLE identity_login_transactions ADD CONSTRAINT identity_login_transactions_return_path_check
        CHECK (return_path IN ('/','/onboarding','/invitations'))""")


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
