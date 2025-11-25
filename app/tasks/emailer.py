"""
Scalable campaign execution with chunked dispatch + monitor approach.

- send_campaign: orchestrator that chunks recipients and dispatches chunk groups.
- send_email: robust single-recipient sender with retries/backoff and DeliveryLog writes.
- monitor_campaign: polls DB until all delivery logs for campaign equal total_recipients, then calls finalize_campaign.
- finalize_campaign: aggregates counts, builds report, emails admin.

Config via ENV:
- RECIPIENT_CHUNK (default 200)
- SMTP_* (HOST, PORT, USER, PASS, USE_TLS)
- ADMIN_EMAIL
- SEND_RETRY_COUNT (default 3)
- SEND_RETRY_BACKOFF (seconds base, default 2)
"""
from __future__ import annotations

import os
import csv
import io
import smtplib
import time
import traceback
from datetime import datetime, timezone
from typing import List, Dict, Any

from celery import group
from celery.utils.log import get_task_logger

from .celery_app import celery_app

from app.db.session import SessionLocal
from app.db import repositories
from app.db.models import (
    Recipient,
    Campaign,
    DeliveryLog,
    DeliveryStatus,
    CampaignStatus,
)

logger = get_task_logger(__name__)

# Config
RECIPIENT_CHUNK = int(os.environ.get("RECIPIENT_CHUNK", "200"))
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
SEND_RETRY_COUNT = int(os.environ.get("SEND_RETRY_COUNT", "3"))
SEND_RETRY_BACKOFF = int(os.environ.get("SEND_RETRY_BACKOFF", "2"))  # base seconds



@celery_app.task(name="test.print")
def tprint():
    print("hello-from-task", flush=True)
    return "ok"




# Simple SMTP send with retry/backoff per task (keeps connection local to task)
def _send_smtp_message(msg):
    """
    Send an EmailMessage via SMTP with retry and exponential backoff.
    Returns None on success, or the last exception on failure after retries.
    """
    try:
        print("_make_email_message ", flush=True)

        last_exc = None
        for attempt in range(1, SEND_RETRY_COUNT + 1):
            try:
                if SMTP_USE_TLS:
                    # STARTTLS
                    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                        s.ehlo()
                        s.starttls()
                        s.ehlo()
                        if SMTP_USER:
                            s.login(SMTP_USER, SMTP_PASS)
                        s.send_message(msg)
                else:
                    # SSL
                    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                        if SMTP_USER:
                            s.login(SMTP_USER, SMTP_PASS)
                        s.send_message(msg)
                return None  # success
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "SMTP send attempt %s failed: %s (backoff=%ss)",
                    attempt,
                    exc,
                    SEND_RETRY_BACKOFF ** attempt,
                )
                if attempt < SEND_RETRY_COUNT:
                    time.sleep(SEND_RETRY_BACKOFF ** attempt)
        return last_exc  # after exhausting retries

    except Exception as exc:
        logger.exception("Failed to send SMTP message: %s", exc)
        print(f"Failed to send SMTP message: {exc}", flush=True)
        return exc

def _make_email_message(subject: str, content: str, to_email: str, from_email: str | None = None):
    try:
        from email.message import EmailMessage
        print("_make_email_message ", flush=True)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = to_email
        msg["From"] = from_email or (SMTP_USER or "no-reply@example.com")
        msg.set_content(content)
        return msg
    except Exception as exc:
        logger.exception("Failed to build email message to %s: %s", to_email, exc)
        print(f"Failed to build email message to {to_email}: {exc}", flush=True)
        raise


