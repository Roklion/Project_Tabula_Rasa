"""Reversible customer closure and immutable lifecycle request evidence."""
from pathlib import Path
from alembic import op

revision = '0021_customer_lifecycle'
down_revision = '0020_book_currency'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Lifecycle migrations are forward-only; use compatible recovery.')
