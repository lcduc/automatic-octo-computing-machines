"""host-site identity: conversation owner and token-visitor bindings

Revision ID: 8b41f2c6d7e5
Revises: 5d2e9b7c4a18
Create Date: 2026-09-30 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '8b41f2c6d7e5'
down_revision = '5d2e9b7c4a18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('user_id', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_conversations_user_id'), 'conversations', ['user_id'])
    op.create_table(
        'host_token_uses',
        sa.Column('jti', sa.String(length=128), nullable=False),
        sa.Column('visitor_id', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('jti', name=op.f('pk_host_token_uses')),
    )
    op.create_index(op.f('ix_host_token_uses_expires_at'), 'host_token_uses', ['expires_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_host_token_uses_expires_at'), table_name='host_token_uses')
    op.drop_table('host_token_uses')
    op.drop_index(op.f('ix_conversations_user_id'), table_name='conversations')
    op.drop_column('conversations', 'user_id')
