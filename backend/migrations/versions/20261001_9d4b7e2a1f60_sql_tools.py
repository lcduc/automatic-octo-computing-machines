"""SQL tool registry

Revision ID: 9d4b7e2a1f60
Revises: 6f3a8d21c9b4
Create Date: 2026-10-01 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '9d4b7e2a1f60'
down_revision = '6f3a8d21c9b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sql_tools',
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('args_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('required_tier', sa.String(length=16), nullable=False),
        sa.Column('sql_template', sa.Text(), nullable=False),
        sa.Column('allowed_columns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('masked_columns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('row_limit', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('name', name=op.f('pk_sql_tools')),
    )


def downgrade() -> None:
    op.drop_table('sql_tools')
