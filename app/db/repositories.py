"""
app/db/repositories.py

Repository helpers for DB operations used by endpoints and background tasks.

Provides:
- recipient bulk insert helpers (existing)
- campaign helper functions (created here)
"""
from typing import List, Dict, Tuple, Set, Iterable
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import func

from .models import Recipient, Campaign, DeliveryLog, SubscriptionStatus, CampaignStatus, DeliveryStatus
from .session import SessionLocal

logger = logging.getLogger(__name__)


# --------------------
# Recipient utilities
# --------------------
def get_existing_recipient_emails(session, emails: Set[str]) -> Set[str]:
    """
    Return set of emails already present in DB from the provided set.
    """
    if not emails:
        return set()
    rows = session.query(Recipient.email).filter(Recipient.email.in_(list(emails))).all()
    return {r[0] for r in rows}


def bulk_insert_recipients(session, rows: List[Dict]) -> Tuple[int, int]:
    """
    Bulk-insert recipient dicts into the recipients table.

    rows: list of dicts with keys 'email', optional 'name', optional 'subscription_status'.
    Returns: (inserted_count, duplicates_count)

    Strategy:
      - Deduplicate by email in the provided rows (last occurrence wins for name).
      - Use SQLite INSERT OR IGNORE to avoid IntegrityError on concurrent inserts.
      - Count existing emails before insert to compute duplicates count.
    """
    if not rows:
        return 0, 0

    # Deduplicate incoming list by email (keep last)
    dedup_map: Dict[str, Dict] = {}
    for r in rows:
        dedup_map[r["email"]] = {
            "email": r["email"],
            "name": r.get("name"),
            "subscription_status": r.get("subscription_status", "subscribed"),
        }

    unique_emails = set(dedup_map.keys())

    # Check existing emails in DB
    existing = get_existing_recipient_emails(session, unique_emails)
    duplicates_count = len(existing)

    # Prepare list to insert (exclude existing)
    to_insert = [
        {"email": dedup_map[email]["email"], "name": dedup_map[email]["name"],
         "subscription_status": dedup_map[email]["subscription_status"]}
        for email in unique_emails if email not in existing
    ]

    if not to_insert:
        return 0, duplicates_count

    try:
        stmt = sqlite_insert(Recipient.__table__).prefix_with("OR IGNORE")
        session.execute(stmt, to_insert)
        session.commit()
    except IntegrityError as ie:
        logger.exception("IntegrityError during bulk insert: %s", ie)
        session.rollback()
        # Fallback: per-row insert to maximize successful inserts and count duplicates
        inserted = 0
        for r in to_insert:
            try:
                obj = Recipient(email=r["email"], name=r.get("name"),
                                subscription_status=r.get("subscription_status", "subscribed"))
                session.add(obj)
                session.commit()
                inserted += 1
            except IntegrityError:
                session.rollback()
                duplicates_count += 1
            except Exception as exc:
                session.rollback()
                logger.exception("Failed inserting recipient %s: %s", r.get("email"), exc)
        return inserted, duplicates_count
    except Exception as exc:
        session.rollback()
        logger.exception("Unexpected error during bulk insert: %s", exc)
        raise

    # Estimate inserted count as number of attempted inserts (len(to_insert)).
    # If some were ignored due to race with other processes, they are effectively duplicates.
    inserted_count = len(to_insert)
    return inserted_count, duplicates_count


# --------------------
# Campaign utilities
# --------------------
def create_campaign(session, name: str, subject: str, content: str, scheduled_at=None) -> Campaign:
    """
    Create a new campaign and return the instance.
    """
    c = Campaign(name=name, subject=subject, content=content, scheduled_at=scheduled_at)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def get_campaign(session, campaign_id: int) -> Campaign:
    return session.query(Campaign).filter(Campaign.id == campaign_id).one_or_none()


def update_campaign_status(session, campaign: Campaign, status: CampaignStatus):
    campaign.status = status
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def set_campaign_total_recipients(session, campaign: Campaign, total: int):
    campaign.total_recipients = total
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def count_subscribed_recipients(session) -> int:
    return session.query(func.count(Recipient.id)).filter(Recipient.subscription_status == SubscriptionStatus.SUBSCRIBED).scalar() or 0


def get_delivery_counts(session, campaign_id: int) -> Tuple[int, int]:
    """
    Return (sent_count, failed_count) for the campaign.
    """
    sent = session.query(func.count(DeliveryLog.id)).filter(
        DeliveryLog.campaign_id == campaign_id, DeliveryLog.status == DeliveryStatus.SENT
    ).scalar() or 0
    failed = session.query(func.count(DeliveryLog.id)).filter(
        DeliveryLog.campaign_id == campaign_id, DeliveryLog.status == DeliveryStatus.FAILED
    ).scalar() or 0
    return int(sent), int(failed)


def list_campaigns_with_dashboard(session):
    """
    Compact listing that returns dicts matching CampaignDashboardItem:
    {
      id, name, subject, status, created_at, scheduled_at,
      total_recipients, sent_count, failed_count, summary
    }
    """
    from sqlalchemy import func, case
    from app.db.models import Campaign, DeliveryLog

    # aggregate delivery counts per campaign in a single query
    q = (
        session.query(
            Campaign.id,
            Campaign.name,
            Campaign.subject,
            Campaign.status,
            Campaign.created_at,
            Campaign.scheduled_at,
            Campaign.total_recipients.label("total_recipients"),
            func.coalesce(func.sum(case((DeliveryLog.status == DeliveryStatus.SENT, 1), else_=0)), 0).label("sent_count"),
            func.coalesce(func.sum(case((DeliveryLog.status == DeliveryStatus.FAILED, 1), else_=0)), 0).label("failed_count"),
            func.count(DeliveryLog.id).label("attempts"),
        )
        .outerjoin(DeliveryLog, DeliveryLog.campaign_id == Campaign.id)
        .group_by(
            Campaign.id,
            Campaign.name,
            Campaign.subject,
            Campaign.status,
            Campaign.created_at,
            Campaign.scheduled_at,
            Campaign.total_recipients,
        )
        .order_by(Campaign.created_at.desc())
    )

    out = []
    for row in q:
        total = int(row.total_recipients or 0)
        sent = int(row.sent_count or 0)
        failed = int(row.failed_count or 0)
        attempts = int(row.attempts or 0)
        summary = f"{sent}/{total} sent" if total else (f"{sent}/{attempts} sent" if attempts else f"{sent}/0 sent")

        out.append({
            "id": row.id,
            "name": row.name or "",
            "subject": row.subject or "",
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "created_at": row.created_at,
            "scheduled_at": row.scheduled_at,
            "total_recipients": total,
            "sent_count": sent,
            "failed_count": failed,
            "summary": summary,
        })
    return out