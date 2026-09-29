"""privacy: legal hold on conversations, reviewed feedback, eval cases, audit purge (PRV-04, ADM-12)

Revision ID: 87894e201f49
Revises: 8d81aec5cb82
Create Date: 2026-10-04 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '87894e201f49'
down_revision = '8d81aec5cb82'
branch_labels = None
depends_on = None

# The audit trigger lets the retention purge delete entries older than a year; nothing else changes it.
AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger AS $$
BEGIN
    {purge}RAISE EXCEPTION 'admin_audit_log is append-only';
END;
$$ LANGUAGE plpgsql
"""
AUDIT_PURGE_CLAUSE = """IF TG_OP = 'DELETE' AND OLD.created_at < now() - interval '365 days' THEN
        RETURN OLD;
    END IF;
    """


def upgrade() -> None:
    op.create_table('eval_cases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected_answer', sa.Text(), nullable=False),
    sa.Column('expected_sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('document_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_eval_cases'))
    )
    op.add_column('conversations', sa.Column('legal_hold', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('feedback', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('feedback', sa.Column('reviewed_by', sa.String(length=255), nullable=True))
    op.execute(AUDIT_FUNCTION.format(purge=AUDIT_PURGE_CLAUSE))


def downgrade() -> None:
    op.execute(AUDIT_FUNCTION.format(purge=""))
    op.drop_column('feedback', 'reviewed_by')
    op.drop_column('feedback', 'reviewed_at')
    op.drop_column('conversations', 'legal_hold')
    op.drop_table('eval_cases')
