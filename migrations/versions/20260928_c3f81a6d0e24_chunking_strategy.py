"""chunking strategy, stored extracted text and edited-chunk flag

Revision ID: c3f81a6d0e24
Revises: a7e4c2d19b53
Create Date: 2026-09-28 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3f81a6d0e24'
down_revision = 'a7e4c2d19b53'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'knowledge_documents',
        sa.Column('chunking', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column('knowledge_documents', sa.Column('extracted_text', sa.Text(), nullable=True))
    op.add_column('knowledge_documents', sa.Column('extraction_method', sa.String(length=16), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('edited', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('knowledge_chunks', 'edited')
    op.drop_column('knowledge_documents', 'extraction_method')
    op.drop_column('knowledge_documents', 'extracted_text')
    op.drop_column('knowledge_documents', 'chunking')
