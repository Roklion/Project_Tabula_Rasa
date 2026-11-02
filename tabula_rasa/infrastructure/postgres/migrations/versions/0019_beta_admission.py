"""Invitation-only program controls; no release activation or membership changes."""
from pathlib import Path
from alembic import op

revision = '0019_beta_admission'
down_revision = '0018_drive_oauth'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Admission migrations are forward-only; use compatible recovery.')
