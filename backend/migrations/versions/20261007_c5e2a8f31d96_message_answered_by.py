"""staff replies record who wrote them

Revision ID: c5e2a8f31d96
Revises: b4d7e1a92c35
Create Date: 2026-10-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'c5e2a8f31d96'
down_revision = 'b4d7e1a92c35'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('answered_by', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'answered_by')
