"""
app/services/csv_services.py

CSV processing for recipient uploads with explicit per-row actions.

Returns:
  {
    inserted, updated, duplicates, invalid, errors,
    duplicates_list, updated_list, invalid_list,
    actions: [ { row: int, email: str, action: "inserted"|"updated"|"skipped"|"invalid", reason?: str } ... ]
  }
"""
from typing import Any, Dict, List, IO
import csv
from io import StringIO

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.db.models import Recipient

# Try strict validators if present
try:
    from app.utils.validators import normalize_email, validate_subscription_status
except Exception:
    import re
    EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

    def normalize_email(email: str) -> str | None:
        if not isinstance(email, str):
            return None
        e = email.strip().lower()
        if not EMAIL_RE.match(e):
            return None
        return e

    def validate_subscription_status(value: str | None) -> str:
        raw = (value or "").strip().lower()
        if raw == "":
            # Caller treats empty as "no change" for updates / default for inserts
            raise ValueError("empty")
        if raw in ("subscribed", "subscribe", "yes", "true"):
            return "subscribed"
        if raw in ("unsubscribed", "unsubscribe", "no", "false"):
            return "unsubscribed"
        raise ValueError(f"invalid subscription_status '{value}'")


def process_recipient_csv(file_like: IO[str], update_on_duplicate: bool = False) -> Dict[str, Any]:
    reader = csv.DictReader(file_like)
    inserted = 0
    updated = 0
    duplicates = 0   # only skipped duplicates
    invalid = 0
    errors: List[str] = []
    duplicate_emails: List[str] = []   # skipped duplicates
    updated_emails: List[str] = []
    invalid_emails: List[str] = []
    actions: List[Dict[str, Any]] = []

    db: Session = SessionLocal()
    try:
        for row_num, row in enumerate(reader, start=1):
            raw_email = (row.get("email") or "").strip()
            if not raw_email:
                invalid += 1
                invalid_emails.append("")
                msg = f"missing email (row {row_num})"
                errors.append(msg)
                actions.append({"row": row_num, "email": "", "action": "invalid", "reason": msg})
                continue

            norm = normalize_email(raw_email)
            if not norm:
                invalid += 1
                invalid_emails.append(raw_email)
                msg = f"invalid email '{raw_email}' (row {row_num})"
                errors.append(msg)
                actions.append({"row": row_num, "email": raw_email, "action": "invalid", "reason": msg})
                continue

            # Determine subscription_status intent
            raw_status_cell = row.get("subscription_status")
            status_intent = None
            if raw_status_cell is not None:
                raw_status_str = (raw_status_cell or "").strip()
                if raw_status_str != "":
                    try:
                        status_intent = validate_subscription_status(raw_status_str)
                    except ValueError as ve:
                        # Non-empty invalid status -> treat row as invalid
                        invalid += 1
                        invalid_emails.append(norm)
                        msg = f"{ve} (row {row_num})"
                        errors.append(msg)
                        actions.append({"row": row_num, "email": norm, "action": "invalid", "reason": str(ve)})
                        continue
                else:
                    status_intent = None
            else:
                status_intent = None

            name = (row.get("name") or "").strip() or None

            # Check for existing recipient
            existing = db.query(Recipient).filter(Recipient.email == norm).one_or_none()
            if existing:
                if update_on_duplicate:
                    changed = False
                    # Only apply status change when CSV provided a non-empty valid status
                    if status_intent is not None and existing.subscription_status != status_intent:
                        existing.subscription_status = status_intent
                        changed = True
                    if name and existing.name != name:
                        existing.name = name
                        changed = True
                    if changed:
                        updated += 1
                        updated_emails.append(norm)
                        actions.append({"row": row_num, "email": norm, "action": "updated"})
                    else:
                        duplicates += 1
                        duplicate_emails.append(norm)
                        actions.append({"row": row_num, "email": norm, "action": "skipped", "reason": "no changes"})
                else:
                    duplicates += 1
                    duplicate_emails.append(norm)
                    actions.append({"row": row_num, "email": norm, "action": "skipped", "reason": "duplicate"})
                continue

            # Insert new recipient (default status = subscribed when status_intent None)
            insert_status = status_intent if status_intent is not None else "subscribed"
            try:
                new_r = Recipient(email=norm, name=name, subscription_status=insert_status)
                db.add(new_r)
                db.flush()
                inserted += 1
                actions.append({"row": row_num, "email": norm, "action": "inserted"})
            except IntegrityError:
                db.rollback()
                # Concurrent insert -> reload existing and decide
                existing = db.query(Recipient).filter(Recipient.email == norm).one_or_none()
                if existing:
                    if update_on_duplicate:
                        changed = False
                        if status_intent is not None and existing.subscription_status != status_intent:
                            existing.subscription_status = status_intent
                            changed = True
                        if name and existing.name != name:
                            existing.name = name
                            changed = True
                        if changed:
                            updated += 1
                            updated_emails.append(norm)
                            actions.append({"row": row_num, "email": norm, "action": "updated"})
                        else:
                            duplicates += 1
                            duplicate_emails.append(norm)
                            actions.append({"row": row_num, "email": norm, "action": "skipped", "reason": "concurrent duplicate"})
                    else:
                        duplicates += 1
                        duplicate_emails.append(norm)
                        actions.append({"row": row_num, "email": norm, "action": "skipped", "reason": "concurrent duplicate"})
                else:
                    duplicates += 1
                    duplicate_emails.append(norm)
                    actions.append({"row": row_num, "email": norm, "action": "skipped", "reason": "unknown"})
                continue

        db.commit()
    except Exception as exc:
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
        "duplicates_list": duplicate_emails,
        "updated_list": updated_emails,
        "invalid_list": invalid_emails,
        "actions": actions,
    }