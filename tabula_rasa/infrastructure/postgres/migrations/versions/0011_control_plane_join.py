"""Join independent workspace/onboarding and external-connection forward branches."""

revision = '0011_control_plane_join'
down_revision = ('0010_onboarding_routes', '0009_external_connections')
branch_labels = None
depends_on = None


def upgrade():
    pass  # Both branches retain their deployed schemas and data.


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
