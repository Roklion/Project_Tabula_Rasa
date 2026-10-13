"""Keep owner serialization off identity display-metadata updates."""

from alembic import op

revision = '0008_owner_lock_scope'
down_revision = '0007_identity_sessions'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('DROP TRIGGER owner_locks ON identity_users')
    op.execute('''CREATE TRIGGER owner_locks BEFORE UPDATE OF state OR DELETE ON identity_users
        FOR EACH ROW EXECUTE FUNCTION lock_owner_organizations()''')


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
