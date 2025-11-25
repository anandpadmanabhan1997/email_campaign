"""
Campaigns API (v1)

Endpoints:
- POST /campaigns             : create a new campaign (prevents duplicate name+scheduled_at)
- POST /campaigns/{id}/schedule : mark a campaign as scheduled (and compute total recipients)
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
from app.db.models import Campaign, CampaignStatus
from app.tasks.celery_app import celery_app  # celery instance (tasks worker registers start_campaign)
import calendar,logging

router = APIRouter()

logger = logging.getLogger(__name__)

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
        For comparison the scheduled_at is normalized to UTC. If scheduled_at is omitted (None), we look for
        an existing campaign with scheduled_at IS NULL.
    """
    # Normalize scheduled_at to a UTC-aware datetime for stable comparison
    scheduled = payload.scheduled_at
    if scheduled is not None:
        if scheduled.tzinfo is None:
            # treat naive datetimes from client as UTC (change behaviour if you prefer native-local)
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        else:
            scheduled = scheduled.astimezone(timezone.utc)

    # Check for existing campaign with same name + scheduled_at (normalized)
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

    # No conflict -> create campaign via repository
    c = repositories.create_campaign(
        db,
        name=payload.name,
        subject=payload.subject,
        content=payload.content,
        scheduled_at=scheduled,
    )
    return c


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
        # treat naive datetimes as UTC (policy choice)
        # use utctimetuple + calendar.timegm to avoid system-local assumptions
        return float(calendar.timegm(dt.utctimetuple()))
    # aware: convert to UTC then return timestamp
    return float(dt.astimezone(timezone.utc).timestamp())



@router.post("/{campaign_id}/schedule", response_model=schemas.CampaignResponse)
def schedule_campaign(campaign_id: int, payload: schemas.CampaignScheduleRequest | None = None, db: Session = Depends(get_db)):
    """
    Schedule a campaign. Optional payload.scheduled_at will override stored scheduled_at.
    This endpoint will set the campaign status to 'scheduled' and will NOT start sending immediately.
    A separate background scheduler/worker should transition Scheduled -> In Progress when the time arrives.
    """
    def _ensure_aware_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    campaign = repositories.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    current_status = (campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status)).lower()
 
 
 
    if str(current_status).lower() != CampaignStatus.DRAFT:

        raise HTTPException(status_code=400, detail=f"Campaign must be Draft to schedule (current: {campaign.status})")

    # Apply override from payload if provided
    if payload and payload.scheduled_at is not None:
        campaign.scheduled_at = _ensure_aware_utc(payload.scheduled_at)
    else:
        # Keep stored scheduled_at if present; do not default to now to avoid accidental immediate start.
        if campaign.scheduled_at is None:
            # If you prefer to require a scheduled_at, raise 400 here instead of defaulting.
            # raise HTTPException(status_code=400, detail="No scheduled time provided")
            campaign.scheduled_at = datetime.now(timezone.utc)  # optional policy; still will remain 'scheduled'
        else:
            campaign.scheduled_at = _ensure_aware_utc(campaign.scheduled_at)

    # compute recipients snapshot and set total_recipients
    total = repositories.count_subscribed_recipients(db)
    repositories.set_campaign_total_recipients(db, campaign, total)

    # Set status to Scheduled (do not auto-start)
    try:
        repositories.update_campaign_status(db, campaign, repositories.CampaignStatus.SCHEDULED)
    except Exception:
        # fallback if enum not accessible: set string and persist
        campaign.status = "scheduled"
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

    logger.info("Campaign %s scheduled for %s (total recipients: %s)", campaign_id, campaign.scheduled_at, total)

    # Return fresh campaign
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

    # revert to draft and (optionally) clear total_recipients - here we keep a snapshot but set status back to draft
    repositories.update_campaign_status(db, campaign, repositories.CampaignStatus.DRAFT if hasattr(repositories, 'CampaignStatus') else campaign.status.__class__('draft'))
    # Optionally clear scheduled_at or total_recipients if you prefer:
    # campaign.scheduled_at = None
    # campaign.total_recipients = None
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign



@router.get("/", response_model=List[schemas.CampaignDashboardItem], summary="List campaigns with dashboard info")
def list_campaigns(db: Session = Depends(get_db)):
    items = repositories.list_campaigns_with_dashboard(db)
    # map dicts to Pydantic objects (CampaignDashboardItem)
    return [schemas.CampaignDashboardItem(**i) for i in items]


@router.get("/{campaign_id}", response_model=schemas.CampaignResponse, summary="Get campaign details")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = repositories.get_campaign(db, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c