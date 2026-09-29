"""handoff requests become async tickets (contact, consent, answer, SLA, legal hold)

Revision ID: 7a2f9c3e5b18
Revises: 4e8c1b7d2a95
Create Date: 2026-10-02 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '7a2f9c3e5b18'
down_revision = '4e8c1b7d2a95'
branch_labels = None
depends_on = None

NEW_STATES = (("pending", "open"), ("in_progress", "assigned"), ("resolved", "closed"))


def upgrade() -> None:
    for name, column in (
        ('user_id', sa.String(length=128)), ('contact_name', sa.String(length=128)),
        ('contact_email', sa.String(length=255)), ('contact_phone', sa.String(length=32)),
        ('details', sa.Text()), ('consent_at', sa.DateTime(timezone=True)), ('assigned_to', sa.String(length=255)),
        ('answer', sa.Text()), ('answered_at', sa.DateTime(timezone=True)), ('emailed_at', sa.DateTime(timezone=True)),
        ('closed_at', sa.DateTime(timezone=True)), ('due_at', sa.DateTime(timezone=True)),
    ):
        op.add_column('handoff_requests', sa.Column(name, column, nullable=True))
    op.add_column('handoff_requests', sa.Column('legal_hold', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index(op.f('ix_handoff_requests_due_at'), 'handoff_requests', ['due_at'])
    for old, new in NEW_STATES:
        op.execute(sa.text("UPDATE handoff_requests SET status = :new WHERE status = :old").bindparams(old=old, new=new))
    op.execute("UPDATE handoff_requests SET closed_at = updated_at WHERE status = 'closed'")


def downgrade() -> None:
    op.execute("UPDATE handoff_requests SET status = 'resolved' WHERE status IN ('answered', 'closed')")
    op.execute("UPDATE handoff_requests SET status = 'in_progress' WHERE status = 'assigned'")
    op.execute("UPDATE handoff_requests SET status = 'pending' WHERE status = 'open'")
    op.drop_index(op.f('ix_handoff_requests_due_at'), table_name='handoff_requests')
    for name in ('legal_hold', 'due_at', 'closed_at', 'emailed_at', 'answered_at', 'answer', 'assigned_to',
                 'consent_at', 'details', 'contact_phone', 'contact_email', 'contact_name', 'user_id'):
        op.drop_column('handoff_requests', name)
