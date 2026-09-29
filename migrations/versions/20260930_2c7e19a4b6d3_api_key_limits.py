"""server-to-server API keys: expiry, per-key rate limit, rotation link

Revision ID: 2c7e19a4b6d3
Revises: 8b41f2c6d7e5
Create Date: 2026-09-30 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '2c7e19a4b6d3'
down_revision = '8b41f2c6d7e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('api_keys', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('api_keys', sa.Column('rate_limit_per_minute', sa.Integer(), server_default='60', nullable=False))
    op.add_column('api_keys', sa.Column('rotated_from_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_api_keys_rotated_from_id_api_keys'), 'api_keys', 'api_keys', ['rotated_from_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_api_keys_rotated_from_id_api_keys'), 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'rotated_from_id')
    op.drop_column('api_keys', 'rate_limit_per_minute')
    op.drop_column('api_keys', 'expires_at')
