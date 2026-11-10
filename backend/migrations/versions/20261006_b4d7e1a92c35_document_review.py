"""document review: every new document waits for an owner or editor to approve it

Revision ID: b4d7e1a92c35
Revises: 87894e201f49
Create Date: 2026-10-06 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'b4d7e1a92c35'
down_revision = '87894e201f49'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Documents that already answer questions stay approved; the default is dropped
    # afterwards so new rows take the application's ``pending``.
    op.add_column('knowledge_documents', sa.Column('review_status', sa.String(length=16), server_default='approved', nullable=False))
    op.alter_column('knowledge_documents', 'review_status', server_default=None)
    op.add_column('knowledge_documents', sa.Column('reviewed_by', sa.String(length=255), nullable=True))
    op.add_column('knowledge_documents', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('knowledge_documents', sa.Column('review_note', sa.Text(), nullable=True))
    op.create_index('ix_knowledge_documents_review_status', 'knowledge_documents', ['review_status'])


def downgrade() -> None:
    op.drop_index('ix_knowledge_documents_review_status', table_name='knowledge_documents')
    op.drop_column('knowledge_documents', 'review_note')
    op.drop_column('knowledge_documents', 'reviewed_at')
    op.drop_column('knowledge_documents', 'reviewed_by')
    op.drop_column('knowledge_documents', 'review_status')
