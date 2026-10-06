"""Durable mileage insertion ordering for equal-date/equal-instant trip pairs."""

from alembic import op

revision = "0004_mileage_order"
down_revision = "0003_domain_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE mileage_records ADD COLUMN insertion_order bigint GENERATED ALWAYS AS IDENTITY")


def downgrade() -> None:
    op.execute("ALTER TABLE mileage_records DROP COLUMN insertion_order")
