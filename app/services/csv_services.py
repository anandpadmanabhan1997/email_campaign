"""
app/services/csv_services.py

CSV processing using pure sqlite3 (no SQLAlchemy for inserts).
"""
import csv
import sqlite3
import time
from io import IOBase
from typing import Dict, Any, List
from app.core.config import get_settings

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
            raise ValueError("empty")
        if raw in ("subscribed", "subscribe", "yes", "true"):
            return "subscribed"
        if raw in ("unsubscribed", "unsubscribe", "no", "false"):
            return "unsubscribed"
        raise ValueError(f"invalid subscription_status '{value}'")


CHUNK_SIZE = 100
MAX_RETRIES = 3


def process_recipient_csv(file_like: IOBase, update_on_duplicate: bool = False) -> Dict[str, Any]:
    """
    Process CSV file using pure sqlite3 (no SQLAlchemy).
    """
    reader = csv.DictReader(file_like)

    inserted, updated, duplicates, invalid = 0, 0, 0, 0
    errors: List[str] = []
    actions: List[Dict[str, Any]] = []

    settings = get_settings()
    db_url = settings.DATABASE_URL

    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
    elif db_url.startswith("sqlite://"):
        db_path = db_url.replace("sqlite://", "")
    else:
        db_path = db_url

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.isolation_level = None  # autocommit mode
    cursor = conn.cursor()

    new_recipients = []

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

            new_recipients.append((norm, name, insert_status, row_num))

            # Process in chunks
            if len(new_recipients) >= CHUNK_SIZE:
                inserted_count, updated_count, dup_count, batch_actions, batch_errors = (
                    _process_batch(cursor, new_recipients, update_on_duplicate)
                )
                inserted += inserted_count
                updated += updated_count
                duplicates += dup_count
                actions.extend(batch_actions)
                errors.extend(batch_errors)
                new_recipients.clear()

        # Process remaining records
        if new_recipients:
            inserted_count, updated_count, dup_count, batch_actions, batch_errors = (
                _process_batch(cursor, new_recipients, update_on_duplicate)
            )
            inserted += inserted_count
            updated += updated_count
            duplicates += dup_count
            actions.extend(batch_actions)
            errors.extend(batch_errors)

    except Exception as exc:
        print(f"[ERROR] Exception: {type(exc).__name__}: {exc}", flush=True)
        conn.rollback()
        errors.append(f"unexpected error: {exc}")
        raise
    finally:
        conn.close()

    return {
        "inserted": inserted,
        "updated": updated,
        "duplicates": duplicates,
        "invalid": invalid,
        "errors": errors,
        "actions": actions,
    }


def _process_batch(
    cursor,
    batch: List[tuple],
    update_on_duplicate: bool
) -> tuple[int, int, int, List[Dict[str, Any]], List[str]]:
    """
    Process batch using raw sqlite3 cursor.
    """
    print(f"[START] _process_batch with {len(batch)} records", flush=True)
    
    inserted, updated, duplicates = 0, 0, 0
    actions = []
    errors = []

    emails_in_batch = [rec[0] for rec in batch]
    print(f"[DEBUG] Extracted {len(emails_in_batch)} emails", flush=True)

    # Fetch existing recipients - SINGLE query
    try:
        print("[DEBUG] Querying existing recipients", flush=True)
        placeholders = ",".join(["?" for _ in emails_in_batch])
        query = f"SELECT email FROM recipients WHERE email IN ({placeholders})"
        print(f"[DEBUG] Query: {query}", flush=True)
        
        cursor.execute(query, emails_in_batch)
        existing_emails = {row[0] for row in cursor.fetchall()}
        print(f"[DEBUG] Found {len(existing_emails)} existing emails", flush=True)
    except Exception as e:
        print(f"[ERROR] Query failed: {e}", flush=True)
        errors.append(f"failed to fetch recipients: {e}")
        return 0, 0, 0, [], errors

    # Separate new and existing
    new_records = []
    
    for email, name, status, row_num in batch:
        if email in existing_emails:
            print(f"[DEBUG] Email {email} exists", flush=True)
            duplicates += 1
            actions.append({"row": row_num, "email": email, "action": "skipped"})
        else:
            print(f"[DEBUG] Email {email} is new", flush=True)
            new_records.append((email, name, status))
            inserted += 1
            actions.append({"row": row_num, "email": email, "action": "inserted"})

    # Bulk insert using executemany
    if new_records:
        print(f"[INFO] Bulk inserting {len(new_records)} records", flush=True)
        _bulk_insert_sqlite3(cursor, new_records)

    print(f"[END] _process_batch: inserted={inserted}, duplicates={duplicates}", flush=True)
    return inserted, updated, duplicates, actions, errors


