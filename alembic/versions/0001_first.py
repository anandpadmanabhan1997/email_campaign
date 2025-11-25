"""initial

Revision ID: 0001_first
Revises: 
Create Date: 2025-11-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_first"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create recipients table
    op.create_table(
        "recipients",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("subscription_status", sa.String(length=50), nullable=False, server_default="subscribed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_recipient_email_unique", "recipients", ["email"], unique=True)

    # Create campaigns table
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),

    )
    op.create_index("ix_campaign_status_scheduled", "campaigns", ["status", "scheduled_at"])

    # Create delivery_logs table
    op.create_table(
        "delivery_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("recipients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_delivery_campaign_status", "delivery_logs", ["campaign_id", "status"])
    op.create_index("ix_delivery_recipient_email", "delivery_logs", ["recipient_email"])


def downgrade():
    op.drop_index("ix_delivery_recipient_email", table_name="delivery_logs")
    op.drop_index("ix_delivery_campaign_status", table_name="delivery_logs")
    op.drop_table("delivery_logs")

    op.drop_index("ix_campaign_status_scheduled", table_name="campaigns")
    op.drop_table("campaigns")

    op.drop_index("ix_recipient_email_unique", table_name="recipients")
    op.drop_table("recipients")