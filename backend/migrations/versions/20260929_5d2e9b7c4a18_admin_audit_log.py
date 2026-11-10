"""append-only admin audit log

Revision ID: 5d2e9b7c4a18
Revises: c3f81a6d0e24
Create Date: 2026-09-29 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '5d2e9b7c4a18'
down_revision = 'c3f81a6d0e24'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=True),
        sa.Column('actor_role', sa.String(length=16), nullable=True),
        sa.Column('method', sa.String(length=8), nullable=False),
        sa.Column('path', sa.String(length=512), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('client_ip', sa.String(length=64), nullable=True),
        sa.Column('request_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_audit_log')),
    )
    op.create_index('ix_admin_audit_log_created_at', 'admin_audit_log', ['created_at'])
    op.create_index('ix_admin_audit_log_actor_email', 'admin_audit_log', ['actor_email'])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_no_change
        BEFORE UPDATE OR DELETE ON admin_audit_log
        FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutable()
        """
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS admin_audit_log_no_change ON admin_audit_log')
    op.execute('DROP FUNCTION IF EXISTS admin_audit_log_immutable()')
    op.drop_index('ix_admin_audit_log_actor_email', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_log_created_at', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
