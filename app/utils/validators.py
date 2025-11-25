"""
Reusable validation helpers.

Install dependency if missing:
    pip install email-validator
"""
from typing import Optional
from email_validator import validate_email, EmailNotValidError


_ALLOWED_STATUSES = {
    "subscribed": "subscribed",
    "subscribe": "subscribed",
    "yes": "subscribed",
    "unsubscribed": "unsubscribed",
    "unsubscribe": "unsubscribed",
    "no": "unsubscribed",
}


def is_valid_email(email: str) -> bool:
    """
    Return True if email is syntactically valid according to email_validator.
    """
    try:
        validate_email(email)
        return True
    except EmailNotValidError:
        return False


def normalize_email(email: str) -> Optional[str]:
    """
    Validate and return a normalized email (lowercased, IDN handled) or None on invalid.
    Uses email_validator for robust normalization.
    """
    if not isinstance(email, str):
        return None
    try:
        result = validate_email(email)
        return result.email
    except EmailNotValidError:
        return None


def validate_subscription_status(value: str | None) -> str:
    """
    Normalize a subscription status string to one of:
      - "subscribed"
      - "unsubscribed"
    Raises ValueError for unknown/ambiguous values so callers can handle them as invalid.
    Accepts empty/None -> treat as "subscribed" (or change if you'd rather treat empty as invalid).
    """
    raw = (value or "").strip().lower()
    if raw == "":
        return "subscribed"
    if raw in _ALLOWED_STATUSES:
        return _ALLOWED_STATUSES[raw]
    raise ValueError(f"invalid subscription_status '{value}'")