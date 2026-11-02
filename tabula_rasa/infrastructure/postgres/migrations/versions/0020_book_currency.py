"""Independent fixed-currency books; existing currency is immutable."""
from pathlib import Path
from alembic import op

revision = '0020_book_currency'
down_revision = '0019_beta_admission'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'))


def downgrade():
    raise ValueError('Currency migrations are forward-only; use compatible recovery.')