@celery_app.task(
    bind=True,
    name="tasks.emailer.send_email",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def send_email(self, campaign_id: int, recipient_id: int) -> Dict[str, Any]:
    """
    Send a single email and write DeliveryLog exactly once per (campaign_id, recipient_id).
    Assumes a unique constraint on DeliveryLog(campaign_id, recipient_id).
    """
    db = SessionLocal()
    try:
        print("Sending mail", flush=True)
        recipient = db.query(Recipient).filter(Recipient.id == recipient_id).one_or_none()
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).one_or_none()
        if not recipient or not campaign:
            return {
                "recipient_id": recipient_id,
                "email": None,
                "status": "failed",
                "error": "missing recipient or campaign",
            }

        # Idempotency: if a log exists, return its status
        existing = (
            db.query(DeliveryLog)
            .filter(
                DeliveryLog.campaign_id == campaign_id,
                DeliveryLog.recipient_id == recipient_id,
            )
            .one_or_none()
        )
        if existing:
            status_str = existing.status.name.lower() if hasattr(existing.status, "name") else str(existing.status)
            return {
                "recipient_id": recipient_id,
                "email": existing.recipient_email,
                "status": status_str,
                "error": existing.error,
            }

        # Build and send email
        msg = _make_email_message(campaign.subject or "No subject", campaign.content or "", recipient.email)
        smtp_exc = _send_smtp_message(msg)

        if smtp_exc is None:
            status = DeliveryStatus.SENT
            status_str = "sent"
            error = None
        else:
            status = DeliveryStatus.FAILED
            status_str = "failed"
            error = f"{type(smtp_exc).__name__}: {smtp_exc}"

        # Persist log once
        dl = DeliveryLog(
            campaign_id=campaign_id,
            recipient_id=recipient.id,
            recipient_email=recipient.email,
            status=status,
            error=error,
            attempts=1,
            message_id=None,
            last_attempt_at=datetime.now(timezone.utc),
        )
        db.add(dl)
        db.commit()

        return {"recipient_id": recipient.id, "email": recipient.email, "status": status_str, "error": error}

    except Exception as exc:
        db.rollback()
        logger.exception("send_email unexpected error for campaign %s recipient %s: %s", campaign_id, recipient_id, exc)
        # Let Celery autoretry handle reattempts. Avoid writing duplicate failed logs here.
        raise
    finally:
        db.close()



@celery_app.task(bind=True, name="tasks.emailer.finalize_campaign")
def finalize_campaign(self, campaign_id: int) -> Dict[str, Any]:
    """
    Aggregate delivery counts, set terminal status (COMPLETED or PARTIAL/FAILED),
    generate CSV report, and email to ADMIN_EMAIL.
    """
    db = SessionLocal()
    try:
        campaign = repositories.get_campaign(db, campaign_id)
        if not campaign:
            raise ValueError("campaign not found")

        sent, failed = repositories.get_delivery_counts(db, campaign_id)
        total = int(campaign.total_recipients or 0)

        # Terminal state decision
        try:
            if total == sent and failed == 0:
                repositories.update_campaign_status(db, campaign, CampaignStatus.COMPLETED)
            else:
                # choose a policy: PARTIAL if you have it; otherwise COMPLETED with failures noted
                if hasattr(CampaignStatus, "PARTIAL"):
                    repositories.update_campaign_status(db, campaign, CampaignStatus.PARTIAL)
                else:
                    repositories.update_campaign_status(db, campaign, CampaignStatus.COMPLETED)
        except Exception:
            # fallback string for robustness if Enum write fails
            campaign.status = "completed"
            db.add(campaign)
            db.commit()
            db.refresh(campaign)

        # Build CSV report in-memory
        rows = db.query(DeliveryLog).filter(DeliveryLog.campaign_id == campaign_id).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["recipient_id", "recipient_email", "status", "error"])
        for r in rows:
            st = r.status.name.lower() if hasattr(r.status, "name") else str(r.status)
            writer.writerow([r.recipient_id, r.recipient_email, st, r.error or ""])
        csv_content = output.getvalue()
        output.close()

        # Email report to admin
        if ADMIN_EMAIL:
            from email.message import EmailMessage

            subject = f"Campaign {campaign_id} report - {datetime.now(timezone.utc).isoformat()}"
            body = f"Campaign {campaign_id} finalized. Sent: {sent}, Failed: {failed}, Total: {total}"
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SMTP_USER or "no-reply@example.com"
            msg["To"] = ADMIN_EMAIL
            msg.set_content(body)
            msg.add_attachment(
                csv_content,
                filename=f"campaign_{campaign_id}_report.csv",
                subtype="csv",
                maintype="text",
            )
            try:
                _send_smtp_message(msg)
            except Exception:
                logger.exception("Failed sending admin report for campaign %s", campaign_id)

        return {"campaign_id": campaign_id, "sent": sent, "failed": failed}

    finally:
        db.close()


