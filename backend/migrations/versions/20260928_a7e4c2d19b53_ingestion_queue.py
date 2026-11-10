"""ingestion queue columns on knowledge_documents

Revision ID: a7e4c2d19b53
Revises: 3b5c8693432c
Create Date: 2026-09-28 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'a7e4c2d19b53'
down_revision = '3b5c8693432c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('knowledge_documents', sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('knowledge_documents', sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('knowledge_documents', sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('knowledge_documents', 'processed_at')
    op.drop_column('knowledge_documents', 'claimed_at')
    op.drop_column('knowledge_documents', 'attempts')
