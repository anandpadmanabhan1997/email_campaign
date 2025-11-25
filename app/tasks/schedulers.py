
from datetime import datetime, timezone
from typing import List

from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)

from app.services.campaign_services import mark_campaign_and_enqueue
from app.db.models import Campaign
from app.db import SessionLocal
from app.tasks.celery_app import celery_app



@celery_app.task(name="app.tasks.schedulers.enqueue_due_campaigns")
def enqueue_due_campaigns() -> int:
    """
    Run every minute via Celery Beat. Find campaigns with scheduled_at <= now and status == 'scheduled'
    and enqueue send_campaign.
    """
    try:
        now = datetime.now(timezone.utc)
        db = SessionLocal()
        logger.warning("enqueue_due_campaigns triggered (test)") 
        print("HEre",flush=True)
        candidates: List[Campaign] = (
            db.query(Campaign)
            .filter(Campaign.scheduled_at <= now, Campaign.status == "scheduled")
            .order_by(Campaign.scheduled_at)
            .with_for_update(skip_locked=True)
            .limit(100)
            .all()
                )

        logger.info("enqueue_due_campaigns: found %s candidate(s)", len(candidates))
        count = 0
        for c in candidates:
            logger.info("Candidate campaign_id=%s scheduled_at=%s status=%s", c.id, c.scheduled_at, c.status)
    
            if mark_campaign_and_enqueue(db, c.id):
                count += 1
                logger.info("Enqueued campaign_id=%s successfully", c.id)
            else:
                logger.warning("Failed to enqueue campaign_id=%s", c.id)

        logger.info("enqueue_due_campaigns: total enqueued=%s", count)
        return count

    except Exception as e:
        logger.error("Error in enqueue_due_campaigns: %s", str(e))
        raise

    finally:
        db.close()