@celery_app.task(bind=True, name="tasks.emailer.monitor_campaign")
def monitor_campaign(self, campaign_id: int, check_interval: int = 10, max_wait: int = 60 * 60 * 6) -> Dict[str, Any]:
    """
    Poll DB until the number of delivery logs equals total_recipients (or max_wait reached).
    When complete, call finalize_campaign.
    - check_interval: seconds between polls
    - max_wait: maximum seconds to wait before giving up (prevents runaway)
    """
    db = SessionLocal()
    try:
        logger.info("monitor_campaign START campaign_id=%s check_interval=%s max_wait=%s",
                campaign_id, check_interval, max_wait)
        start = time.time()
        logger.info("asdjbasdababbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        while True:
            
            c = repositories.get_campaign(db, campaign_id)
            print(c)
            if not c:
                raise ValueError("campaign not found")
            total = int(c.total_recipients or 0)
            sent, failed = repositories.get_delivery_counts(db, campaign_id)
            processed = sent + failed
            logger.info("monitor_campaign %s: processed=%s total=%s", campaign_id, processed, total)
            if total == 0:
                # no recipients, finalize immediately
                finalize_campaign.apply_async(args=[campaign_id])
                return {"campaign_id": campaign_id, "status": "no_recipients"}
            if processed >= total:
                # done
                finalize_campaign.apply_async(args=[campaign_id])
                return {"campaign_id": campaign_id, "status": "finalizing", "processed": processed}
            if time.time() - start > max_wait:
                logger.warning("monitor_campaign %s reached max_wait; processed %s of %s", campaign_id, processed, total)
                # decide: finalize anyway or requeue monitor; here we finalize to avoid indefinite waits
                finalize_campaign.apply_async(args=[campaign_id])
                return {"campaign_id": campaign_id, "status": "timeout", "processed": processed}
            # sleep before re-check
            time.sleep(check_interval)
    except Exception:
        logger.exception("monitor_campaign: unexpected error for campaign %s", campaign_id)
        raise
    
    finally:
        db.close()

@celery_app.task(bind=True, name="tasks.emailer.send_campaign")
def send_campaign(self, campaign_id: int) -> Dict[str, Any]:
    """
    Orchestrator:
    - Mark campaign IN_PROGRESS
    - Stream recipient IDs and dispatch send_email tasks in chunks
    - Update total_recipients on the campaign
    - Kick off monitor_campaign
    """
    db = SessionLocal()
    try:
        print("send_campaign triggered", flush=True)
        campaign = repositories.get_campaign(db, campaign_id)
        if not campaign:
            raise ValueError("campaign not found")

        # Mark in-progress with Enum (prefer) and fallback string as last resort
        try:
            repositories.update_campaign_status(db, campaign, CampaignStatus.IN_PROGRESS)
        except Exception:
            print("Failed to update campaign status via Enum, using string fallback", flush=True)
            campaign.status = "in_progress"
            db.add(campaign)
            db.commit()
            db.refresh(campaign)
        print("HERE", flush=True)

        # Stream recipients and dispatch in chunks (avoid loading all IDs into memory)
        q = (
            db.query(Recipient.id)
            .filter(Recipient.subscription_status == "subscribed")
            .yield_per(1000)
        )

        total_tasks = 0
        chunk_buffer = []

        for (rid,) in q:
            chunk_buffer.append(rid)
            if len(chunk_buffer) >= RECIPIENT_CHUNK:
                print("***************************************************", flush=True)
                print(campaign,chunk_buffer, flush=True)
                group(send_email.si(campaign_id, r).set(queue="send") for r in chunk_buffer).apply_async()
                total_tasks += len(chunk_buffer)
                chunk_buffer.clear()

        # Remaining recipients
        if chunk_buffer:
            print("********11111111111111*", flush=True)
            print(campaign,chunk_buffer, flush=True)

            group(send_email.si(campaign_id, r).set(queue="send") for r in chunk_buffer).apply_async()
            total_tasks += len(chunk_buffer)
            chunk_buffer.clear()

        # Update total_recipients to what we actually queued
        try:
            if hasattr(repositories, "update_campaign_total_recipients"):
                repositories.update_campaign_total_recipients(db, campaign, total_tasks)
            else:
                print("Failed to update total_recipients via repository, using direct assignment", flush=True)
                campaign.total_recipients = total_tasks
                db.add(campaign)
                db.commit()
                db.refresh(campaign)
        except Exception as exc:
            print("Failed to update total_recipients", flush=True)
            logger.warning("Failed to update total_recipients for campaign %s: %s", campaign_id, exc)

        # Start monitor shortly after dispatch
        monitor_campaign.apply_async(args=[campaign_id], countdown=5, queue="monitor")

        # If there was nothing to send, finalize immediately
        if total_tasks == 0:
            finalize_campaign.apply_async(args=[campaign_id], queue="monitor")
            return {"campaign_id": campaign_id, "queued": 0}

        return {"campaign_id": campaign_id, "queued": total_tasks}

    except Exception as exc:
        logger.exception("send_campaign error for %s: %s", campaign_id, exc)
        print (f"send_campaign error for {campaign_id}: {exc}", flush=True)
        # Mark campaign failed (prefer Enum)
        try:
            campaign = repositories.get_campaign(db, campaign_id)
            if campaign:
                repositories.update_campaign_status(db, campaign, CampaignStatus.FAILED)
        except Exception:
            # last-resort fallback
            if campaign:
                campaign.status = "failed"
                db.add(campaign)
                db.commit()
        raise
    finally:
        db.close()

   