from datetime import timezone, datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import Campaign
from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)

def mark_campaign_and_enqueue(db: Session, campaign_id: int) -> bool:
    """
    Atomically mark campaign.status from 'scheduled' -> 'queued' and enqueue send_campaign.
    Returns True if this call changed the status and enqueued; False if another process already did it.
    Must be called inside a DB transaction or will open a short transaction here.
    """
    logger.info("Enqueued mark_campaign_and_enqueue")

    # Try to atomically update status; only succeed if current status is 'scheduled'
    from app.tasks.emailer import send_campaign  # lazy import
    stmt = (
        update(Campaign)
        .where(Campaign.id == campaign_id, Campaign.status == "scheduled")
        .values(status="in_progress", queued_at=datetime.now(timezone.utc))        
        .execution_options(synchronize_session="fetch")
    )
    res = db.execute(stmt)
    if res.rowcount == 0:
        # someone else already picked this campaign
        db.commit()
        return False

    # commit the status change before sending the task so worker can read DB reliably
    db.commit()

    # enqueue the send_campaign task (producer)
    send_campaign.apply_async(args=[campaign_id], queue="control")
    return True