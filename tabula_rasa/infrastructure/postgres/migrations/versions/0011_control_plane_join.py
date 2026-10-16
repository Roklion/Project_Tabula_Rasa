"""Mark the integrated control-plane head after canonical workspace onboarding."""

revision = '0011_control_plane_join'
down_revision = '0010_onboarding_routes'
branch_labels = None
depends_on = None


def upgrade():
    pass  # The preceding revisions already supply the integrated schema.


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
