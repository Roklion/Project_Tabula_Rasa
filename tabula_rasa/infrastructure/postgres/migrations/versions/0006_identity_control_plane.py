"""Add identity independently of retained bookkeeping and authority records."""

from pathlib import Path
from alembic import op

revision = '0006_identity_control_plane'
down_revision = '0005_bookkeeping_cutover'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_bind().connection.driver_connection.cursor() as cursor:
        cursor.execute(Path(__file__).with_suffix('.sql').read_text(encoding='utf-8'), prepare=False)


def downgrade():
    raise ValueError('Identity migrations are forward-only; use a verified recovery procedure.')
