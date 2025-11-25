"""
app/db/models.py

SQLAlchemy models for recipients, campaigns and delivery logs.
"""
from datetime import datetime
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    Index,
    func,UniqueConstraint
)
from sqlalchemy.orm import relationship

from .session import Base  # import Base from session (same package)


class SubscriptionStatus(str, enum.Enum):
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
  

class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), nullable=False, unique=True, index=True)  # normalized email unique
    name = Column(String(255), nullable=True)
    subscription_status = Column(String(32), nullable=False, default="subscribed")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    delivery_logs = relationship("DeliveryLog", back_populates="recipient", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Recipient id={self.id} email={self.email} status={self.subscription_status}>"
    def as_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "subscription_status": self.subscription_status,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("name", "scheduled_at", name="uq_campaign_name_scheduled_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=255), nullable=False)
    subject = Column(String(length=512), nullable=False)
    content = Column(Text, nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT, index=True)
    total_recipients = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    queued_at = Column(DateTime(timezone=True))  # ← add this

    delivery_logs = relationship("DeliveryLog", back_populates="campaign", cascade="all, delete-orphan")


    def as_dict(self):
        def _fmt(dt):
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "scheduled_at": _fmt(self.scheduled_at),
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(getattr(self, "updated_at", None)),
        }

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name} status={self.status} total={self.total_recipients}>"


class DeliveryLog(Base):
    __tablename__ = "delivery_logs"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False)
    recipient_id = Column(Integer, ForeignKey("recipients.id", ondelete="SET NULL"), index=True, nullable=True)

    recipient_email = Column(String(length=320), nullable=False, index=True)

    status = Column(Enum(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING, index=True)
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    message_id = Column(String(length=512), nullable=True, index=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    campaign = relationship("Campaign", back_populates="delivery_logs")
    recipient = relationship("Recipient", back_populates="delivery_logs")

    def mark_sent(self, message_id: str = None):
        self.status = DeliveryStatus.SENT
        self.attempts = (self.attempts or 0) + 1
        if message_id:
            self.message_id = message_id
        self.last_attempt_at = datetime.utcnow()

    def mark_failed(self, error: str = None):
        self.status = DeliveryStatus.FAILED
        self.attempts = (self.attempts or 0) + 1
        if error:
            self.error = str(error)
        self.last_attempt_at = datetime.utcnow()

    def __repr__(self) -> str:
        return f"<DeliveryLog id={self.id} campaign={self.campaign_id} to={self.recipient_email} status={self.status}>"


# Index hints
Index("ix_campaign_status_scheduled", Campaign.status, Campaign.scheduled_at)
Index("ix_recipient_email_unique", Recipient.email)
Index("ix_delivery_campaign_status", DeliveryLog.campaign_id, DeliveryLog.status)