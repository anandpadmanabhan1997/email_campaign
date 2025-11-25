from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from io import StringIO

from app.db import get_db
from app.services.csv_services import process_recipient_csv
from app.db.models import Recipient, Campaign

router = APIRouter()


@router.get("/", summary="List recipients")
def list_recipients(db: Session = Depends(get_db)) -> List[dict]:
    items = db.query(Recipient).order_by(Recipient.id.desc()).limit(500).all()
    return [r.as_dict() for r in items]


@router.post("/upload", summary="Upload recipients CSV")
async def upload_recipients(
    file: UploadFile = File(...),
    update_on_duplicate: bool = Form(False),
):
    try:
        print("upload",flush=True)

        contents = await file.read()
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError:
            text = contents.decode("latin-1")

        def run():
            print("run",flush=True)
            return process_recipient_csv(StringIO(text), update_on_duplicate=update_on_duplicate)

        try:
            result = await run_in_threadpool(run)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        return result

    except Exception as exc:
        print(exc.__class__.__name__, str(exc))
        raise HTTPException(status_code=500, detail=str(exc))




@router.delete("/clear", summary="Delete all recipients (dangerous!)")
def clear_recipients(confirm: bool = Query(False), db: Session = Depends(get_db)):
    """
    Delete all recipients. To avoid accidental deletion this endpoint requires the query
    parameter confirm=true. Example: DELETE /recipients/clear?confirm=true

    Additional safety: refuse to clear when there are campaigns in 'scheduled' or 'in_progress' status.
    Returns 409 with details about blocking campaigns.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide ?confirm=true to clear all recipients",
        )

    blocking_campaigns = (
        db.query(Campaign)
        .filter(Campaign.status.in_(["scheduled", "in_progress"]))
        .order_by(Campaign.id.asc())
        .all()
    )

    if blocking_campaigns:
        sample = [f"{c.id}:{c.name or 'untitled'}" for c in blocking_campaigns[:10]]
        detail_payload = {
            "message": "Cannot clear recipients while there are campaigns in scheduled/in_progress state",
            "count": len(blocking_campaigns),
            "campaigns": sample,
        }
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail_payload)

    deleted = db.query(Recipient).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}