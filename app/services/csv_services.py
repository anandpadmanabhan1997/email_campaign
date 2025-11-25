"""
app/services/csv_services.py

"""

from typing import Dict, Any, List
from io import IOBase
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.db.models import Recipient
from app.utils.validators import normalize_email, validate_subscription_status 

import csv
import time

CHUNK_SIZE = 500
MAX_RETRIES = 3


CHUNK_SIZE = 500
MAX_RETRIES = 3

def process_recipient_csv(file_like: IOBase, update_on_duplicate: bool = False) -> Dict[str, Any]:
    reader = csv.DictReader(file_like)
    inserted, updated, duplicates, invalid = 0, 0, 0, 0
    errors: List[str] = []
    actions: List[Dict[str, Any]] = []

    db: Session = SessionLocal()
    new_recipients: List[Dict[str, Any]] = []

    try:
        for row_num, row in enumerate(reader, start=1):
            raw_email = (row.get("email") or "").strip()
            if not raw_email:
                invalid += 1
                errors.append(f"missing email (row {row_num})")
                actions.append({"row": row_num, "email": "", "action": "invalid"})
                continue

            norm = normalize_email(raw_email)
            if not norm:
                invalid += 1
                errors.append(f"invalid email '{raw_email}' (row {row_num})")
                actions.append({"row": row_num, "email": raw_email, "action": "invalid"})
                continue

            raw_status = (row.get("subscription_status") or "").strip()
            try:
                status_intent = validate_subscription_status(raw_status) if raw_status else None
            except ValueError as ve:
                invalid += 1
                errors.append(f"{ve} (row {row_num})")
                actions.append({"row": row_num, "email": norm, "action": "invalid"})
                continue

            name = (row.get("name") or "").strip() or None
            insert_status = status_intent if status_intent else "subscribed"

            existing = db.query(Recipient).filter(Recipient.email == norm).one_or_none()
            if existing:
                if update_on_duplicate:
                    changed = False
                    if status_intent and existing.subscription_status != status_intent:
                        existing.subscription_status = status_intent
                        changed = True
                    if name and existing.name != name:
                        existing.name = name
                        changed = True
                    if changed:
                        updated += 1
                        actions.append({"row": row_num, "email": norm, "action": "updated"})
                    else:
                        duplicates += 1
                        actions.append({"row": row_num, "email": norm, "action": "skipped"})
                else:
                    duplicates += 1
                    actions.append({"row": row_num, "email": norm, "action": "skipped"})
                continue

            new_recipients.append(
                {"email": norm, "name": name, "subscription_status": insert_status}
            )
            inserted += 1
            actions.append({"row": row_num, "email": norm, "action": "inserted"})

            if len(new_recipients) >= CHUNK_SIZE:
                _commit_with_retry(db, new_recipients)
                new_recipients.clear()

        if new_recipients:
            _commit_with_retry(db, new_recipients)

    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", flush=True)
        db.rollback()
        errors.append(f"unexpected error: {exc}")
        raise
    finally:
        db.close()

    return {
        "inserted": inserted,
        "updated": updated,
        "duplicates": duplicates,
        "invalid": invalid,
        "errors": errors,
        "actions": actions,
    }


def _commit_with_retry(db: Session, records: List[Dict[str, Any]], retries: int = MAX_RETRIES):
    for attempt in range(retries):
        try:
            db.bulk_insert_mappings(Recipient, records)
            db.commit()
            return
        except OperationalError as e:
            db.rollback()
            if "database is locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except IntegrityError:
            db.rollback()
            return
