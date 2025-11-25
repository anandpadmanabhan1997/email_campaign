"""
Campaigns API (v1)

Endpoints:
- POST /campaigns             : create a new campaign 
- POST /campaigns/{id}/schedule : mark a campaign as scheduled 
- GET /campaigns              : list campaigns with dashboard info
- GET /campaigns/{id}         : get campaign details (basic fields)
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.db import repositories
from app.db.models import Campaign, CampaignStatus, DeliveryLog, DeliveryStatus
from app.tasks.celery_app import celery_app 
import calendar,logging
from app.schemas.schemas import DeliveryLogResponse
router = APIRouter()

logger = logging.getLogger(__name__)



def _ensure_aware_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

def _to_utc_timestamp(dt: datetime | None) -> float | None:
    """
    Return a POSIX timestamp (seconds since epoch, UTC) for dt.
    - If dt is None -> None
    - If dt is timezone-aware -> convert to UTC and return .timestamp()
    - If dt is naive -> treat as UTC and use calendar.timegm to avoid local-time assumptions
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
  
        return float(calendar.timegm(dt.utctimetuple()))
    return float(dt.astimezone(timezone.utc).timestamp())



@router.post(
    "/",
    response_model=schemas.CampaignResponse,
    summary="Create a campaign",
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(payload: schemas.CampaignCreate, db: Session = Depends(get_db)):
    """
    Create a campaign.
    Validation:
      - Reject creation if a campaign with the same name AND the same scheduled_at instant already exists.
        an existing campaign with scheduled_at IS NULL.
    """
    scheduled = payload.scheduled_at
    if scheduled is not None:
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        else:
            scheduled = scheduled.astimezone(timezone.utc)

    q = db.query(Campaign).filter(Campaign.name == payload.name)
    if scheduled is None:
        q = q.filter(Campaign.scheduled_at.is_(None))
    else:
        q = q.filter(Campaign.scheduled_at == scheduled)

    existing = q.one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A campaign with that name and scheduled time already exists.",
                "campaign_id": existing.id,
                "name": existing.name,
                "scheduled_at": existing.scheduled_at.isoformat() if existing.scheduled_at else None,
            },
        )

    c = repositories.create_campaign(
        db,
        name=payload.name,
        subject=payload.subject,
        content=payload.content,
        scheduled_at=scheduled,
    )
    return c



@router.post("/{campaign_id}/schedule", response_model=schemas.CampaignResponse)
def schedule_campaign(campaign_id: int, payload: schemas.CampaignScheduleRequest | None = None, db: Session = Depends(get_db)):
    """
    This endpoint will set the campaign status to 'scheduled'.
    """
    logger.info("Scheduling campaign %s", campaign_id)

    campaign = repositories.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    current_status = (campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status)).lower()
 
    if str(current_status).lower() != CampaignStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Campaign must be Draft to schedule (current: {campaign.status})")

    if payload and payload.scheduled_at is not None:
        campaign.scheduled_at = _ensure_aware_utc(payload.scheduled_at)
    else:
        if campaign.scheduled_at is None:
            campaign.scheduled_at = datetime.now(timezone.utc)  
        else:
            campaign.scheduled_at = _ensure_aware_utc(campaign.scheduled_at)

    total = repositories.count_subscribed_recipients(db)
    repositories.set_campaign_total_recipients(db, campaign, total)
    repositories.update_campaign_status(db, campaign, repositories.CampaignStatus.SCHEDULED)

    logger.info("Campaign %s scheduled for %s (total recipients: %s)", campaign_id, campaign.scheduled_at, total)
    db.refresh(campaign)
    return campaign



@router.post("/{campaign_id}/unschedule", response_model=schemas.CampaignResponse)
def unschedule_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """
    Unschedule a scheduled campaign (revert to Draft).
    Only allowed when campaign.status == 'scheduled'.
    """
    campaign = repositories.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    current_status = (campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status)).lower()
    if current_status != "scheduled":
        raise HTTPException(status_code=400, detail=f"Only Scheduled campaigns may be unscheduled (current: {campaign.status})")

    repositories.update_campaign_status(db, campaign, repositories.CampaignStatus.DRAFT if hasattr(repositories, 'CampaignStatus') else campaign.status.__class__('draft'))
    return campaign



@router.get("/", response_model=List[schemas.CampaignDashboardItem], summary="List campaigns for dashboard")
def list_campaigns(db: Session = Depends(get_db)):
    items = repositories.list_campaigns_with_dashboard(db)
    return [schemas.CampaignDashboardItem(**i) for i in items]


@router.get("/{campaign_id}", response_model=schemas.CampaignResponse, summary="Get campaign details")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = repositories.get_campaign(db, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c


@router.get("/{campaign_id}/deliveries", response_model=List[DeliveryLogResponse], summary="List delivery logs for a campaign")
def list_campaign_deliveries(campaign_id: int, db: Session = Depends(get_db)):
    campaign = repositories.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    logs = (
        db.query(DeliveryLog)
        .filter(DeliveryLog.campaign_id == campaign_id)
        .order_by(DeliveryLog.created_at.asc())
        .all()
    )
    return logs