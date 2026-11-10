"""document lifecycle: access tier, language, version, effective dates, supersedes

Revision ID: 4e8c1b7d2a95
Revises: 9d4b7e2a1f60
Create Date: 2026-10-02 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '4e8c1b7d2a95'
down_revision = '9d4b7e2a1f60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('knowledge_documents', sa.Column('access_tier', sa.String(length=16), server_default='anonymous', nullable=False))
    op.add_column('knowledge_documents', sa.Column('language', sa.String(length=8), nullable=True))
    op.add_column('knowledge_documents', sa.Column('version', sa.String(length=32), nullable=True))
    op.add_column('knowledge_documents', sa.Column('effective_from', sa.Date(), nullable=True))
    op.add_column('knowledge_documents', sa.Column('effective_to', sa.Date(), nullable=True))
    op.add_column('knowledge_documents', sa.Column('supersedes_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_knowledge_documents_supersedes_id_knowledge_documents'), 'knowledge_documents',
        'knowledge_documents', ['supersedes_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_knowledge_documents_supersedes_id_knowledge_documents'), 'knowledge_documents', type_='foreignkey')
    for column in ('supersedes_id', 'effective_to', 'effective_from', 'version', 'language', 'access_tier'):
        op.drop_column('knowledge_documents', column)
