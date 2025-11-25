"""
Single-file Pydantic schemas for the API (pydantic v2).
"""
from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# -------------------------
# Recipient schemas
# -------------------------
class RecipientCreate(BaseModel):
    name: Optional[str] = Field(None, description="Recipient full name")
    email: EmailStr = Field(..., description="Recipient email address")
    subscription_status: str = Field("subscribed", description="subscribed or unsubscribed")

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("subscription_status", mode="before")
    @classmethod
    def _normalize_status(cls, v):
        if v is None:
            return "subscribed"
        vs = str(v).strip().lower()
        if vs in ("subscribed", "sub"):
            return "subscribed"
        if vs in ("unsubscribed", "unsub"):
            return "unsubscribed"
        raise ValueError("subscription_status must be 'subscribed' or 'unsubscribed'")

    model_config = {"extra": "forbid"}


class RecipientResponse(BaseModel):
    id: int
    name: Optional[str]
    email: EmailStr
    subscription_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    inserted: int
    duplicates: int
    invalid: int
    errors: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# -------------------------
# Campaign schemas
# -------------------------
class CampaignCreate(BaseModel):
    name: str = Field(..., description="Campaign name (admin visible)")
    subject: str = Field(..., description="Email subject line")
    content: str = Field(..., description="Email content (plain text or HTML)")
    # Accept timezone-aware ISO strings (with offset or Z) parsed into datetime by Pydantic,
    # or naive datetimes which we'll treat as UTC on the server if needed.
    scheduled_at: Optional[datetime] = Field(None, description="Optional scheduled timestamp (ISO string or datetime)")

    model_config = {"extra": "forbid"}


class CampaignResponse(BaseModel):
    id: int
    name: str
    subject: str
    status: str
    total_recipients: int
    scheduled_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignDashboardItem(BaseModel):
    id: int
    name: str
    status: str
    subject: Optional[str] = ""
    total_recipients: int = 0
    sent_count: int = 0
    failed_count: int = 0
    summary: str
    created_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CampaignScheduleRequest(BaseModel):
    """
    Payload for scheduling a campaign (explicit Schedule action).
    Either scheduled_at (preferred; accepts ISO with offset or Z) or omitted to use stored scheduled_at.
    """
    scheduled_at: Optional[datetime] = Field(None, description="Optional scheduled timestamp to set when scheduling")

    model_config = {"extra": "forbid"}


# -------------------------
# Delivery schemas
# -------------------------
class DeliveryLogResponse(BaseModel):
    id: int
    campaign_id: int
    recipient_id: Optional[int]
    recipient_email: EmailStr
    status: str
    error: Optional[str]
    attempts: int
    message_id: Optional[str]
    last_attempt_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}