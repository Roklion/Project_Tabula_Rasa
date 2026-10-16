"""Durable jobs and atomic append-only bookkeeping history."""

from pathlib import Path

from alembic import op

revision = '0012_operations'
down_revision = '0011_control_plane_join'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Operations migrations are forward-only; use verified recovery.')
