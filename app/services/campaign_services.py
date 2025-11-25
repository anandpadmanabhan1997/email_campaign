from datetime import timezone, datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Campaign
from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)
from app.tasks.emailer import send_campaign 

def mark_campaign_and_enqueue(db: Session, campaign_id: int) -> bool:
    """
    Mark campaign status from 'scheduled' -> 'queued' and enqueue send_campaign.
    """
    logger.info("Enqueued mark_campaign_and_enqueue")
    stmt = (
        update(Campaign)
        .where(Campaign.id == campaign_id, Campaign.status == "scheduled")
        .values(status="in_progress", queued_at=datetime.now(timezone.utc))        
        .execution_options(synchronize_session="fetch")
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        db.commit()
        return False
    db.commit()
    send_campaign.apply_async(args=[campaign_id], queue="control")
    return True