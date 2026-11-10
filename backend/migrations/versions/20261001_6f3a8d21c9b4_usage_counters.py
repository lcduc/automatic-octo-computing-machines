"""durable usage counters, model prices, cost and tier per LLM call

Revision ID: 6f3a8d21c9b4
Revises: 2c7e19a4b6d3
Create Date: 2026-10-01 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '6f3a8d21c9b4'
down_revision = '2c7e19a4b6d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'usage_counters',
        sa.Column('scope_key', sa.String(length=160), nullable=False),
        sa.Column('window', sa.String(length=8), nullable=False),
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requests', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('tokens', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('cost_micro_usd', sa.BigInteger(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('scope_key', 'window', 'bucket_start', name=op.f('pk_usage_counters')),
    )
    op.create_index('ix_usage_counters_bucket_start', 'usage_counters', ['bucket_start'])
    op.create_table(
        'model_prices',
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('input_usd_per_million', sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column('output_usd_per_million', sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('model', name=op.f('pk_model_prices')),
    )
    op.add_column('token_usage', sa.Column('cost_micro_usd', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('token_usage', sa.Column('tier', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('token_usage', 'tier')
    op.drop_column('token_usage', 'cost_micro_usd')
    op.drop_table('model_prices')
    op.drop_index('ix_usage_counters_bucket_start', table_name='usage_counters')
    op.drop_table('usage_counters')
