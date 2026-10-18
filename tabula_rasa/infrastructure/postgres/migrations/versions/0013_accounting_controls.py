"""Explicit recurring authority and opt-in accounting periods."""

from pathlib import Path

from alembic import op

revision = '0013_accounting_controls'
down_revision = '0012_operations'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Accounting controls are forward-only; use the documented authority rollback.')