def _bulk_insert_sqlite3(cursor, records: List[tuple]):
    """
    Pure sqlite3 bulk insert using executemany.
    This is what worked in the test.
    """
    print(f"[START] _bulk_insert_sqlite3 with {len(records)} records", flush=True)
    
    for attempt in range(MAX_RETRIES):
        try:
            print(f"[DEBUG] Attempt {attempt + 1}/{MAX_RETRIES}", flush=True)
            
            insert_sql = "INSERT INTO recipients (email, name, subscription_status) VALUES (?, ?, ?)"
            print(f"[DEBUG] SQL: {insert_sql}", flush=True)
            print(f"[DEBUG] Executing executemany with {len(records)} records", flush=True)
            
            cursor.executemany(insert_sql, records)
            print("[DEBUG] executemany completed", flush=True)
            
            print("[DEBUG] Committing", flush=True)
            cursor.connection.commit()
            print("[DEBUG] Committed successfully", flush=True)
            return

        except sqlite3.IntegrityError as e:
            print(f"[WARN] IntegrityError (attempt {attempt + 1}): {e}", flush=True)
            cursor.connection.rollback()
            print("[DEBUG] Ignoring duplicate constraint", flush=True)
            return

        except sqlite3.OperationalError as e:
            print(f"[WARN] OperationalError (attempt {attempt + 1}): {e}", flush=True)
            cursor.connection.rollback()
            
            if "database is locked" in str(e).lower() and attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt
                print(f"[WARN] Database locked, waiting {wait_time}s", flush=True)
                time.sleep(wait_time)
                continue
            else:
                print(f"[ERROR] Max retries or non-lock error", flush=True)
                raise

        except Exception as e:
            print(f"[ERROR] Unexpected error (attempt {attempt + 1}): {type(e).__name__}: {e}", flush=True)
            cursor.connection.rollback()
            raise

    print("[END] _bulk_insert_sqlite3 completed", flush=True)



def _process_batch(
    cursor,
    batch: List[tuple],
    update_on_duplicate: bool
) -> tuple[int, int, int, List[Dict[str, Any]], List[str]]:
    """
    Process batch using raw sqlite3 cursor.
    """
    inserted, updated, duplicates = 0, 0, 0
    actions = []
    errors = []

    emails_in_batch = [rec[0] for rec in batch]

    # Fetch existing recipients - SINGLE query
    try:
        placeholders = ",".join(["?" for _ in emails_in_batch])
        query = f"SELECT email FROM recipients WHERE email IN ({placeholders})"
        cursor.execute(query, emails_in_batch)
        existing_emails = {row[0] for row in cursor.fetchall()}
    except Exception as e:
        print(f"[ERROR] Query failed: {e}", flush=True)
        errors.append(f"failed to fetch recipients: {e}")
        return 0, 0, 0, [], errors

    # Separate new and existing
    new_records = []
    for email, name, status, row_num in batch:
        if email in existing_emails:
            duplicates += 1
            actions.append({"row": row_num, "email": email, "action": "skipped"})
        else:
            new_records.append((email, name, status))
            inserted += 1
            actions.append({"row": row_num, "email": email, "action": "inserted"})

    # Bulk insert using executemany
    if new_records:
        _bulk_insert_sqlite3(cursor, new_records)

    return inserted, updated, duplicates, actions, errors


def _bulk_insert_sqlite3(cursor, records: List[tuple]):
    """
    Pure sqlite3 bulk insert using executemany.
    """
    for attempt in range(MAX_RETRIES):
        try:
            insert_sql = "INSERT INTO recipients (email, name, subscription_status) VALUES (?, ?, ?)"
            cursor.executemany(insert_sql, records)
            cursor.connection.commit()
            return

        except sqlite3.IntegrityError as e:
            print(f"[ERROR] IntegrityError (attempt {attempt + 1}): {e}", flush=True)
            cursor.connection.rollback()
            return

        except sqlite3.OperationalError as e:
            print(f"[ERROR] OperationalError (attempt {attempt + 1}): {e}", flush=True)
            cursor.connection.rollback()
            if "database is locked" in str(e).lower() and attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            else:
                raise

        except Exception as e:
            print(f"[ERROR] Unexpected error (attempt {attempt + 1}): {type(e).__name__}: {e}", flush=True)
            cursor.connection.rollback()
            raise
