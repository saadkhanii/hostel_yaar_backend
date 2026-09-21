"""add booking_cancelled to notification_type enum

Revision ID: b89c97ee9048
Revises: 9552b220d3f4
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b89c97ee9048'
down_revision: Union[str, Sequence[str], None] = '9552b220d3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'booking_cancelled' to the notificationtype Postgres enum."""
    op.execute(
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'booking_cancelled'"
    )


def downgrade() -> None:
    """Postgres doesn't support removing enum values. Downgrade is a no-op."""
    pass