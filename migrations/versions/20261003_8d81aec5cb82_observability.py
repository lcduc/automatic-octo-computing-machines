"""message traces, daily metrics and alert state (ADM-05, OBS-03, OBS-04)

Revision ID: 8d81aec5cb82
Revises: 7a2f9c3e5b18
Create Date: 2026-10-03 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '8d81aec5cb82'
down_revision = '7a2f9c3e5b18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('alert_states',
    sa.Column('rule', sa.String(length=64), nullable=False),
    sa.Column('firing', sa.Boolean(), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cursor', sa.String(length=64), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('rule', name=op.f('pk_alert_states'))
    )
    op.create_table('metrics_daily',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('turns', sa.Integer(), nullable=False),
    sa.Column('conversations', sa.Integer(), nullable=False),
    sa.Column('errors', sa.Integer(), nullable=False),
    sa.Column('handoffs', sa.Integer(), nullable=False),
    sa.Column('p50_latency_ms', sa.Float(), nullable=True),
    sa.Column('p95_latency_ms', sa.Float(), nullable=True),
    sa.Column('p95_first_token_ms', sa.Float(), nullable=True),
    sa.Column('prompt_tokens', sa.BigInteger(), nullable=False),
    sa.Column('completion_tokens', sa.BigInteger(), nullable=False),
    sa.Column('cost_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('day', name=op.f('pk_metrics_daily'))
    )
    op.create_table('message_traces',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('route', sa.String(length=32), nullable=True),
    sa.Column('intent', sa.String(length=32), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('rewritten_query', sa.Text(), nullable=True),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('chunks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('prompt_version', sa.String(length=32), nullable=True),
    sa.Column('steps_ms', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_message_traces_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_traces_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', name=op.f('pk_message_traces'))
    )
    op.create_index(op.f('ix_message_traces_conversation_id'), 'message_traces', ['conversation_id'], unique=False)
    op.create_index('ix_message_traces_created_at', 'message_traces', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_message_traces_created_at', table_name='message_traces')
    op.drop_index(op.f('ix_message_traces_conversation_id'), table_name='message_traces')
    op.drop_table('message_traces')
    op.drop_table('metrics_daily')
    op.drop_table('alert_states')
