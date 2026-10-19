"""Expiring scoped operator grants and immutable support action history."""
from pathlib import Path

from alembic import op

revision = '0015_support_controls'
down_revision = '0014_document_locations'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Support migrations are forward-only; revoke grants and use compatible recovery.')
